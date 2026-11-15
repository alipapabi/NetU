/* NetU — 内置二维码编码器（零第三方依赖，完全离线）
 * 仅支持 8-bit 字节模式，覆盖 QR 标准的版本 1-40 与 L/M/Q/H 四级纠错。
 * 对外接口：
 *   NetUQR.encode(text, ecLevel) -> { size, modules }   modules[y][x] = true 表示深色模块
 *   NetUQR.draw(canvas, text, options)                  直接绘制到 <canvas>
 * 参数表（每块纠错码字数 / 纠错块数）取自 QR 标准 ISO/IEC 18004。
 */
(function (global) {
  "use strict";

  const ECC_PER_BLOCK = {
    L: [7, 10, 15, 20, 26, 18, 20, 24, 30, 18, 20, 24, 26, 30, 22, 24, 28, 30, 28, 28, 28, 28, 30, 30, 26, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    M: [10, 16, 26, 18, 24, 16, 18, 22, 22, 26, 30, 22, 22, 24, 24, 28, 28, 26, 26, 26, 26, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28, 28],
    Q: [13, 22, 18, 26, 18, 24, 18, 22, 20, 24, 28, 26, 24, 20, 30, 24, 28, 28, 26, 30, 28, 30, 30, 30, 30, 28, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
    H: [17, 28, 22, 16, 22, 28, 26, 26, 24, 28, 24, 28, 22, 24, 24, 30, 28, 28, 26, 28, 30, 24, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30, 30],
  };

  const ECC_BLOCKS = {
    L: [1, 1, 1, 1, 1, 2, 2, 2, 2, 4, 4, 4, 4, 4, 6, 6, 6, 6, 7, 8, 8, 9, 9, 10, 12, 12, 12, 13, 14, 15, 16, 17, 18, 19, 19, 20, 21, 22, 24, 25],
    M: [1, 1, 1, 2, 2, 4, 4, 4, 5, 5, 5, 8, 9, 9, 10, 10, 11, 13, 14, 16, 17, 17, 18, 20, 21, 23, 25, 26, 28, 29, 31, 33, 35, 37, 38, 40, 43, 45, 47, 49],
    Q: [1, 1, 2, 2, 4, 4, 6, 6, 8, 8, 8, 10, 12, 16, 12, 17, 16, 18, 21, 20, 23, 23, 25, 27, 29, 34, 34, 35, 38, 40, 43, 45, 48, 51, 53, 56, 59, 62, 65, 68],
    H: [1, 1, 2, 4, 4, 4, 5, 6, 8, 8, 11, 11, 16, 16, 18, 16, 19, 21, 25, 25, 25, 34, 30, 32, 35, 37, 40, 42, 45, 48, 51, 54, 57, 60, 63, 66, 70, 74, 77, 81],
  };

  // 纠错等级在格式信息中的两位编码
  const FORMAT_BITS = { L: 1, M: 0, Q: 3, H: 2 };
  const LEVELS = ["L", "M", "Q", "H"];

  // ---- GF(256) 有限域运算，生成多项式为本原多项式 0x11D ----
  const GF_EXP = new Uint8Array(512);
  const GF_LOG = new Uint8Array(256);
  (function initGaloisField() {
    let value = 1;
    for (let i = 0; i < 255; i += 1) {
      GF_EXP[i] = value;
      GF_LOG[value] = i;
      value <<= 1;
      if (value & 0x100) {
        value ^= 0x11d;
      }
    }
    for (let i = 255; i < 512; i += 1) {
      GF_EXP[i] = GF_EXP[i - 255];
    }
  })();

  function gfMultiply(a, b) {
    if (a === 0 || b === 0) {
      return 0;
    }
    return GF_EXP[GF_LOG[a] + GF_LOG[b]];
  }

  // 生成多项式 (x-α^0)(x-α^1)...(x-α^(degree-1))
  // 内部按升幂累积，返回时反转为降幂（首位系数恒为 1），与下面的除法实现对应。
  function reedSolomonGenerator(degree) {
    let poly = [1];
    for (let i = 0; i < degree; i += 1) {
      const next = new Array(poly.length + 1).fill(0);
      for (let j = 0; j < poly.length; j += 1) {
        next[j] ^= gfMultiply(poly[j], GF_EXP[i]);
        next[j + 1] ^= poly[j];
      }
      poly = next;
    }
    return poly.reverse();
  }

  function reedSolomonRemainder(data, generator) {
    const remainder = new Array(generator.length - 1).fill(0);
    for (let i = 0; i < data.length; i += 1) {
      const factor = data[i] ^ remainder[0];
      remainder.shift();
      remainder.push(0);
      for (let j = 0; j < remainder.length; j += 1) {
        remainder[j] ^= gfMultiply(generator[j + 1], factor);
      }
    }
    return remainder;
  }

  // ---- 容量计算 ----
  function rawDataModules(version) {
    let result = (16 * version + 128) * version + 64;
    if (version >= 2) {
      const alignCount = Math.floor(version / 7) + 2;
      result -= (25 * alignCount - 10) * alignCount - 55;
      if (version >= 7) {
        result -= 36;
      }
    }
    return result;
  }

  function rawCodewords(version) {
    return Math.floor(rawDataModules(version) / 8);
  }

  function dataCodewords(version, level) {
    return rawCodewords(version) - ECC_PER_BLOCK[level][version - 1] * ECC_BLOCKS[level][version - 1];
  }

  function utf8Bytes(text) {
    const encoded = encodeURIComponent(text);
    const bytes = [];
    for (let i = 0; i < encoded.length; i += 1) {
      if (encoded[i] === "%") {
        bytes.push(parseInt(encoded.substr(i + 1, 2), 16));
        i += 2;
      } else {
        bytes.push(encoded.charCodeAt(i));
      }
    }
    return bytes;
  }

  function chooseVersion(byteLength, level) {
    for (let version = 1; version <= 40; version += 1) {
      const countBits = version <= 9 ? 8 : 16;
      if (4 + countBits + byteLength * 8 <= dataCodewords(version, level) * 8) {
        return version;
      }
    }
    throw new Error("内容过长，超出二维码容量上限");
  }

  // ---- 数据位流 ----
  function buildCodewords(bytes, version, level) {
    const totalData = dataCodewords(version, level);
    const bits = [];
    const push = (value, length) => {
      for (let i = length - 1; i >= 0; i -= 1) {
        bits.push((value >>> i) & 1);
      }
    };
    push(0b0100, 4); // 字节模式
    push(bytes.length, version <= 9 ? 8 : 16);
    for (let i = 0; i < bytes.length; i += 1) {
      push(bytes[i], 8);
    }
    // 结束符 + 补零对齐到字节
    push(0, Math.min(4, totalData * 8 - bits.length));
    push(0, (8 - (bits.length % 8)) % 8);
    // 填充字节 0xEC / 0x11 交替，直到填满
    for (let pad = 0xec; bits.length < totalData * 8; pad ^= 0xec ^ 0x11) {
      push(pad, 8);
    }

    const codewords = [];
    for (let i = 0; i < bits.length; i += 8) {
      let value = 0;
      for (let j = 0; j < 8; j += 1) {
        value = (value << 1) | bits[i + j];
      }
      codewords.push(value);
    }

    // 分块并计算纠错码字，再按标准规则交错排列
    const blockCount = ECC_BLOCKS[level][version - 1];
    const eccLength = ECC_PER_BLOCK[level][version - 1];
    const shortBlocks = blockCount - (rawCodewords(version) % blockCount);
    const shortBlockLength = Math.floor(rawCodewords(version) / blockCount);
    const generator = reedSolomonGenerator(eccLength);
    const dataBlocks = [];
    const eccBlocks = [];
    let offset = 0;
    for (let i = 0; i < blockCount; i += 1) {
      const length = shortBlockLength - eccLength + (i < shortBlocks ? 0 : 1);
      const chunk = codewords.slice(offset, offset + length);
      offset += length;
      dataBlocks.push(chunk);
      eccBlocks.push(reedSolomonRemainder(chunk, generator));
    }

    const result = [];
    for (let i = 0; i < shortBlockLength - eccLength + 1; i += 1) {
      for (let b = 0; b < blockCount; b += 1) {
        if (i < dataBlocks[b].length) {
          result.push(dataBlocks[b][i]);
        }
      }
    }
    for (let i = 0; i < eccLength; i += 1) {
      for (let b = 0; b < blockCount; b += 1) {
        result.push(eccBlocks[b][i]);
      }
    }
    return result;
  }

  // ---- 矩阵绘制 ----
  function alignmentPositions(version) {
    if (version === 1) {
      return [];
    }
    const count = Math.floor(version / 7) + 2;
    const step = version === 32 ? 26 : Math.ceil((version * 4 + 4) / (count * 2 - 2)) * 2;
    const result = [6];
    for (let pos = version * 4 + 10; result.length < count; pos -= step) {
      result.splice(1, 0, pos);
    }
    return result;
  }

  function buildMatrix(codewords, version, level) {
    const size = version * 4 + 17;
    const modules = [];
    const isFunction = [];
    for (let y = 0; y < size; y += 1) {
      modules.push(new Array(size).fill(false));
      isFunction.push(new Array(size).fill(false));
    }

    const setFunction = (x, y, dark) => {
      modules[y][x] = dark;
      isFunction[y][x] = true;
    };

    // 定位图形（三个角）
    const drawFinder = (cx, cy) => {
      for (let dy = -4; dy <= 4; dy += 1) {
        for (let dx = -4; dx <= 4; dx += 1) {
          const x = cx + dx;
          const y = cy + dy;
          if (x < 0 || x >= size || y < 0 || y >= size) {
            continue;
          }
          const dist = Math.max(Math.abs(dx), Math.abs(dy));
          setFunction(x, y, dist !== 2 && dist !== 4);
        }
      }
    };
    // 校正图形
    const drawAlignment = (cx, cy) => {
      for (let dy = -2; dy <= 2; dy += 1) {
        for (let dx = -2; dx <= 2; dx += 1) {
          setFunction(cx + dx, cy + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
        }
      }
    };

    // 定时图形
    for (let i = 0; i < size; i += 1) {
      setFunction(6, i, i % 2 === 0);
      setFunction(i, 6, i % 2 === 0);
    }
    drawFinder(3, 3);
    drawFinder(size - 4, 3);
    drawFinder(3, size - 4);

    const alignPositions = alignmentPositions(version);
    const alignCount = alignPositions.length;
    for (let i = 0; i < alignCount; i += 1) {
      for (let j = 0; j < alignCount; j += 1) {
        const corner = (i === 0 && j === 0) || (i === 0 && j === alignCount - 1) || (i === alignCount - 1 && j === 0);
        if (!corner) {
          drawAlignment(alignPositions[i], alignPositions[j]);
        }
      }
    }

    // 版本信息（版本 7 起）
    if (version >= 7) {
      let rem = version;
      for (let i = 0; i < 12; i += 1) {
        rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
      }
      const versionBits = (version << 12) | rem;
      for (let i = 0; i < 18; i += 1) {
        const bit = ((versionBits >>> i) & 1) === 1;
        const a = size - 11 + (i % 3);
        const b = Math.floor(i / 3);
        setFunction(a, b, bit);
        setFunction(b, a, bit);
      }
    }

    const drawFormat = (mask) => {
      const data = (FORMAT_BITS[level] << 3) | mask;
      let rem = data;
      for (let i = 0; i < 10; i += 1) {
        rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
      }
      const bits = ((data << 10) | rem) ^ 0x5412;
      const get = (index) => ((bits >>> index) & 1) === 1;
      for (let i = 0; i <= 5; i += 1) {
        setFunction(8, i, get(i));
      }
      setFunction(8, 7, get(6));
      setFunction(8, 8, get(7));
      setFunction(7, 8, get(8));
      for (let i = 9; i < 15; i += 1) {
        setFunction(14 - i, 8, get(i));
      }
      for (let i = 0; i < 8; i += 1) {
        setFunction(size - 1 - i, 8, get(i));
      }
      for (let i = 8; i < 15; i += 1) {
        setFunction(8, size - 15 + i, get(i));
      }
      setFunction(8, size - 8, true); // 固定深色模块
    };
    drawFormat(0);

    // 数据填充：自右下角起“之”字形走位
    let bitIndex = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) {
        right = 5;
      }
      for (let vert = 0; vert < size; vert += 1) {
        for (let j = 0; j < 2; j += 1) {
          const x = right - j;
          const upward = ((right + 1) & 2) === 0;
          const y = upward ? size - 1 - vert : vert;
          if (!isFunction[y][x] && bitIndex < codewords.length * 8) {
            modules[y][x] = ((codewords[bitIndex >>> 3] >>> (7 - (bitIndex & 7))) & 1) === 1;
            bitIndex += 1;
          }
        }
      }
    }

    const applyMask = (mask) => {
      for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
          if (isFunction[y][x]) {
            continue;
          }
          let invert;
          switch (mask) {
            case 0: invert = (x + y) % 2 === 0; break;
            case 1: invert = y % 2 === 0; break;
            case 2: invert = x % 3 === 0; break;
            case 3: invert = (x + y) % 3 === 0; break;
            case 4: invert = (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0; break;
            case 5: invert = ((x * y) % 2) + ((x * y) % 3) === 0; break;
            case 6: invert = (((x * y) % 2) + ((x * y) % 3)) % 2 === 0; break;
            default: invert = (((x + y) % 2) + ((x * y) % 3)) % 2 === 0; break;
          }
          if (invert) {
            modules[y][x] = !modules[y][x];
          }
        }
      }
    };

    const addHistory = (runLength, history) => {
      if (history[0] === 0) {
        runLength += size; // 起始 run 补上静默区
      }
      history.pop();
      history.unshift(runLength);
    };
    const countPatterns = (history) => {
      const n = history[1];
      const core = n > 0 && history[2] === n && history[3] === n * 3 && history[4] === n && history[5] === n;
      return (core && history[0] >= n * 4 && history[6] >= n ? 1 : 0) + (core && history[6] >= n * 4 && history[0] >= n ? 1 : 0);
    };
    const terminateAndCount = (runColor, runLength, history) => {
      if (runColor) {
        addHistory(runLength, history);
        runLength = 0;
      }
      addHistory(runLength + size, history);
      return countPatterns(history);
    };

    const penalty = () => {
      let score = 0;
      for (let y = 0; y < size; y += 1) {
        let runColor = false;
        let runLength = 0;
        const history = [0, 0, 0, 0, 0, 0, 0];
        for (let x = 0; x < size; x += 1) {
          if (modules[y][x] === runColor) {
            runLength += 1;
            score += runLength === 5 ? 3 : runLength > 5 ? 1 : 0;
          } else {
            addHistory(runLength, history);
            if (!runColor) {
              score += countPatterns(history) * 40;
            }
            runColor = modules[y][x];
            runLength = 1;
          }
        }
        score += terminateAndCount(runColor, runLength, history) * 40;
      }
      for (let x = 0; x < size; x += 1) {
        let runColor = false;
        let runLength = 0;
        const history = [0, 0, 0, 0, 0, 0, 0];
        for (let y = 0; y < size; y += 1) {
          if (modules[y][x] === runColor) {
            runLength += 1;
            score += runLength === 5 ? 3 : runLength > 5 ? 1 : 0;
          } else {
            addHistory(runLength, history);
            if (!runColor) {
              score += countPatterns(history) * 40;
            }
            runColor = modules[y][x];
            runLength = 1;
          }
        }
        score += terminateAndCount(runColor, runLength, history) * 40;
      }
      for (let y = 0; y < size - 1; y += 1) {
        for (let x = 0; x < size - 1; x += 1) {
          const color = modules[y][x];
          if (color === modules[y][x + 1] && color === modules[y + 1][x] && color === modules[y + 1][x + 1]) {
            score += 3;
          }
        }
      }
      let dark = 0;
      for (let y = 0; y < size; y += 1) {
        for (let x = 0; x < size; x += 1) {
          if (modules[y][x]) {
            dark += 1;
          }
        }
      }
      const total = size * size;
      score += (Math.ceil(Math.abs(dark * 20 - total * 10) / total) - 1) * 10;
      return score;
    };

    const snapshot = () => modules.map((row) => row.slice());
    const best = { score: Infinity, mask: 0, matrix: null };
    for (let mask = 0; mask < 8; mask += 1) {
      applyMask(mask);
      drawFormat(mask);
      const score = penalty();
      if (score < best.score) {
        best.score = score;
        best.mask = mask;
        best.matrix = snapshot();
      }
      applyMask(mask); // 掩码与格式位都是可逆的，异或回去即可还原
    }
    return best.matrix;
  }

  function encode(text, ecLevel) {
    const level = LEVELS.indexOf(ecLevel) >= 0 ? ecLevel : "M";
    const bytes = utf8Bytes(String(text));
    const version = chooseVersion(bytes.length, level);
    const codewords = buildCodewords(bytes, version, level);
    const modules = buildMatrix(codewords, version, level);
    return { size: modules.length, version: version, level: level, modules: modules };
  }

  function draw(canvas, text, options) {
    const settings = Object.assign(
      { ecLevel: "M", scale: 6, margin: 4, dark: "#0b1626", light: "#ffffff" },
      options || {}
    );
    const qr = encode(text, settings.ecLevel);
    const side = (qr.size + settings.margin * 2) * settings.scale;
    canvas.width = side;
    canvas.height = side;
    const context = canvas.getContext("2d");
    context.fillStyle = settings.light;
    context.fillRect(0, 0, side, side);
    context.fillStyle = settings.dark;
    for (let y = 0; y < qr.size; y += 1) {
      for (let x = 0; x < qr.size; x += 1) {
        if (qr.modules[y][x]) {
          context.fillRect(
            (x + settings.margin) * settings.scale,
            (y + settings.margin) * settings.scale,
            settings.scale,
            settings.scale
          );
        }
      }
    }
    return qr;
  }

  global.NetUQR = { encode: encode, draw: draw };
})(typeof window !== "undefined" ? window : globalThis);
