let currentEtag = "";
let allFiles = [];
let pollingHandle = null;
let isBusy = false;
let actionModalState = null;
let currentPreviewFilename = "";

const capabilityState = {
  download: false,
  delete: false,
};

function getActionModalElements() {
  return {
    backdrop: document.getElementById("actionAuthModal"),
    title: document.getElementById("actionModalTitle"),
    desc: document.getElementById("actionModalDesc"),
    input: document.getElementById("actionPasswordInput"),
    error: document.getElementById("actionModalError"),
    confirm: document.getElementById("actionModalConfirm"),
  };
}

function getInlinePreviewElements() {
  return {
    backdrop: document.getElementById("inlinePreviewModal"),
    body: document.getElementById("inlinePreviewBody"),
    title: document.getElementById("inlinePreviewTitle"),
    download: document.getElementById("inlinePreviewDownload"),
  };
}

function setActionStatus(message, kind = "info") {
  const node = document.getElementById("actionStatus");
  if (!node) {
    return;
  }
  node.textContent = message || "";
  node.className = `action-status ${kind}`.trim();
}

function closeActionModal(result = false) {
  const { backdrop, input, error, confirm } = getActionModalElements();
  backdrop.hidden = true;
  input.value = "";
  error.textContent = "";
  confirm.disabled = false;
  if (actionModalState?.resolve) {
    const { resolve } = actionModalState;
    actionModalState = null;
    resolve(result);
  }
}

function openActionModal(config) {
  const { backdrop, title, desc, input, error, confirm } = getActionModalElements();
  title.textContent = config.title;
  desc.textContent = config.description;
  confirm.textContent = config.confirmText;
  input.value = "";
  error.textContent = "";
  backdrop.hidden = false;
  window.setTimeout(() => input.focus(), 0);
  return new Promise((resolve) => {
    actionModalState = { ...config, resolve };
  });
}

async function confirmActionModal() {
  if (!actionModalState) {
    return;
  }
  const { input, error, confirm } = getActionModalElements();
  const password = input.value.trim();
  if (!password) {
    error.textContent = "请输入密码。";
    return;
  }
  const originalText = actionModalState.confirmText;
  confirm.disabled = true;
  confirm.textContent = "验证中...";
  error.textContent = "";
  try {
    const response = await fetch("/api/unlock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ability: actionModalState.ability, password }),
      credentials: "same-origin",
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      error.textContent = payload.message || "密码错误，请重试。";
      confirm.disabled = false;
      confirm.textContent = originalText;
      return;
    }
    capabilityState[actionModalState.ability] = true;
    closeActionModal(true);
  } catch (_error) {
    error.textContent = "验证失败，请稍后重试。";
    confirm.disabled = false;
    confirm.textContent = originalText;
  }
}

async function fetchSession() {
  const response = await fetch("/api/session", { credentials: "same-origin" });
  if (!response.ok) {
    return;
  }
  const payload = await response.json();
  capabilityState.download = Boolean(payload.capabilities?.download);
  capabilityState.delete = Boolean(payload.capabilities?.delete);
  const noteField = document.getElementById("accountNote");
  if (noteField && document.activeElement !== noteField) {
    noteField.value = payload.note || "";
  }
}

function escapeHtml(value) {
  return String(value == null ? "" : value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

const noteTimers = new Map();

function noteStatusFor(field) {
  const block = field.closest(".note-block");
  return block ? block.querySelector(".note-status") : null;
}

function queueNoteSave(key, field, buildRequest, onSaved) {
  const existing = noteTimers.get(key);
  if (existing) {
    window.clearTimeout(existing);
  }
  const status = noteStatusFor(field);
  if (status) {
    status.textContent = "输入中…";
    status.className = "note-status";
  }
  noteTimers.set(key, window.setTimeout(async () => {
    noteTimers.delete(key);
    const { url, body } = buildRequest(field.value);
    try {
      const response = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        credentials: "same-origin",
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.message || `保存失败 (${response.status})`);
      }
      if (status) {
        status.textContent = "已保存";
        status.className = "note-status success";
      }
      if (onSaved) {
        onSaved(field.value);
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message || "保存失败";
        status.className = "note-status error";
      }
    }
  }, 600));
}

function getFileExtension(filename) {
  const dotIndex = filename.lastIndexOf(".");
  return dotIndex >= 0 ? filename.slice(dotIndex).toLowerCase() : "";
}

const IMAGE_EXTS = new Set([".jpg", ".jpeg", ".jfif", ".pjpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico", ".avif", ".apng"]);
const AUDIO_EXTS = new Set([".mp3", ".wav", ".ogg", ".oga", ".m4a", ".aac", ".flac", ".opus", ".weba"]);
const VIDEO_EXTS = new Set([".mp4", ".webm", ".mov", ".m4v", ".ogv", ".3gp"]);

function classifyPreviewTarget(filename) {
  const ext = getFileExtension(filename);
  if (IMAGE_EXTS.has(ext)) return "image";
  if (AUDIO_EXTS.has(ext)) return "audio";
  if (VIDEO_EXTS.has(ext)) return "video";
  // 其余格式统一交给服务端预览页渲染（文本 / Markdown / 表格 / JSON / PDF / Office 等）。
  return "page";
}

async function ensureCapabilityAndRun(ability, modalConfig, action) {
  if (!capabilityState[ability]) {
    const verified = await openActionModal(modalConfig);
    if (!verified) {
      setActionStatus(`已取消${modalConfig.confirmText}。`, "info");
      return;
    }
  }
  await action();
}

async function loadFiles(force = false) {
  if (isBusy && !force) {
    return;
  }
  const url = !force && currentEtag
    ? `/api/files?since=${encodeURIComponent(currentEtag)}`
    : "/api/files";
  const response = await fetch(url, { credentials: "same-origin" });
  if (response.status === 401) {
    window.location.href = "/login";
    return;
  }
  if (!response.ok) {
    throw new Error(`文件列表加载失败 (${response.status})`);
  }
  const payload = await response.json();
  if (payload.changed === false) {
    return;
  }
  currentEtag = payload.etag;
  allFiles = payload.files || [];
  renderFiles();
}

function renderFiles() {
  const root = document.getElementById("fileList");
  const query = (document.getElementById("searchInput")?.value || "").toLowerCase();
  const visibleFiles = allFiles.filter((item) => item.name.toLowerCase().includes(query));
  const active = document.activeElement;
  const activeName = active && active.classList.contains("note-input") ? active.dataset.noteName : null;
  const caret = activeName ? active.selectionStart : 0;
  root.innerHTML = visibleFiles.map((file) => `
    <article class="file-card">
      <div>
        <div class="file-name">${file.name}</div>
        <div class="file-meta">${file.modified_text || ""}</div>
      </div>
      <div class="file-meta">${Math.max(1, Math.round((file.size_bytes || 0) / 1024))} KB</div>
      <div class="note-block">
        <textarea class="note-input" data-note-name="${file.name}" rows="2" placeholder="文件备注（输入即存，仅文字）">${escapeHtml(file.note || "")}</textarea>
        <span class="note-status"></span>
      </div>
      <div class="file-actions">
        <button type="button" data-action="preview" data-name="${file.name}">预览</button>
        <button type="button" data-action="download" data-name="${file.name}">下载</button>
        <button type="button" data-delete="${file.name}">删除</button>
      </div>
    </article>
  `).join("");
  if (activeName) {
    const restored = Array.from(root.querySelectorAll(".note-input"))
      .find((node) => node.dataset.noteName === activeName);
    if (restored) {
      restored.focus();
      try {
        restored.selectionStart = restored.selectionEnd = caret;
      } catch (_error) {
        // Some browsers reject caret restore on certain input types.
      }
    }
  }
}

function isIosDevice() {
  const ua = navigator.userAgent || "";
  return /iP(hone|ad|od)/.test(ua) || (ua.includes("Macintosh") && navigator.maxTouchPoints > 1);
}

function setUploadProgress(percent) {
  const wrap = document.getElementById("uploadProgress");
  const bar = document.getElementById("uploadProgressBar");
  if (!wrap || !bar) {
    return;
  }
  if (percent === null || percent === undefined) {
    wrap.hidden = true;
    bar.style.width = "0%";
    return;
  }
  wrap.hidden = false;
  bar.style.width = `${Math.max(0, Math.min(100, percent))}%`;
}

function setUploadBusy(busy) {
  document.querySelectorAll("[data-upload-trigger]").forEach((button) => {
    button.disabled = busy;
  });
}

function uploadWithProgress(url, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.withCredentials = true;
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable && onProgress) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    });
    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve();
        return;
      }
      if (xhr.status === 401) {
        window.location.href = "/login";
        reject(new Error("登录已过期，请重新登录。"));
        return;
      }
      reject(new Error(`上传失败 (${xhr.status})`));
    });
    xhr.addEventListener("error", () => reject(new Error("网络异常，上传失败，请检查网络后重试。")));
    xhr.addEventListener("timeout", () => reject(new Error("上传超时，请重试。")));
    const formData = new FormData();
    formData.append("file", file);
    xhr.send(formData);
  });
}

async function uploadFiles(fileList) {
  const files = Array.from(fileList || []);
  if (files.length === 0) {
    return;
  }
  const status = document.getElementById("uploadStatus");
  const total = files.length;
  isBusy = true;
  setUploadBusy(true);
  let done = 0;
  try {
    for (let index = 0; index < total; index += 1) {
      const file = files[index];
      const prefix = total > 1 ? `(${index + 1}/${total}) ` : "";
      if (status) {
        status.textContent = `${prefix}正在上传 ${file.name}...`;
      }
      setUploadProgress(0);
      await uploadWithProgress("/api/upload", file, (percent) => {
        if (status) {
          status.textContent = `${prefix}正在上传 ${file.name}：${percent}%`;
        }
        setUploadProgress(percent);
      });
      done += 1;
    }
    if (status) {
      status.textContent = `上传完成，共 ${done} 个文件`;
    }
    setActionStatus("文件上传完成，列表已刷新。", "success");
    await loadFiles(true);
  } catch (error) {
    if (status) {
      status.textContent = "";
    }
    setActionStatus(error.message || "上传失败。", "error");
  } finally {
    setUploadProgress(null);
    setUploadBusy(false);
    isBusy = false;
  }
}

function triggerBrowserDownload(filename) {
  const url = `/download/${encodeURIComponent(filename)}`;
  if (isIosDevice()) {
    // iOS Safari 对 download 属性支持有限，直接导航由服务端 Content-Disposition 触发下载。
    window.location.href = url;
    return;
  }
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.style.display = "none";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

function closeInlinePreview() {
  const { backdrop, body } = getInlinePreviewElements();
  backdrop.hidden = true;
  body.innerHTML = "";
  currentPreviewFilename = "";
}

function openInlinePreview(filename) {
  const type = classifyPreviewTarget(filename);
  const { backdrop, body, title } = getInlinePreviewElements();
  const sourceUrl = `/preview/${encodeURIComponent(filename)}`;
  backdrop.hidden = false;
  title.textContent = `预览：${filename}`;
  currentPreviewFilename = filename;
  if (type === "image") {
    body.innerHTML = `<img src="${sourceUrl}" alt="${escapeHtml(filename)}">`;
    return;
  }
  if (type === "audio") {
    body.innerHTML = `<audio controls autoplay src="${sourceUrl}"></audio>`;
    return;
  }
  body.innerHTML = `<video controls autoplay playsinline preload="metadata" src="${sourceUrl}"></video>`;
}

function openPagePreview(filename) {
  window.open(`/view/${encodeURIComponent(filename)}`, "_blank", "noopener");
}

async function deleteFile(filename) {
  await ensureCapabilityAndRun(
    "delete",
    {
      ability: "delete",
      title: "请输入删除密码",
      description: `删除文件 “${filename}” 会将其移入回收站（仅隐藏，未真正删除）。`,
      confirmText: "移入回收站",
    },
    async () => {
      isBusy = true;
      const response = await fetch("/api/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
        credentials: "same-origin",
      });
      if (response.ok) {
        setActionStatus(`已移入回收站：${filename}`, "success");
        await loadFiles(true);
      } else {
        let message = "删除失败，请确认删除密码是否正确。";
        try {
          const payload = await response.json();
          if (payload?.message) {
            message = `删除失败：${payload.message}`;
          }
        } catch (_error) {
          // Ignore JSON parse failures and keep fallback text.
        }
        setActionStatus(message, "error");
      }
      isBusy = false;
    },
  );
}

async function previewFile(filename) {
  if (classifyPreviewTarget(filename) === "page") {
    openPagePreview(filename);
    setActionStatus(`已在新页面打开预览：${filename}`, "success");
    return;
  }
  openInlinePreview(filename);
  setActionStatus(`正在预览：${filename}`, "success");
}

async function downloadFile(filename) {
  await ensureCapabilityAndRun(
    "download",
    {
      ability: "download",
      title: "请输入下载密码",
      description: `下载文件 “${filename}” 前，需要先验证下载密码。`,
      confirmText: "开始下载",
    },
    async () => {
      triggerBrowserDownload(filename);
      setActionStatus(
        isIosDevice()
          ? `已开始下载：${filename}。请到「文件」App 的「下载」中查看。`
          : `已开始下载：${filename}`,
        "success",
      );
    },
  );
}

function handleFileAction(action, filename) {
  if (action === "preview") {
    previewFile(filename).catch((error) => {
      setActionStatus(error.message || "预览失败。", "error");
    });
    return;
  }
  if (action === "download") {
    downloadFile(filename).catch((error) => {
      setActionStatus(error.message || "下载失败。", "error");
    });
    return;
  }
  if (action === "delete") {
    deleteFile(filename).catch((error) => {
      isBusy = false;
      setActionStatus(error.message || "删除失败。", "error");
    });
  }
}

function startPolling() {
  clearInterval(pollingHandle);
  pollingHandle = window.setInterval(() => {
    loadFiles(false).catch((error) => {
      if (document.visibilityState === "hidden") {
        return;
      }
      setActionStatus(error.message || "文件列表刷新失败。", "error");
    });
  }, 5000);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("refreshBtn")?.addEventListener("click", () => {
    loadFiles(true)
      .then(() => setActionStatus("已手动刷新文件列表。", "success"))
      .catch((error) => setActionStatus(error.message || "刷新失败。", "error"));
  });
  document.getElementById("uploadBtn")?.addEventListener("click", () => {
    document.getElementById("fileInput")?.click();
  });
  document.getElementById("cameraBtn")?.addEventListener("click", () => {
    document.getElementById("cameraInput")?.click();
  });
  const handlePickedFiles = (event) => {
    const chosen = Array.from(event.target.files || []);
    event.target.value = "";
    uploadFiles(chosen);
  };
  document.getElementById("fileInput")?.addEventListener("change", handlePickedFiles);
  document.getElementById("cameraInput")?.addEventListener("change", handlePickedFiles);
  document.getElementById("searchInput")?.addEventListener("input", () => renderFiles());
  document.getElementById("fileList")?.addEventListener("input", (event) => {
    const field = event.target;
    if (!field.classList?.contains("note-input")) {
      return;
    }
    const name = field.dataset.noteName || "";
    queueNoteSave(
      `file:${name}`,
      field,
      (value) => ({ url: "/api/note", body: { filename: name, note: value } }),
      (value) => {
        const file = allFiles.find((item) => item.name === name);
        if (file) {
          file.note = value;
        }
      },
    );
  });
  document.getElementById("accountNote")?.addEventListener("input", (event) => {
    queueNoteSave("account", event.target, (value) => ({
      url: "/api/account-note",
      body: { note: value },
    }));
  });
  document.getElementById("fileList")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action], button[data-delete]");
    if (!button) {
      return;
    }
    if (button.dataset.delete) {
      handleFileAction("delete", button.dataset.delete);
      return;
    }
    handleFileAction(button.dataset.action, button.dataset.name);
  });
  document.getElementById("actionModalCancel")?.addEventListener("click", () => {
    closeActionModal(false);
  });
  document.getElementById("actionModalConfirm")?.addEventListener("click", () => {
    confirmActionModal();
  });
  document.getElementById("actionPasswordInput")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      confirmActionModal();
    }
    if (event.key === "Escape") {
      closeActionModal(false);
    }
  });
  document.getElementById("actionAuthModal")?.addEventListener("click", (event) => {
    if (event.target.id === "actionAuthModal") {
      closeActionModal(false);
    }
  });
  document.getElementById("inlinePreviewClose")?.addEventListener("click", () => {
    closeInlinePreview();
  });
  document.getElementById("inlinePreviewDownload")?.addEventListener("click", () => {
    if (currentPreviewFilename) {
      downloadFile(currentPreviewFilename).catch((error) => {
        setActionStatus(error.message || "下载失败。", "error");
      });
    }
  });
  document.getElementById("inlinePreviewModal")?.addEventListener("click", (event) => {
    if (event.target.id === "inlinePreviewModal") {
      closeInlinePreview();
    }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !document.getElementById("inlinePreviewModal")?.hidden) {
      closeInlinePreview();
    }
  });
  Promise.allSettled([fetchSession(), loadFiles(true)]).then((results) => {
    const loadResult = results[1];
    if (loadResult.status === "fulfilled") {
      setActionStatus("文件列表已加载。", "success");
    } else {
      setActionStatus(loadResult.reason?.message || "文件列表加载失败。", "error");
    }
  });
  startPolling();
});
