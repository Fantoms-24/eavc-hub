/**
 * EAVC Mobile Nav — swipe-back, history sync, unified back affordance.
 * Только телефоны (≤767.98px), только body.eavc-app.
 */
(function () {
  "use strict";

  var MQ = window.matchMedia("(max-width: 767.98px)");
  var SWIPE_MIN = 56;
  var SWIPE_MAX = 120;
  var EDGE = 28;
  var HISTORY_KEY = "eavc.mobile";

  var touch = { active: false, x0: 0, y0: 0, dx: 0, fromEdge: false };
  var suppressHistory = false;

  function isMobile() {
    return !!MQ.matches && document.body.classList.contains("eavc-app");
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

  function getPage() {
    if (document.body.classList.contains("eavc-page-audio")) return "audio";
    if (document.body.classList.contains("eavc-page-intercepts")) return "intercepts";
    if (document.body.classList.contains("eavc-page-map")) return "map";
    if (document.body.classList.contains("eavc-page-sessions")) return "sessions";
    if (document.body.classList.contains("eavc-page-aviation")) return "aviation";
    return null;
  }

  function getAviationSection() {
    var root = document.querySelector(".md3-aviation");
    return root ? root.getAttribute("data-av-section") || "freq" : "freq";
  }

  function getInterceptsPanel() {
    var root = document.querySelector(".md3-intercepts");
    return root ? root.getAttribute("data-ix-panel") || "groups" : "groups";
  }

  function getMapTab() {
    var wb = document.getElementById("map-workbench");
    return wb ? wb.getAttribute("data-mobile-tab") || "map" : "map";
  }

  function getSessionsSection() {
    var root = document.querySelector(".md3-sessions");
    return root ? root.getAttribute("data-sn-section") || "folder" : "folder";
  }

  function rootStateForPage(page) {
    page = page || getPage();
    return {
      page: page,
      railOpen: false,
      audio: "groups",
      intercepts: "groups",
      map: "map",
      sessions: "folder",
      aviation: "freq",
    };
  }

  function getNavState() {
    return {
      page: getPage(),
      railOpen: document.body.classList.contains("eavc-rail-open"),
      audio: getInterceptsPanel(),
      intercepts: getInterceptsPanel(),
      map: getMapTab(),
      sessions: getSessionsSection(),
      aviation: getAviationSection(),
    };
  }

  function isRootState(state) {
    if (!state) return true;
    if (state.railOpen) return false;
    if (state.page === "audio") return state.audio === "groups";
    if (state.page === "intercepts") return state.intercepts === "groups";
    if (state.page === "map") return state.map === "map";
    if (state.page === "sessions") return state.sessions === "folder";
    if (state.page === "aviation") return state.aviation === "freq";
    return true;
  }

  function canGoBack(state) {
    state = state || getNavState();
    if (state.railOpen) return true;
    return !isRootState(state);
  }

  function navigateIntercepts(panel) {
    if (typeof window.setInterceptsMobilePanel === "function") {
      window.setInterceptsMobilePanel(panel);
    }
  }

  function navigateMap(tab) {
    var dock = document.getElementById("mp-mobile-dock");
    var btn = dock && dock.querySelector('[data-panel="' + tab + '"]');
    if (btn) btn.click();
  }

  function navigateSessions(section) {
    if (typeof window.setSessionsMobileSection === "function") {
      window.setSessionsMobileSection(section);
    }
  }

  function navigateAviation(section) {
    if (typeof window.setAviationMobileSection === "function") {
      window.setAviationMobileSection(section);
    } else {
      var dock = document.getElementById("av-mobile-dock");
      var btn = dock && dock.querySelector('[data-av-section="' + section + '"]');
      if (btn) btn.click();
    }
  }

  function applyState(state) {
    if (!state) state = rootStateForPage();
    if (state.railOpen) setRailOpen(true);
    else setRailOpen(false);
    if (state.page === "audio" && state.audio) {
      navigateIntercepts(state.audio);
    } else if (state.page === "intercepts" && state.intercepts) {
      navigateIntercepts(state.intercepts);
    } else if (state.page === "map" && state.map) {
      navigateMap(state.map);
    } else if (state.page === "sessions" && state.sessions) {
      navigateSessions(state.sessions);
    } else if (state.page === "aviation" && state.aviation) {
      navigateAviation(state.aviation);
    }
  }

  function goBack() {
    var state = getNavState();
    if (state.railOpen) {
      setRailOpen(false);
      syncUi();
      return true;
    }
    if (!canGoBack(state)) return false;
    try {
      history.back();
    } catch (_e) {
      applyState(rootStateForPage(state.page));
      syncUi();
    }
    return true;
  }

  function shouldPushHistory(prev, next) {
    if (prev.page !== next.page) return navDepth(next) > navDepth(prev);
    if (next.page === "audio") {
      if (prev.audio === "groups" && next.audio !== "groups") return true;
      if (prev.audio === "blank" && next.audio === "audio") return true;
      return false;
    }
    if (next.page === "intercepts") {
      if (prev.intercepts === "groups" && next.intercepts !== "groups") return true;
      if (prev.intercepts === "blank" && next.intercepts === "input") return true;
      return false;
    }
    if (next.page === "map") {
      return prev.map === "map" && next.map !== "map";
    }
    if (next.page === "sessions") {
      return prev.sessions === "folder" && next.sessions !== "folder";
    }
    if (next.page === "aviation") {
      return prev.aviation === "freq" && next.aviation !== "freq";
    }
    return false;
  }

  function pushHistory(state) {
    if (!isMobile() || suppressHistory) return;
    try {
      history.pushState({ eavc: HISTORY_KEY, state: state }, "");
    } catch (_e) { /* ignore */ }
  }

  function replaceHistory(state) {
    if (!isMobile() || suppressHistory) return;
    try {
      history.replaceState({ eavc: HISTORY_KEY, state: state }, "");
    } catch (_e) { /* ignore */ }
  }

  function syncUi() {
    if (!isMobile()) {
      document.documentElement.classList.remove("eavc-mobile-shell");
      document.body.classList.remove("eavc-mobile-active", "eavc-mobile-can-back", "eavc-mobile-shell");
      return;
    }
    document.documentElement.classList.add("eavc-mobile-shell");
    document.body.classList.add("eavc-mobile-shell");
    document.body.classList.add("eavc-mobile-active");
    document.body.classList.toggle("eavc-mobile-can-back", canGoBack());
    var backBtn = document.getElementById("eavc-mobile-back");
    if (backBtn) {
      if (canGoBack()) backBtn.removeAttribute("hidden");
      else backBtn.setAttribute("hidden", "");
    }
  }

  function onPopState(ev) {
    if (!isMobile() || suppressHistory) return;
    var st = ev.state && ev.state.eavc === HISTORY_KEY ? ev.state.state : null;
    suppressHistory = true;
    applyState(st || rootStateForPage());
    window.setTimeout(function () {
      suppressHistory = false;
      syncUi();
    }, 50);
  }

  function onTouchStart(ev) {
    if (!isMobile() || ev.touches.length !== 1) return;
    var t = ev.touches[0];
    touch.active = true;
    touch.x0 = t.clientX;
    touch.y0 = t.clientY;
    touch.dx = 0;
    touch.fromEdge = t.clientX <= EDGE;
    if (!canGoBack() && !touch.fromEdge) {
      touch.active = false;
      return;
    }
    document.body.classList.add("eavc-swipe-active");
  }

  function onTouchMove(ev) {
    if (!touch.active || !ev.touches.length) return;
    var t = ev.touches[0];
    var dx = t.clientX - touch.x0;
    var dy = t.clientY - touch.y0;
    if (Math.abs(dy) > Math.abs(dx) && Math.abs(dx) < 20) return;
    if (dx < 0) return;
    if (!canGoBack() && !touch.fromEdge) return;
    touch.dx = dx;
    document.body.classList.toggle("eavc-swipe-dragging", dx > 8);
    document.body.style.setProperty("--eavc-swipe-x", Math.min(dx, SWIPE_MAX) + "px");
    if (dx > 12) ev.preventDefault();
  }

  function onTouchEnd() {
    if (!touch.active) return;
    var dx = touch.dx;
    touch.active = false;
    document.body.classList.remove("eavc-swipe-active", "eavc-swipe-dragging");
    document.body.style.removeProperty("--eavc-swipe-x");
    if (dx >= SWIPE_MIN && canGoBack()) {
      goBack();
    }
  }

  function observeNavChanges() {
    var last = JSON.stringify(getNavState());
    var obs = new MutationObserver(function () {
      var next = getNavState();
      var nextStr = JSON.stringify(next);
      if (nextStr === last) return;
      var prev = JSON.parse(last);
      last = nextStr;
      syncUi();
      if (suppressHistory) return;
      if (shouldPushHistory(prev, next)) {
        pushHistory(next);
      } else {
        replaceHistory(next);
      }
    });
    obs.observe(document.body, { attributes: true, attributeFilter: ["class"] });
    var ixRoot = document.querySelector(".md3-intercepts");
    if (ixRoot) obs.observe(ixRoot, { attributes: true, attributeFilter: ["data-ix-panel", "class"] });
    var mapWb = document.getElementById("map-workbench");
    if (mapWb) obs.observe(mapWb, { attributes: true, attributeFilter: ["data-mobile-tab", "class"] });
    var snRoot = document.querySelector(".md3-sessions");
    if (snRoot) obs.observe(snRoot, { attributes: true, attributeFilter: ["data-sn-section", "class"] });
    var avRoot = document.querySelector(".md3-aviation");
    if (avRoot) obs.observe(avRoot, { attributes: true, attributeFilter: ["data-av-section", "class"] });
  }

  function navDepth(state) {
    if (state.page === "audio") {
      if (state.audio === "groups") return 0;
      if (state.audio === "audio") return 2;
      return 1;
    }
    if (state.page === "intercepts") {
      if (state.intercepts === "groups") return 0;
      if (state.intercepts === "input") return 2;
      return 1;
    }
    if (state.page === "map") return state.map === "map" ? 0 : 1;
    if (state.page === "sessions") return state.sessions === "folder" ? 0 : 1;
    if (state.page === "aviation") return state.aviation === "freq" ? 0 : 1;
    return 0;
  }

  function bindBackButton() {
    var btn = document.getElementById("eavc-mobile-back");
    if (!btn) return;
    btn.addEventListener("click", function (ev) {
      ev.preventDefault();
      goBack();
    });
  }

  function boot() {
    if (!document.body.classList.contains("eavc-app")) return;
    bindBackButton();
    observeNavChanges();
    syncUi();
    replaceHistory(getNavState());

    window.addEventListener("popstate", onPopState);
    document.addEventListener("touchstart", onTouchStart, { passive: true });
    document.addEventListener("touchmove", onTouchMove, { passive: false });
    document.addEventListener("touchend", onTouchEnd, { passive: true });
    document.addEventListener("touchcancel", onTouchEnd, { passive: true });

    if (MQ.addEventListener) MQ.addEventListener("change", syncUi);
    else if (MQ.addListener) MQ.addListener(syncUi);
  }

  window.EavcMobileNav = {
    goBack: goBack,
    canGoBack: canGoBack,
    syncUi: syncUi,
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
