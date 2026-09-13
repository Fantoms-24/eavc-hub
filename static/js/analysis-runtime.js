(function () {
  "use strict";

  const valid = new Set(["callsigns", "network", "graph", "keys", "crypto", "blanks-search", "ai", "arm-task"]);

  window.AnalysisRuntime = window.AnalysisRuntime || {
    module() {
      const root = document.querySelector(".md3-analysis-group.an-workbench-ui");
      const mod = root && root.getAttribute("data-an-container");
      return valid.has(mod) ? mod : "callsigns";
    },
    onReady(fn) {
      if (typeof fn !== "function") return;
      if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", fn, { once: true });
      } else {
        fn();
      }
    },
    isModule(name) {
      return this.module() === String(name || "");
    },
  };
})();
