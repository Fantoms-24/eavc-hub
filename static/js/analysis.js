let ACTIVE_CONTAINER = "callsigns";
const ACTIVE_CONTAINER_STORAGE_KEY = "wp_analysis_active_container";
let GRAPH_ACTIVE = false;
let GRAPH_REFRESH_TIMER = null;


function syncGraphContext() {
  if (typeof window.__analysisCallsignsSyncGraph === "function") {
    window.__analysisCallsignsSyncGraph();
  }
}

function startGraphPolling() {
  const graphV2 = window.AnalysisGraphV2;
  if (graphV2 && typeof graphV2.isEnabled === "function" && graphV2.isEnabled()) {
    return;
  }
}

function stopGraphPolling() {
  if (GRAPH_REFRESH_TIMER) {
    clearTimeout(GRAPH_REFRESH_TIMER);
    GRAPH_REFRESH_TIMER = null;
  }
}

function requestGraphRefresh() {
  syncGraphContext();
  if (!GRAPH_ACTIVE) return;
  if (document.hidden) return;
  if (GRAPH_REFRESH_TIMER) clearTimeout(GRAPH_REFRESH_TIMER);
  const graphV2 = window.AnalysisGraphV2;
  if (graphV2 && typeof graphV2.refresh === "function") {
    GRAPH_REFRESH_TIMER = setTimeout(() => {
      GRAPH_REFRESH_TIMER = null;
      graphV2.refresh();
    }, 180);
  }
}

const AN_MOBILE_CONTAINER_META = {
  callsigns: {
    title: "Анализ позывных",
    sub: "Частота и группа → активность корреспондентов за период",
  },
  network: {
    title: "Общий анализ радиосети",
    sub: "Кластеризация сеансов и сравнение с прошлым интервалом",
  },
  graph: {
    title: "Граф радиосети",
    sub: "Связи, таймлайн и сравнение периодов",
  },
  keys: {
    title: "Проверка ключей",
    sub: "Валидация и статус ключевых материалов",
  },
  crypto: {
    title: "Крипто",
    sub: "Анализ криптографической активности",
  },
  "blanks-search": {
    title: "Поиск по перехватам",
    sub: "Поиск в бланках перехватов",
  },
  ai: {
    title: "AI-анализ",
    sub: "Запросы к локальной модели по данным",
  },
  "arm-task": {
    title: "Задание поста",
    sub: "Задачи и частоты для поста",
  },
};

function setAnalysisMobileCallsignsSub(sub) {
  const root = document.querySelector(".md3-analysis-group");
  if (!root || !root.classList.contains("an-mobile-ui")) return;
  const allowed = ["tree", "main"];
  if (!allowed.includes(sub)) sub = "tree";
  root.dataset.anCsSub = sub;
  const body = $("an-cs-body");
  if (body) {
    body.classList.remove("an2--panel-main");
    if (sub === "main") body.classList.add("an2--panel-main");
  }
  const dock = document.getElementById("an-mobile-subdock-callsigns");
  if (dock) {
    const btns = Array.from(dock.querySelectorAll("[data-an-cs-sub]"));
    btns.forEach(function (btn) {
      const on = btn.getAttribute("data-an-cs-sub") === sub;
      btn.classList.toggle("active", on);
      btn.setAttribute("aria-selected", on ? "true" : "false");
    });
    const idx = Math.max(0, btns.findIndex(function (b) { return b.getAttribute("data-an-cs-sub") === sub; }));
    dock.style.setProperty("--an-cs-sub-index", String(idx));
  }
}

function syncAnalysisMobileChrome() {
  const root = document.querySelector(".md3-analysis-group");
  if (!root || !root.classList.contains("an-mobile-ui")) return;
  const meta = AN_MOBILE_CONTAINER_META[ACTIVE_CONTAINER] || AN_MOBILE_CONTAINER_META.callsigns;
  root.dataset.anContainer = ACTIVE_CONTAINER;
  root.classList.toggle("an-mobile-ui--callsigns", ACTIVE_CONTAINER === "callsigns");

  const hero = document.getElementById("an-mobile-hero");
  const heroTitle = document.getElementById("an-mobile-hero-title");
  const heroSub = document.getElementById("an-mobile-hero-sub");
  const headTitle = document.getElementById("an-mobile-panel-head-title");
  const headSub = document.getElementById("an-mobile-panel-head-sub");
  const subdock = document.getElementById("an-mobile-subdock-callsigns");

  if (hero) hero.hidden = false;
  if (heroTitle) heroTitle.textContent = meta.title;
  if (heroSub) heroSub.textContent = meta.sub;
  if (headTitle) headTitle.textContent = "Модуль";
  if (headSub) headSub.textContent = meta.title;
  if (subdock) subdock.hidden = ACTIVE_CONTAINER !== "callsigns";

  if (ACTIVE_CONTAINER === "callsigns") {
    const sub = root.dataset.anCsSub || "tree";
    setAnalysisMobileCallsignsSub(sub);
  }
}

function applyAnalysisMobileUi() {
  const root = document.querySelector(".md3-analysis-group");
  if (!root) return;
  const mq = window.matchMedia("(max-width: 767.98px)");
  const on = !!mq.matches;
  root.classList.toggle("an-mobile-ui", on);
  document.body.classList.toggle("an-mobile-analysis", on);

  const hero = document.getElementById("an-mobile-hero");
  const head = document.getElementById("an-mobile-panel-head");
  if (hero) hero.hidden = !on;
  if (head) head.hidden = !on;

  if (on) {
    if (!root.dataset.anCsSub) root.dataset.anCsSub = "tree";
    syncAnalysisMobileChrome();
  } else {
    root.classList.remove("an-mobile-ui--callsigns");
  }
}

function setActiveContainer(name) {
  ACTIVE_CONTAINER = String(name || "").trim() || "callsigns";
  try {
    localStorage.setItem(ACTIVE_CONTAINER_STORAGE_KEY, ACTIVE_CONTAINER);
  } catch (_e) {
    // ignore
  }
  const root = document.querySelector(".md3-analysis-group.an-workbench-ui");
  if (root) root.setAttribute("data-an-container", ACTIVE_CONTAINER);
  syncAnalysisMobileChrome();
  // buttons
  const wrap = $("analysis-containers");
  if (wrap) {
    wrap.querySelectorAll("[data-container]").forEach((btn) => {
      const c = btn.getAttribute("data-container");
      const isActive = c === ACTIVE_CONTAINER;
      btn.classList.toggle("active", isActive);
      const check = btn.querySelector(".analysis-container-check");
      if (check) check.classList.toggle("d-none", !isActive);
    });
  }
  // sidebar parts (positions always visible; callsigns nav only for callsigns)
  const csNav = document.getElementById("analysis-callsigns-nav");
  if (csNav) csNav.style.display = ACTIVE_CONTAINER === "callsigns" ? "" : "none";
  const positionsNav = document.getElementById("analysis-positions-nav");
  if (positionsNav) {
    positionsNav.style.display = "";
  }
  // bodies
  document.querySelectorAll("[data-container-body]").forEach((el) => {
    const c = el.getAttribute("data-container-body");
    el.style.display = c === ACTIVE_CONTAINER ? "" : "none";
  });
  const graphV2 = window.AnalysisGraphV2;
  if (ACTIVE_CONTAINER === "graph") {
    GRAPH_ACTIVE = true;
    syncGraphContext();
    if (graphV2 && typeof graphV2.activate === "function") {
      graphV2.activate();
    } else {
      startGraphPolling();
    }
  } else {
    GRAPH_ACTIVE = false;
    if (graphV2 && typeof graphV2.deactivate === "function") {
      graphV2.deactivate();
    }
    stopGraphPolling();
  }
  if (ACTIVE_CONTAINER === "arm-task" && window.ArmTaskView && typeof window.ArmTaskView.activate === "function") {
    window.ArmTaskView.activate();
  }
}

document.addEventListener("DOMContentLoaded", async () => {
  const root = document.querySelector(".md3-analysis-group.an-workbench-ui");
  const pageModule = root && root.getAttribute("data-an-container");
  if (
    pageModule === "callsigns" ||
    pageModule === "network" ||
    pageModule === "graph" ||
    pageModule === "keys" ||
    pageModule === "crypto" ||
    pageModule === "blanks-search" ||
    pageModule === "ai" ||
    pageModule === "arm-task"
  ) {
    ACTIVE_CONTAINER = pageModule;
  } else {
    try {
      const saved = localStorage.getItem(ACTIVE_CONTAINER_STORAGE_KEY);
      if (
        saved === "callsigns" ||
        saved === "network" ||
        saved === "graph" ||
        saved === "keys" ||
        saved === "crypto" ||
        saved === "blanks-search" ||
        saved === "ai" ||
        saved === "arm-task"
      ) {
        ACTIVE_CONTAINER = saved;
      }
    } catch (_e) {
      // ignore
    }
  }
  setActiveContainer(ACTIVE_CONTAINER);

  applyAnalysisMobileUi();
  window.matchMedia("(max-width: 767.98px)").addEventListener("change", applyAnalysisMobileUi);

  // callsigns: analysis-callsigns.js

});



