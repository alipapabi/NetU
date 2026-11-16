let accounts = [];
let editingUsername = "";
let currentEtag = "";
let defaultExpireDays = "30";
let allFiles = [];
let allHidden = [];
let visibleFileCount = 40;
const FILE_PAGE_SIZE = 40;
const RANDOM_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";
const SUPERADMIN_USER = "superadmin";

function randomPassword() {
  const length = 4 + Math.floor(Math.random() * 3);
  let result = "";
  const values = new Uint32Array(length);
  if (window.crypto?.getRandomValues) {
    window.crypto.getRandomValues(values);
    for (let i = 0; i < length; i += 1) {
      result += RANDOM_CHARS[values[i] % RANDOM_CHARS.length];
    }
    return result;
  }
  for (let i = 0; i < length; i += 1) {
    result += RANDOM_CHARS[Math.floor(Math.random() * RANDOM_CHARS.length)];
  }
  return result;
}

function setShareStatus(message, kind = "info") {
  const node = document.getElementById("shareStatus");
  if (!node) {
    return;
  }
  node.textContent = message || "";
  node.className = `file-meta ${kind}`.trim();
}

const ADMIN_TAB_KEY = "netu-admin-tab";

function activateTab(name) {
  const target = name || "accounts";
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === target;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.hidden = panel.dataset.panel !== target;
  });
  try {
    window.localStorage.setItem(ADMIN_TAB_KEY, target);
  } catch (_error) {
    // 隐私模式下无法写入本地存储，忽略即可。
  }
  if (target === "activity") {
    loadActivity(SUPERADMIN_USER, "activityList", setActivityStatus);
  }
}

function restoreTab() {
  let saved = "";
  try {
    saved = window.localStorage.getItem(ADMIN_TAB_KEY) || "";
  } catch (_error) {
    saved = "";
  }
  const exists = Array.from(document.querySelectorAll(".tab")).some((tab) => tab.dataset.tab === saved);
  activateTab(exists ? saved : "accounts");
}

function renderShareQr(loginLink, siteUrl) {
  if (!window.NetUQR) {
    return;
  }
  const options = { ecLevel: "H", scale: 5, margin: 3, dark: "#0b1626", light: "#ffffff" };
  const loginCanvas = document.getElementById("shareQrLogin");
  const siteCanvas = document.getElementById("shareQrSite");
  try {
    if (loginCanvas) {
      window.NetUQR.draw(loginCanvas, loginLink, options);
    }
    if (siteCanvas) {
      window.NetUQR.draw(siteCanvas, siteUrl, options);
    }
  } catch (_error) {
    // 内容超出容量上限时静默忽略，文本分享仍然可用。
  }
}

function showShare({ username, loginPassword, downloadPassword, deletePassword }) {
  const panel = document.getElementById("sharePanel");
  const box = document.getElementById("shareText");
  if (!panel || !box) {
    return;
  }
  const loginLink = `${window.location.origin}/login#${encodeURIComponent(loginPassword)}`;
  const lines = [
    "NetU 文件区",
    `网址：${window.location.origin}`,
    `快捷登录链接：${loginLink}`,
    `用户名：${username}`,
    `登录密码：${loginPassword}`,
  ];
  if (downloadPassword) {
    lines.push(`下载密码：${downloadPassword}`);
  }
  if (deletePassword) {
    lines.push(`删除密码：${deletePassword}`);
  }
  box.value = lines.join("\n");
  renderShareQr(loginLink, window.location.origin);
  activateTab("accounts");
  panel.hidden = false;
  setShareStatus("已生成分享信息，可一键复制。快捷登录链接中的 # 后面是密码，不会发送到服务器。", "success");
  panel.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function copyText(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_error) {
      // Fall back to the legacy copy path below.
    }
  }
  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch (_error) {
    copied = false;
  }
  helper.remove();
  return copied;
}

function getPasswordInputs() {
  return {
    login: document.getElementById("accountLoginPassword"),
    download: document.getElementById("accountDownloadPassword"),
    delete: document.getElementById("accountDeletePassword"),
  };
}

function fillRandomPasswords(targets) {
  const inputs = getPasswordInputs();
  targets.forEach((key) => {
    if (inputs[key]) {
      inputs[key].value = randomPassword();
    }
  });
}

function fillSamePassword(targets) {
  const inputs = getPasswordInputs();
  const value = randomPassword();
  targets.forEach((key) => {
    if (inputs[key]) {
      inputs[key].value = value;
    }
  });
}

function setAdminStatus(message, kind = "info") {
  const node = document.getElementById("adminStatus");
  if (!node) {
    return;
  }
  node.textContent = message || "";
  node.className = `file-meta ${kind}`.trim();
}

function setAccountStatus(message, kind = "info") {
  const node = document.getElementById("accountStatus");
  if (!node) {
    return;
  }
  node.textContent = message || "";
  node.className = `file-meta ${kind}`.trim();
}

function setFileStatus(message) {
  const node = document.getElementById("adminFileStatus");
  if (node) {
    node.textContent = message || "";
  }
}

function setActivityStatus(message, kind = "info") {
  const node = document.getElementById("activityStatus");
  if (!node) {
    return;
  }
  node.textContent = message || "";
  node.className = `file-meta ${kind}`.trim();
}

function setAccountActivityStatus(message, kind = "info") {
  const node = document.getElementById("accountActivityStatus");
  if (!node) {
    return;
  }
  node.textContent = message || "";
  node.className = `file-meta ${kind}`.trim();
}

function activityRowHtml(record) {
  const label = record.action_label || record.action || "操作";
  const filename = record.filename ? ` · ${escapeHtml(record.filename)}` : "";
  const ip = record.ip ? ` · ${escapeHtml(record.ip)}` : "";
  return `
    <article class="file-card">
      <div>
        <div class="file-name">${escapeHtml(label)}${filename}</div>
        <div class="file-meta">${escapeHtml(record.at || "")}${ip}</div>
      </div>
    </article>
  `;
}

function renderActivityRecords(containerId, records) {
  const root = document.getElementById(containerId);
  if (!root) {
    return;
  }
  const list = records || [];
  root.innerHTML = list.length === 0
    ? `<p class="file-meta">暂无记录。</p>`
    : list.map(activityRowHtml).join("");
}

async function loadActivity(username, containerId, statusFn) {
  const query = username ? `?username=${encodeURIComponent(username)}` : "";
  if (statusFn) {
    statusFn("正在加载记录…");
  }
  try {
    const data = await requestJson(`/admin/api/activity${query}`);
    const records = data.records || [];
    renderActivityRecords(containerId, records);
    if (statusFn) {
      statusFn(`共 ${records.length} 条记录。`, "success");
    }
  } catch (error) {
    if (statusFn) {
      statusFn(error.message || "加载失败", "error");
    }
  }
}

function clearActivity({ scope, username }) {
  const body = scope === "all" ? { scope: "all" } : { scope: "account", username };
  return requestJson("/admin/api/activity/clear", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401) {
      window.location.href = "/login?next=/admin";
    }
    throw new Error(payload.message || `请求失败 (${response.status})`);
  }
  return payload;
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

function queueNoteSave(key, field, buildRequest) {
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
      await requestJson(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (status) {
        status.textContent = "已保存";
        status.className = "note-status success";
      }
    } catch (error) {
      if (status) {
        status.textContent = error.message || "保存失败";
        status.className = "note-status error";
      }
    }
  }, 600));
}

async function saveSecurity() {
  const ttl = Number(document.getElementById("cookieTtlDays").value || "7");
  try {
    const data = await requestJson("/admin/api/security", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cookie_ttl_days: ttl }),
    });
    setAdminStatus(data.message || "已保存");
  } catch (error) {
    setAdminStatus(error.message, "error");
  }
}

async function saveSuperadmin() {
  const password = document.getElementById("superadminPassword").value.trim();
  if (!password) {
    setAdminStatus("请输入新的超级管理员密码。", "error");
    return;
  }
  try {
    const data = await requestJson("/admin/api/superadmin", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    document.getElementById("superadminPassword").value = "";
    setAdminStatus(data.message || "已更新，请重新登录。");
    window.setTimeout(() => {
      window.location.href = "/login?next=/admin";
    }, 1200);
  } catch (error) {
    setAdminStatus(error.message, "error");
  }
}

function resetAccountForm() {
  editingUsername = "";
  document.getElementById("accountUsername").value = "";
  document.getElementById("accountUsername").disabled = false;
  fillSamePassword(["login", "download", "delete"]);
  document.getElementById("accountExpireDays").value = defaultExpireDays;
  document.getElementById("accountEnabled").checked = true;
  document.getElementById("accountSubmitBtn").textContent = "创建账户";
  document.getElementById("accountEditHint").textContent =
    "正在创建新账户，登录/下载/删除密码默认相同（4-6 位大写字母或数字），可点「随机」单独生成不同的密码。";
  const activityCard = document.getElementById("accountActivityCard");
  if (activityCard) {
    activityCard.hidden = true;
  }
}

function editAccount(username) {
  const account = accounts.find((item) => item.username === username);
  if (!account) {
    return;
  }
  editingUsername = username;
  document.getElementById("accountUsername").value = username;
  document.getElementById("accountUsername").disabled = true;
  document.getElementById("accountLoginPassword").value = account.login_password || "";
  document.getElementById("accountDownloadPassword").value = account.download_password || "";
  document.getElementById("accountDeletePassword").value = account.delete_password || "";
  document.getElementById("accountExpireDays").value = String(account.expire_days ?? 0);
  document.getElementById("accountEnabled").checked = Boolean(account.enabled);
  document.getElementById("accountSubmitBtn").textContent = "保存修改";
  document.getElementById("accountEditHint").textContent =
    `正在编辑账户「${username}」。可直接查看并修改全部密码（均不可为空）。`;
  const activityCard = document.getElementById("accountActivityCard");
  if (activityCard) {
    document.getElementById("accountActivityTitle").textContent = `「${username}」的行为记录`;
    activityCard.hidden = false;
  }
  loadActivity(username, "accountActivityList", setAccountActivityStatus);
  window.scrollTo({ top: document.getElementById("accountUsername").offsetTop - 80, behavior: "smooth" });
}

async function submitAccount() {
  const loginPassword = document.getElementById("accountLoginPassword").value.trim();
  const downloadPassword = document.getElementById("accountDownloadPassword").value.trim();
  const deletePassword = document.getElementById("accountDeletePassword").value.trim();
  const enabled = document.getElementById("accountEnabled").checked;
  const expireRaw = document.getElementById("accountExpireDays").value.trim();
  const expireDays = expireRaw === "" ? 0 : Math.max(0, Number(expireRaw) || 0);

  if (!loginPassword || !downloadPassword || !deletePassword) {
    setAccountStatus("登录、下载、删除密码都不能为空。", "error");
    return;
  }
  if (loginPassword.length < 4 || downloadPassword.length < 4 || deletePassword.length < 4) {
    setAccountStatus("每个密码至少 4 位。", "error");
    return;
  }

  if (editingUsername) {
    const username = editingUsername;
    try {
      const data = await requestJson(
        `/admin/api/accounts/${encodeURIComponent(username)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            login_password: loginPassword,
            download_password: downloadPassword,
            delete_password: deletePassword,
            enabled,
            expire_days: expireDays,
          }),
        },
      );
      setAccountStatus(data.message || "账户已更新");
      showShare({ username, loginPassword, downloadPassword, deletePassword });
      resetAccountForm();
      await loadAccounts();
    } catch (error) {
      setAccountStatus(error.message, "error");
    }
    return;
  }

  const username = document.getElementById("accountUsername").value.trim();
  try {
    const data = await requestJson("/admin/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username,
        login_password: loginPassword,
        download_password: downloadPassword,
        delete_password: deletePassword,
        enabled,
        expire_days: expireDays,
      }),
    });
    setAccountStatus(data.message || "账户已创建");
    showShare({ username, loginPassword, downloadPassword, deletePassword });
    resetAccountForm();
    await loadAccounts();
  } catch (error) {
    setAccountStatus(error.message, "error");
  }
}

async function deleteAccount(username) {
  if (!window.confirm(`确认删除账户「${username}」？其文件会移动到 down/.trash 保留。`)) {
    return;
  }
  try {
    const data = await requestJson(`/admin/api/accounts/${encodeURIComponent(username)}`, {
      method: "DELETE",
    });
    setAccountStatus(data.message || "账户已删除");
    if (editingUsername === username) {
      resetAccountForm();
    }
    await loadAccounts();
  } catch (error) {
    setAccountStatus(error.message, "error");
  }
}

async function resetAccountPassword(username) {
  const password = randomPassword();
  try {
    const data = await requestJson(`/admin/api/accounts/${encodeURIComponent(username)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        login_password: password,
        download_password: password,
        delete_password: password,
      }),
    });
    setAccountStatus(data.message || "密码已重置");
    showShare({
      username,
      loginPassword: password,
      downloadPassword: password,
      deletePassword: password,
    });
    await loadAccounts();
  } catch (error) {
    setAccountStatus(error.message, "error");
  }
}

function renderAccounts() {
  const root = document.getElementById("accountList");
  if (!root) {
    return;
  }
  if (accounts.length === 0) {
    root.innerHTML = `<p class="file-meta">还没有账户。请在上方创建第一个账户。</p>`;
    return;
  }
  const active = document.activeElement;
  const activeName = active && active.dataset.noteAccount ? active.dataset.noteAccount : null;
  const caret = activeName ? active.selectionStart : 0;
  root.innerHTML = accounts.map((account) => {
    const expiry = account.expired
      ? "已过期 · 自动停用"
      : account.expires_at
        ? `有效期至 ${account.expires_at}`
        : "永不过期";
    return `
    <article class="file-card">
      <div>
        <div class="file-name">${account.username}</div>
        <div class="file-meta">${account.enabled ? "已启用" : "已停用"} · ${expiry} · 创建于 ${account.created_at || "—"}</div>
      </div>
      <div class="note-block">
        <textarea class="note-input" data-note-account="${account.username}" rows="2" placeholder="账户备注（输入即存，仅文字）">${escapeHtml(account.note || "")}</textarea>
        <span class="note-status"></span>
      </div>
      <div class="file-actions">
        <button type="button" data-edit="${account.username}">编辑</button>
        <button type="button" data-reset="${account.username}">随机重置密码</button>
        <button type="button" data-toggle="${account.username}" data-enabled="${account.enabled}">
          ${account.enabled ? "停用" : "启用"}
        </button>
        <button type="button" data-remove="${account.username}">删除账户</button>
      </div>
    </article>
  `;
  }).join("");
  if (activeName) {
    const restored = Array.from(root.querySelectorAll("[data-note-account]"))
      .find((node) => node.dataset.noteAccount === activeName);
    if (restored) {
      restored.focus();
      try {
        restored.selectionStart = restored.selectionEnd = caret;
      } catch (_error) {
        // Some browsers reject caret restore.
      }
    }
  }
}

function renderOwnerOptions() {
  const select = document.getElementById("ownerSelect");
  if (!select) {
    return;
  }
  const previous = select.value;
  const options = [`<option value="root">上传到：公共区（未分配）</option>`].concat(
    accounts.map((account) => `<option value="${account.username}">上传到：${account.username}</option>`),
  );
  select.innerHTML = options.join("");
  const stillValid = [previous, select.value].find(
    (value) => value && [...select.options].some((option) => option.value === value),
  );
  select.value = stillValid || "root";
}

function renderOwnerFilterOptions() {
  const select = document.getElementById("fileOwnerFilter");
  if (!select) {
    return;
  }
  const previous = select.value || "all";
  const options = [`<option value="all">全部归属</option>`, `<option value="root">公共区</option>`].concat(
    accounts.map((account) => `<option value="${account.username}">${account.username}</option>`),
  );
  select.innerHTML = options.join("");
  select.value = [...select.options].some((option) => option.value === previous) ? previous : "all";
}

async function loadAccounts() {
  const data = await requestJson("/admin/api/accounts");
  accounts = data.accounts || [];
  renderAccounts();
  renderOwnerOptions();
  renderOwnerFilterOptions();
  renderStats();
}

function currentOwner() {
  return document.getElementById("ownerSelect")?.value || "root";
}

function ownerLabel(owner) {
  return !owner || owner === "root" ? "公共区" : owner;
}

function formatSize(sizeBytes) {
  const bytes = Number(sizeBytes) || 0;
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let index = 0;
  while (value >= 1024 && index < units.length - 1) {
    value /= 1024;
    index += 1;
  }
  return `${value.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function fileCardHtml(file, muted = false) {
  const actions = muted
    ? `<button type="button" data-owner="${file.owner}" data-restore="${file.name}">恢复</button>
            <button type="button" data-owner="${file.owner}" data-purge="${file.name}">彻底删除</button>`
    : `<button type="button" data-owner="${file.owner}" data-view="${file.name}">预览</button>
            <button type="button" data-owner="${file.owner}" data-download="${file.name}">下载</button>
            <button type="button" data-owner="${file.owner}" data-hide="${file.name}">隐藏</button>
            <button type="button" data-owner="${file.owner}" data-purge="${file.name}">彻底删除</button>`;
  return `
        <article class="file-card${muted ? " muted" : ""}">
          <div>
            <div class="file-name">${file.name}</div>
            <div class="file-meta">归属：${ownerLabel(file.owner)} · ${file.modified_text || ""}${muted ? " · 已隐藏" : ""}</div>
          </div>
          <div class="file-meta">${formatSize(file.size_bytes)}</div>
          <div class="note-block">
            <textarea class="note-input" data-note-owner="${file.owner}" data-note-name="${file.name}" rows="2" placeholder="文件备注（输入即存，仅文字）">${escapeHtml(file.note || "")}</textarea>
            <span class="note-status"></span>
          </div>
          <div class="file-actions">
            ${actions}
          </div>
        </article>
      `;
}

function matchesFileFilters(file) {
  const ownerFilter = document.getElementById("fileOwnerFilter")?.value || "all";
  if (ownerFilter !== "all" && (file.owner || "root") !== ownerFilter) {
    return false;
  }
  const keyword = (document.getElementById("fileSearch")?.value || "").trim().toLowerCase();
  if (!keyword) {
    return true;
  }
  const haystack = `${file.name || ""} ${file.note || ""} ${ownerLabel(file.owner)}`.toLowerCase();
  return haystack.includes(keyword);
}

function sortFiles(files) {
  const mode = document.getElementById("fileSort")?.value || "modified";
  const sorted = files.slice();
  if (mode === "name") {
    sorted.sort((a, b) => String(a.name || "").localeCompare(String(b.name || ""), "zh-Hans-CN"));
  } else if (mode === "size") {
    sorted.sort((a, b) => (b.size_bytes || 0) - (a.size_bytes || 0));
  } else {
    sorted.sort((a, b) => (b.modified || 0) - (a.modified || 0));
  }
  return sorted;
}

function renderStats() {
  const set = (id, text) => {
    const node = document.getElementById(id);
    if (node) {
      node.textContent = text;
    }
  };
  const usable = accounts.filter((account) => account.enabled && !account.expired).length;
  set("statAccounts", String(accounts.length));
  set("statAccountsSub", `${usable} 个可用 / ${accounts.length - usable} 个停用或过期`);
  set("statFiles", String(allFiles.length));
  set("statTrash", String(allHidden.length));
  const totalBytes = allFiles
    .concat(allHidden)
    .reduce((sum, file) => sum + (Number(file.size_bytes) || 0), 0);
  set("statSize", formatSize(totalBytes));
}

function renderFiles() {
  const root = document.getElementById("adminFileList");
  const hiddenRoot = document.getElementById("adminHiddenList");
  const active = document.activeElement;
  const activeKey = active && active.dataset.noteName
    ? `${active.dataset.noteOwner || ""}\u0000${active.dataset.noteName}`
    : null;
  const caret = activeKey ? active.selectionStart : 0;

  const matched = sortFiles(allFiles.filter(matchesFileFilters));
  const shown = matched.slice(0, visibleFileCount);
  if (root) {
    root.innerHTML = matched.length === 0
      ? `<p class="file-meta">${allFiles.length === 0 ? "暂无文件。" : "没有匹配的文件。"}</p>`
      : shown.map((file) => fileCardHtml(file)).join("");
  }

  const hiddenMatched = sortFiles(allHidden.filter(matchesFileFilters));
  if (hiddenRoot) {
    hiddenRoot.innerHTML = hiddenMatched.length === 0
      ? `<p class="file-meta">回收站为空。</p>`
      : hiddenMatched.map((file) => fileCardHtml(file, true)).join("");
  }

  const more = document.getElementById("fileLoadMore");
  if (more) {
    more.hidden = matched.length <= shown.length;
    more.textContent = `加载更多（已显示 ${shown.length} / ${matched.length}）`;
  }

  const filtered = matched.length === allFiles.length ? "" : `，筛选后 ${matched.length} 个`;
  setFileStatus(`全部账户共 ${allFiles.length} 个文件${filtered}，回收站 ${allHidden.length} 个。`);

  if (activeKey) {
    const restored = Array.from(
      document.querySelectorAll("#adminFileList [data-note-name], #adminHiddenList [data-note-name]"),
    ).find(
      (node) => `${node.dataset.noteOwner || ""}\u0000${node.dataset.noteName}` === activeKey,
    );
    if (restored) {
      restored.focus();
      try {
        restored.selectionStart = restored.selectionEnd = caret;
      } catch (_error) {
        // Some browsers reject caret restore.
      }
    }
  }
}

async function loadFiles(force = false) {
  const url = !force && currentEtag
    ? `/admin/api/files?owner=all&since=${encodeURIComponent(currentEtag)}`
    : `/admin/api/files?owner=all`;
  const data = await requestJson(url);
  if (data.changed === false) {
    return;
  }
  currentEtag = data.etag;
  allFiles = data.files || [];
  allHidden = data.hidden || [];
  visibleFileCount = FILE_PAGE_SIZE;
  renderFiles();
  renderStats();
}

function isIosDevice() {
  const ua = navigator.userAgent || "";
  return /iP(hone|ad|od)/.test(ua) || (ua.includes("Macintosh") && navigator.maxTouchPoints > 1);
}

function setUploadProgress(percent) {
  const wrap = document.getElementById("adminUploadProgress");
  const bar = document.getElementById("adminUploadProgressBar");
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
        window.location.href = "/login?next=/admin";
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

function triggerDownload(url, filename) {
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

async function adminUpload(fileList) {
  const files = Array.from(fileList || []);
  if (files.length === 0) {
    return;
  }
  const owner = currentOwner();
  const label = ownerLabel(owner);
  const total = files.length;
  setUploadBusy(true);
  let done = 0;
  try {
    for (let index = 0; index < total; index += 1) {
      const file = files[index];
      const prefix = total > 1 ? `(${index + 1}/${total}) ` : "";
      setFileStatus(`${prefix}正在上传 ${file.name} 到「${label}」...`);
      setUploadProgress(0);
      await uploadWithProgress(
        `/admin/api/upload?owner=${encodeURIComponent(owner)}`,
        file,
        (percent) => {
          setFileStatus(`${prefix}正在上传 ${file.name} 到「${label}」：${percent}%`);
          setUploadProgress(percent);
        },
      );
      done += 1;
    }
    setFileStatus(`上传完成，共 ${done} 个文件。`);
    await loadFiles(true);
  } catch (error) {
    setFileStatus(error.message || "上传失败");
  } finally {
    setUploadProgress(null);
    setUploadBusy(false);
  }
}

async function adminDelete(filename, mode, owner) {
  if (mode === "purge" && !window.confirm(`彻底删除「${filename}」？此操作不可恢复。`)) {
    return;
  }
  const data = await requestJson("/admin/api/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ owner, filename, mode }),
  });
  setFileStatus(data.message || "已完成");
  await loadFiles(true);
}

async function adminRestore(filename, owner) {
  const data = await requestJson("/admin/api/restore", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ owner, filename }),
  });
  setFileStatus(data.message || "已恢复");
  await loadFiles(true);
}

document.addEventListener("DOMContentLoaded", () => {
  const expireField = document.getElementById("accountExpireDays");
  if (expireField && expireField.value) {
    defaultExpireDays = expireField.value;
  }
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
  restoreTab();
  document.getElementById("saveSecurityBtn")?.addEventListener("click", () => {
    saveSecurity().catch(() => {});
  });
  document.getElementById("saveSuperadminBtn")?.addEventListener("click", () => {
    saveSuperadmin().catch(() => {});
  });
  document.getElementById("activityRefreshBtn")?.addEventListener("click", () => {
    loadActivity(SUPERADMIN_USER, "activityList", setActivityStatus);
  });
  document.getElementById("activityClearAllBtn")?.addEventListener("click", () => {
    if (!window.confirm("确认清空全部行为记录（含所有账户与超级管理员）？此操作不可恢复。")) {
      return;
    }
    clearActivity({ scope: "all" })
      .then(() => loadActivity(SUPERADMIN_USER, "activityList", setActivityStatus))
      .catch((error) => setActivityStatus(error.message, "error"));
  });
  document.getElementById("accountActivityRefreshBtn")?.addEventListener("click", () => {
    if (editingUsername) {
      loadActivity(editingUsername, "accountActivityList", setAccountActivityStatus);
    }
  });
  document.getElementById("accountActivityClearBtn")?.addEventListener("click", () => {
    if (!editingUsername) {
      return;
    }
    if (!window.confirm(`确认清空账户「${editingUsername}」的行为记录？此操作不可恢复。`)) {
      return;
    }
    clearActivity({ scope: "account", username: editingUsername })
      .then(() => loadActivity(editingUsername, "accountActivityList", setAccountActivityStatus))
      .catch((error) => setAccountActivityStatus(error.message, "error"));
  });
  document.getElementById("accountSubmitBtn")?.addEventListener("click", () => {
    submitAccount().catch((error) => setAccountStatus(error.message, "error"));
  });
  document.getElementById("accountResetBtn")?.addEventListener("click", () => resetAccountForm());
  document.getElementById("randomLoginBtn")?.addEventListener("click", () => fillRandomPasswords(["login"]));
  document.getElementById("randomDownloadBtn")?.addEventListener("click", () => fillRandomPasswords(["download"]));
  document.getElementById("randomDeleteBtn")?.addEventListener("click", () => fillRandomPasswords(["delete"]));
  document.getElementById("accountRandomAllBtn")?.addEventListener("click", () =>
    fillRandomPasswords(["login", "download", "delete"]),
  );
  document.getElementById("shareCopyBtn")?.addEventListener("click", async () => {
    const text = document.getElementById("shareText")?.value || "";
    const ok = await copyText(text);
    setShareStatus(ok ? "已复制全部信息。" : "复制失败，请手动选择复制。", ok ? "success" : "error");
  });
  document.getElementById("shareCopyPasswordBtn")?.addEventListener("click", async () => {
    const text = document.getElementById("shareText")?.value || "";
    const matched = text.match(/登录密码：(.*)/);
    const ok = await copyText(matched ? matched[1].trim() : "");
    setShareStatus(ok ? "已复制登录密码。" : "复制失败，请手动选择复制。", ok ? "success" : "error");
  });
  document.getElementById("shareNativeBtn")?.addEventListener("click", async () => {
    const text = document.getElementById("shareText")?.value || "";
    if (navigator.share) {
      try {
        await navigator.share({ title: "NetU 文件区登录信息", text });
        setShareStatus("已分享。", "success");
        return;
      } catch (_error) {
        // Sharing was dismissed or unsupported; fall back to copying.
      }
    }
    const ok = await copyText(text);
    setShareStatus(
      ok ? "当前环境不支持系统分享，已复制到剪贴板。" : "分享失败，请手动复制。",
      ok ? "success" : "error",
    );
  });
  document.getElementById("adminRefreshBtn")?.addEventListener("click", () => {
    loadAccounts()
      .then(() => loadFiles(true))
      .catch((error) => setFileStatus(error.message));
  });
  document.getElementById("adminUploadBtn")?.addEventListener("click", () => {
    document.getElementById("adminFileInput")?.click();
  });
  document.getElementById("adminCameraBtn")?.addEventListener("click", () => {
    document.getElementById("adminCameraInput")?.click();
  });
  const handleAdminPickedFiles = (event) => {
    const chosen = Array.from(event.target.files || []);
    event.target.value = "";
    adminUpload(chosen);
  };
  document.getElementById("adminFileInput")?.addEventListener("change", handleAdminPickedFiles);
  document.getElementById("adminCameraInput")?.addEventListener("change", handleAdminPickedFiles);
  document.getElementById("ownerSelect")?.addEventListener("change", () => {
    setFileStatus(`上传目标已设为「${ownerLabel(currentOwner())}」。`);
  });
  const resetFileView = () => {
    visibleFileCount = FILE_PAGE_SIZE;
    renderFiles();
  };
  document.getElementById("fileSearch")?.addEventListener("input", resetFileView);
  document.getElementById("fileOwnerFilter")?.addEventListener("change", resetFileView);
  document.getElementById("fileSort")?.addEventListener("change", () => renderFiles());
  document.getElementById("fileLoadMore")?.addEventListener("click", () => {
    visibleFileCount += FILE_PAGE_SIZE;
    renderFiles();
  });
  document.getElementById("accountList")?.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-edit], button[data-reset], button[data-toggle], button[data-remove]");
    if (!button) {
      return;
    }
    if (button.dataset.edit) {
      editAccount(button.dataset.edit);
      return;
    }
    if (button.dataset.reset) {
      resetAccountPassword(button.dataset.reset).catch((error) =>
        setAccountStatus(error.message, "error"),
      );
      return;
    }
    if (button.dataset.remove) {
      deleteAccount(button.dataset.remove).catch((error) => setAccountStatus(error.message, "error"));
      return;
    }
    if (button.dataset.toggle) {
      const enabled = button.dataset.enabled !== "true";
      requestJson(`/admin/api/accounts/${encodeURIComponent(button.dataset.toggle)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      })
        .then((data) => {
          setAccountStatus(data.message || "已更新");
          return loadAccounts();
        })
        .catch((error) => setAccountStatus(error.message, "error"));
    }
  });
  const fileHandlers = (event) => {
    const button = event.target.closest("button[data-view], button[data-download], button[data-hide], button[data-purge], button[data-restore]");
    if (!button) {
      return;
    }
    const owner = button.dataset.owner || currentOwner();
    const name = button.dataset.view || button.dataset.download || button.dataset.hide
      || button.dataset.purge || button.dataset.restore;
    if (button.dataset.view) {
      window.open(
        `/admin/file/view?owner=${encodeURIComponent(owner)}&filename=${encodeURIComponent(name)}`,
        "_blank",
        "noopener",
      );
      return;
    }
    if (button.dataset.download) {
      const url = `/admin/file/download?owner=${encodeURIComponent(owner)}&filename=${encodeURIComponent(name)}`;
      triggerDownload(url, name);
      setFileStatus(`已开始下载：${name}`);
      return;
    }
    if (button.dataset.hide) {
      adminDelete(name, "hide", owner).catch((error) => setFileStatus(error.message));
      return;
    }
    if (button.dataset.purge) {
      adminDelete(name, "purge", owner).catch((error) => setFileStatus(error.message));
      return;
    }
    if (button.dataset.restore) {
      adminRestore(name, owner).catch((error) => setFileStatus(error.message));
    }
  };
  document.getElementById("adminFileList")?.addEventListener("click", fileHandlers);
  document.getElementById("adminHiddenList")?.addEventListener("click", fileHandlers);

  const noteInputHandler = (event) => {
    const field = event.target;
    if (!field.classList?.contains("note-input")) {
      return;
    }
    if (field.dataset.noteAccount) {
      const username = field.dataset.noteAccount;
      queueNoteSave(`account:${username}`, field, (value) => ({
        url: `/admin/api/accounts/${encodeURIComponent(username)}/note`,
        body: { note: value },
      }));
      return;
    }
    const owner = field.dataset.noteOwner || "root";
    const name = field.dataset.noteName || "";
    queueNoteSave(`file:${owner}:${name}`, field, (value) => ({
      url: `/admin/api/note?owner=${encodeURIComponent(owner)}`,
      body: { owner, filename: name, note: value },
    }));
  };
  document.getElementById("accountList")?.addEventListener("input", noteInputHandler);
  document.getElementById("adminFileList")?.addEventListener("input", noteInputHandler);
  document.getElementById("adminHiddenList")?.addEventListener("input", noteInputHandler);

  resetAccountForm();
  loadAccounts()
    .then(() => loadFiles(true))
    .catch((error) => setAdminStatus(error.message, "error"));
});
