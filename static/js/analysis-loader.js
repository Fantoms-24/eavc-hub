(function () {
  "use strict";

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      if (!src) {
        resolve();
        return;
      }
      const existing = document.querySelector(`script[src="${src}"]`);
      if (existing) {
        if (existing.dataset.loaded === "1") resolve();
        else existing.addEventListener("load", resolve, { once: true });
        return;
      }
      const s = document.createElement("script");
      s.src = src;
      s.defer = true;
      s.onload = () => {
        s.dataset.loaded = "1";
        resolve();
      };
      s.onerror = () => reject(new Error(`Не удалось загрузить ${src}`));
      document.head.appendChild(s);
    });
  }

  async function boot() {
    const cfg = window.__ANALYSIS_BUNDLE__ || {};
    const scripts = Array.isArray(cfg.scripts) ? cfg.scripts : [];
    for (const src of scripts) {
      await loadScript(src);
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
