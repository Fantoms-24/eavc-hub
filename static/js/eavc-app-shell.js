/**
 * EAVC App Shell — лёгкий скрипт без тяжёлых наблюдателей DOM.
 */
(function () {
  function cleanupStuckOverlays() {
    document.querySelectorAll(".modal-backdrop").forEach(function (el) {
      el.remove();
    });
    document.body.classList.remove("modal-open");
    document.body.style.removeProperty("overflow");
    document.body.style.removeProperty("padding-right");

    var backdrop = document.getElementById("eavc-rail-backdrop");
    if (backdrop) {
      backdrop.hidden = true;
      backdrop.setAttribute("aria-hidden", "true");
    }
    document.body.classList.remove("eavc-rail-open");
  }

  function setRailOpen(open) {
    var btn = document.getElementById("eavc-rail-toggle");
    var backdrop = document.getElementById("eavc-rail-backdrop");
    document.body.classList.toggle("eavc-rail-open", !!open);
    if (btn) btn.setAttribute("aria-expanded", open ? "true" : "false");
    if (backdrop) {
      backdrop.hidden = !open;
      backdrop.setAttribute("aria-hidden", open ? "false" : "true");
    }
  }

  function initRailToggle() {
    var btn = document.getElementById("eavc-rail-toggle");
    var backdrop = document.getElementById("eavc-rail-backdrop");
    if (!btn && !backdrop) return;

    setRailOpen(false);

    if (btn) {
      btn.addEventListener("click", function (ev) {
        ev.preventDefault();
        ev.stopPropagation();
        setRailOpen(!document.body.classList.contains("eavc-rail-open"));
      });
    }

    if (backdrop) {
      backdrop.addEventListener("click", function () {
        setRailOpen(false);
      });
    }

    document.addEventListener("click", function (ev) {
      if (!document.body.classList.contains("eavc-rail-open")) return;
      if (ev.target.closest(".eavc-rail") || ev.target.closest("#eavc-rail-toggle")) return;
      setRailOpen(false);
    });

    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape" && document.body.classList.contains("eavc-rail-open")) {
        setRailOpen(false);
      }
    });
  }

  function syncBadges() {
    ["chat-badge", "targeting-badge"].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      var n = parseInt(String(el.textContent || "0"), 10) || 0;
      if (el.style && el.style.display === "none") {
        el.hidden = true;
        return;
      }
      el.hidden = n <= 0;
    });
  }

  function initTopbarElevate() {
    var topbar = document.querySelector(".eavc-topbar");
    var scrollRoot = document.querySelector("main.eavc-content") || window;
    if (!topbar) return;
    var onScroll = function () {
      var y =
        scrollRoot === window
          ? window.scrollY || document.documentElement.scrollTop || 0
          : scrollRoot.scrollTop || 0;
      topbar.classList.toggle("eavc-topbar--elevated", y > 6);
    };
    onScroll();
    if (scrollRoot === window) {
      window.addEventListener("scroll", onScroll, { passive: true });
    } else {
      scrollRoot.addEventListener("scroll", onScroll, { passive: true });
    }
  }

  function prefersReducedMotion() {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function revealContent() {
    var main = document.querySelector("main.eavc-content");
    if (!main || prefersReducedMotion()) {
      document.body.classList.remove("eavc-nav-revealing", "eavc-nav-revealed");
      return;
    }

    document.body.classList.add("eavc-nav-revealing");
    document.body.classList.remove("eavc-nav-revealed");
    main.classList.add("eavc-content--revealing");
    main.classList.remove("eavc-content--revealed");

    requestAnimationFrame(function () {
      requestAnimationFrame(function () {
        document.body.classList.add("eavc-nav-revealed");
        main.classList.add("eavc-content--revealed");
      });
    });

    var cleaned = false;
    var cleanup = function () {
      if (cleaned) return;
      cleaned = true;
      document.body.classList.remove("eavc-nav-revealing", "eavc-nav-revealed");
      main.classList.remove("eavc-content--revealing", "eavc-content--revealed");
      main.removeEventListener("transitionend", onEnd);
    };
    var onEnd = function (ev) {
      if (ev.target !== main || ev.propertyName !== "opacity") return;
      cleanup();
    };
    main.addEventListener("transitionend", onEnd);
    window.setTimeout(cleanup, 760);
  }

  function isShellNavLink(anchor) {
    if (!anchor || anchor.tagName !== "A") return false;
    if (anchor.target && anchor.target !== "_self") return false;
    if (anchor.hasAttribute("download")) return false;
    var href = anchor.getAttribute("href");
    if (!href || href.charAt(0) === "#" || href.indexOf("javascript:") === 0) return false;

    try {
      var url = new URL(anchor.href, window.location.href);
      if (url.origin !== window.location.origin) return false;
      return !(
        url.pathname === window.location.pathname &&
        url.search === window.location.search &&
        url.hash === window.location.hash
      );
    } catch (_err) {
      return false;
    }
  }

  var NAV_STORAGE_KEY = "eavc:nav";

  function getNavMeta(anchor) {
    var labelEl = anchor.querySelector(".eavc-rail__label");
    var iconEl = anchor.querySelector(".eavc-rail__icon i");
    return {
      label: (labelEl && labelEl.textContent.trim()) || anchor.getAttribute("title") || "Раздел",
      icon: iconEl ? iconEl.className : "bi bi-arrow-repeat",
    };
  }

  function readPendingNav() {
    try {
      var raw = sessionStorage.getItem(NAV_STORAGE_KEY);
      if (!raw) return null;
      var nav = JSON.parse(raw);
      if (!nav || nav.path !== window.location.pathname) return null;
      if (Date.now() - (nav.ts || 0) > 30000) return null;
      return nav;
    } catch (_err) {
      return null;
    }
  }

  function initPageTransitions() {
    if (!document.body.classList.contains("eavc-app")) return;

    var loader = document.getElementById("eavc-nav-loader");
    var loaderLabel = document.getElementById("eavc-nav-loader-label");
    var loaderIcon = document.getElementById("eavc-nav-loader-icon");
    var loaderBar = document.getElementById("eavc-nav-loader-bar");
    var loaderPctEl = document.getElementById("eavc-nav-loader-pct");
    var progressRaf = 0;
    var progressValue = 0;
    var progressActive = false;

    function setProgress(value) {
      progressValue = Math.max(0, Math.min(100, value));
      var pct = progressValue + "%";
      if (loader) {
        loader.style.setProperty("--eavc-loader-pct", pct);
        loader.style.setProperty("--eavc-loader-frac", String(progressValue / 100));
      }
      if (loaderPctEl) loaderPctEl.textContent = Math.round(progressValue) + "%";
    }

    function persistNavProgress() {
      try {
        var raw = sessionStorage.getItem(NAV_STORAGE_KEY);
        if (!raw) return;
        var nav = JSON.parse(raw);
        if (!nav) return;
        nav.progress = Math.round(progressValue * 10) / 10;
        sessionStorage.setItem(NAV_STORAGE_KEY, JSON.stringify(nav));
      } catch (_err) {}
    }

    function stopProgressLoop() {
      progressActive = false;
      if (progressRaf) {
        cancelAnimationFrame(progressRaf);
        progressRaf = 0;
      }
    }

    function isProgressContextActive() {
      return (
        document.body.classList.contains("is-navigating") ||
        document.body.classList.contains("eavc-nav-loading") ||
        document.documentElement.classList.contains("eavc-nav-pending")
      );
    }

    function startProgressCrawl(from, cap) {
      stopProgressLoop();
      setProgress(from);
      progressActive = true;
      var last = performance.now();
      var lastPersist = 0;
      cap = Math.max(from + 0.5, Math.min(96, cap));

      function tick(now) {
        if (!progressActive || !isProgressContextActive()) return;

        var dt = Math.min(32, now - last);
        last = now;
        var remaining = cap - progressValue;

        if (remaining > 0.04) {
          var step = remaining * (0.00014 * dt) + 0.028 * (dt / 16.67);
          setProgress(progressValue + step);
        }

        if (now - lastPersist > 140) {
          lastPersist = now;
          persistNavProgress();
        }

        if (progressValue < cap - 0.08) {
          progressRaf = requestAnimationFrame(tick);
        }
      }

      progressRaf = requestAnimationFrame(tick);
    }

    function animateProgressTo(target, duration, done) {
      stopProgressLoop();
      progressActive = true;
      var from = progressValue;
      var start = performance.now();
      target = Math.max(from, Math.min(100, target));
      duration = duration || 680;

      function tick(now) {
        if (!progressActive) return;
        var t = Math.min(1, (now - start) / duration);
        var eased = 1 - Math.pow(1 - t, 3);
        setProgress(from + (target - from) * eased);
        if (t < 1) {
          progressRaf = requestAnimationFrame(tick);
          return;
        }
        progressActive = false;
        persistNavProgress();
        if (typeof done === "function") done();
      }

      progressRaf = requestAnimationFrame(tick);
    }

    function showLoader(meta, startAt, cap) {
      if (!loader || prefersReducedMotion()) return;

      if (loaderLabel && meta && meta.label) loaderLabel.textContent = meta.label;
      if (loaderIcon && meta && meta.icon) loaderIcon.className = meta.icon + " eavc-nav-loader__icon";

      loader.classList.remove("is-complete");
      loader.removeAttribute("hidden");
      loader.setAttribute("aria-hidden", "false");
      document.body.classList.add("eavc-nav-loading");
      document.body.setAttribute("aria-busy", "true");

      var from =
        typeof startAt === "number"
          ? startAt
          : meta && typeof meta.progress === "number"
            ? meta.progress
            : 0;
      from = Math.max(12, from);
      startProgressCrawl(from, typeof cap === "number" ? cap : 88);
    }

    function hideLoader(done) {
      document.body.classList.remove("is-navigating");

      if (!loader || prefersReducedMotion()) {
        stopProgressLoop();
        document.body.classList.remove("eavc-nav-loading");
        document.body.removeAttribute("aria-busy");
        document.documentElement.classList.remove("eavc-nav-pending");
        sessionStorage.removeItem(NAV_STORAGE_KEY);
        if (typeof done === "function") done();
        return;
      }

      animateProgressTo(100, 760, function () {
        window.setTimeout(function () {
          loader.classList.add("is-complete");
          loader.setAttribute("aria-hidden", "true");
        }, 160);

        window.setTimeout(function () {
          stopProgressLoop();
          loader.setAttribute("hidden", "");
          loader.classList.remove("is-complete");
          setProgress(0);

          document.body.classList.remove("eavc-nav-loading");
          document.body.removeAttribute("aria-busy");
          document.documentElement.classList.remove("eavc-nav-pending");
          sessionStorage.removeItem(NAV_STORAGE_KEY);

          document.body.classList.add("eavc-nav-revealing");
          var main = document.querySelector("main.eavc-content");
          if (main) main.classList.add("eavc-content--revealing");

          requestAnimationFrame(function () {
            requestAnimationFrame(function () {
              if (typeof done === "function") done();
            });
          });
        }, 760);
      });
    }

    function clearNavigating() {
      stopProgressLoop();
      document.body.classList.remove("is-navigating");
    }

    function startNavigating(meta) {
      try {
        sessionStorage.setItem(
          NAV_STORAGE_KEY,
          JSON.stringify({
            path: meta.path,
            label: meta.label,
            icon: meta.icon,
            progress: progressValue,
            ts: Date.now(),
          })
        );
      } catch (_err) {}

      document.body.classList.add("is-navigating");
      showLoader(meta, 12, 82);
      setRailOpen(false);
    }

    window.addEventListener("pagehide", function () {
      if (document.body.classList.contains("is-navigating")) {
        persistNavProgress();
      }
    });

    document.addEventListener(
      "click",
      function (ev) {
        if (ev.defaultPrevented) return;
        if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return;

        var anchor = ev.target.closest(".eavc-rail__link, .eavc-rail__brand");
        if (!isShellNavLink(anchor)) return;

        var meta = getNavMeta(anchor);
        try {
          meta.path = new URL(anchor.href, window.location.href).pathname;
        } catch (_err2) {
          return;
        }
        startNavigating(meta);
      },
      true
    );

    window.addEventListener("pageshow", function (ev) {
      if (ev.persisted) {
        hideLoader(function () {
          revealContent();
        });
        return;
      }
      clearNavigating();
    });

    function finishPendingNav(pendingNav) {
      var resumeFrom =
        typeof pendingNav.progress === "number" ? Math.max(12, pendingNav.progress) : 42;
      showLoader(pendingNav, resumeFrom, 92);
      var shownAt = performance.now();
      var minVisibleMs = 1100;

      function complete() {
        hideLoader(function () {
          revealContent();
        });
      }

      function tryComplete() {
        var elapsed = performance.now() - shownAt;
        var pageReady = document.readyState === "complete";
        if (pageReady && elapsed >= minVisibleMs) {
          complete();
          return;
        }
        if (elapsed >= 9000) {
          complete();
          return;
        }
        window.setTimeout(tryComplete, 40);
      }

      if (document.readyState === "complete") {
        tryComplete();
      } else {
        window.addEventListener("load", tryComplete, { once: true });
        tryComplete();
      }
    }

    var pending = readPendingNav();
    if (pending) {
      finishPendingNav(pending);
      return;
    }
  }

  function boot() {
    cleanupStuckOverlays();
    initRailToggle();
    initTopbarElevate();
    initPageTransitions();
    syncBadges();
  }

  cleanupStuckOverlays();

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }

  window.addEventListener("pageshow", cleanupStuckOverlays);
})();
