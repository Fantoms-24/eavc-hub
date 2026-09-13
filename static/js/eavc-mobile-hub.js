/**
 * EAVC Mobile Hub — section switcher, map drawer helpers.
 * Phone shell only (≤767.98px).
 */
(function () {
  "use strict";

  var MQ = window.matchMedia("(max-width: 767.98px)");

  function isMobileShell() {
    return !!MQ.matches && document.body.classList.contains("eavc-mobile-shell");
  }

  function initSectionNav() {
    var links = document.querySelectorAll(".eavc-topbar__section-link[href]");
    links.forEach(function (link) {
      link.addEventListener("click", function () {
        try {
          sessionStorage.setItem(
            "eavc:nav",
            JSON.stringify({
              path: link.getAttribute("href"),
              label: link.textContent.trim(),
              icon: link.querySelector(".bi") ? "bi " + link.querySelector(".bi").className.split(" ").pop() : "bi bi-arrow-repeat",
              progress: 18,
              ts: Date.now(),
            })
          );
        } catch (_e) {}
      });
    });
  }

  function syncShellClass() {
    if (!document.body.classList.contains("eavc-app")) return;
    var on = !!MQ.matches;
    document.documentElement.classList.toggle("eavc-mobile-shell", on);
    document.body.classList.toggle("eavc-mobile-shell", on);
  }

  if (MQ.addEventListener) MQ.addEventListener("change", syncShellClass);
  else if (MQ.addListener) MQ.addListener(syncShellClass);

  function boot() {
    syncShellClass();
    if (isMobileShell()) initSectionNav();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
