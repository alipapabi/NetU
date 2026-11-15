/* NetU — 微信内置浏览器引导：提示用户改用系统浏览器打开
 * 微信「扫一扫」默认在微信内置浏览器中打开链接，且不会自动跳转外部浏览器。
 * 这里在检测到微信环境时展示引导浮层，指引用户通过右上角菜单「在浏览器打开」。
 * 非微信环境不做任何处理；附加 ?wxguide=1 可强制预览该浮层。
 */
(function () {
  var DISMISS_KEY = "netu-wx-guide-dismissed";
  var inWeChat = /MicroMessenger/i.test(navigator.userAgent || "");
  var forced = /(?:[?&#])wxguide=1(?:&|#|$)/.test(window.location.href);

  if (!inWeChat && !forced) {
    return;
  }

  function dismissed() {
    try {
      return window.sessionStorage.getItem(DISMISS_KEY) === "1";
    } catch (_error) {
      return false;
    }
  }

  function remember() {
    try {
      window.sessionStorage.setItem(DISMISS_KEY, "1");
    } catch (_error) {
      // 隐私模式下 sessionStorage 可能不可用，忽略即可。
    }
  }

  function build() {
    var wrap = document.createElement("div");
    wrap.className = "wx-guide";
    wrap.setAttribute("role", "dialog");
    wrap.setAttribute("aria-modal", "true");
    wrap.setAttribute("aria-label", "请在浏览器中打开");
    wrap.innerHTML =
      '<div class="wx-guide-arrow" aria-hidden="true">' +
      '<svg viewBox="0 0 64 64" width="58" height="58">' +
      '<path d="M4 60C8 30 30 10 56 6" fill="none" stroke="currentColor" stroke-width="4" ' +
      'stroke-linecap="round" stroke-dasharray="9 7"/>' +
      '<path d="M38 4h20v20" fill="none" stroke="currentColor" stroke-width="4" ' +
      'stroke-linecap="round" stroke-linejoin="round"/>' +
      "</svg>" +
      "</div>" +
      '<div class="wx-guide-card">' +
      '<span class="brand-mark wx-guide-mark" aria-hidden="true">DC</span>' +
      "<h2>请在浏览器中打开</h2>" +
      "<p>当前处于微信内置浏览器，下载、预览与登录状态可能无法正常使用。</p>" +
      '<ol class="wx-guide-steps">' +
      "<li><span>1</span>点击右上角的 <strong>···</strong> 按钮</li>" +
      "<li><span>2</span>选择「<strong>在浏览器打开</strong>」</li>" +
      "</ol>" +
      '<button type="button" class="wx-guide-close">我知道了</button>' +
      "</div>";
    return wrap;
  }

  function mount() {
    if (dismissed()) {
      return;
    }
    var wrap = build();
    document.body.appendChild(wrap);
    wrap.querySelector(".wx-guide-close").addEventListener("click", function () {
      remember();
      wrap.remove();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mount);
  } else {
    mount();
  }
})();
