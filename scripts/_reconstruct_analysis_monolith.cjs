const fs = require("fs");
const path = require("path");

const srcPath = path.join("C:", "Users", "user", "Desktop", "web_portal", "static", "js", "analysis.js");
const dstPath = path.join(__dirname, "..", "static", "js", "analysis.js");

const THIN_HELPERS = `
function syncGraphContext() {
  window.__AN_GRAPH_CONTEXT = {
    selectedUnit: String(SELECTED_UNIT || ""),
    selectedPair: SELECTED_PAIR
      ? {
        frequency: String(SELECTED_PAIR.frequency || ""),
        group: String(SELECTED_PAIR.group || ""),
      }
      : null,
    mode: String(MODE || "pair"),
    days: Number(DAYS || 1),
    period_mode: PERIOD_MODE,
    period_start_day: PERIOD_START_DATE,
    period_end_day: PERIOD_END_DATE || PERIOD_START_DATE,
  };
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
`.trim();

const ESCAPE_HTML = `
function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
`.trim();

function findStart(lines, pred, start = 0) {
  for (let i = start; i < lines.length; i++) {
    if (pred(lines[i])) return i;
  }
  throw new Error(`marker not found from line ${start + 1}`);
}

function stripBlanksAi(lines) {
  const iAi = findStart(lines, (l) => l.startsWith("let AI_LAST_REPORT_ID"));
  lines.splice(iAi, 2);

  const iBlanks = findStart(lines, (l) => l.startsWith("// ---- Поиск по перехватам"));
  const iDom = findStart(lines, (l) => l.startsWith('document.addEventListener("DOMContentLoaded"'));
  lines.splice(iBlanks, iDom - iBlanks, ESCAPE_HTML, "");

  const iNet = findStart(lines, (l) => l.includes("network summary container init"));
  const iBlankDom = findStart(lines, (l) => l.includes("Поиск по перехватам (бланки)"));
  lines.splice(iNet, iBlankDom - iNet, "  // network: analysis-network.js", "");

  const iAiDom = findStart(lines, (l) => l.trim() === "initAiDates();");
  const iForm = findStart(lines, (l) => l.includes('formExportBtn = $("an-export-form-btn")'));
  lines.splice(iAiDom, iForm - iAiDom, "  // blanks-search / AI: analysis-blanks.js / analysis-ai.js", "");
}

function stripGraphV1(lines) {
  const iRange = findStart(lines, (l) => l.startsWith("function readGraphRangeInputs"));
  const iState = findStart(lines, (l) => l.startsWith("let STATE = null"));
  lines.splice(iRange, iState - iRange);

  const iGraphTimer = findStart(lines, (l) => l.startsWith("let GRAPH_TIMER = null"));
  const iMeta = findStart(lines, (l) => l.startsWith("const AN_MOBILE_CONTAINER_META"));
  lines.splice(
    iGraphTimer,
    iMeta - iGraphTimer,
    "let GRAPH_ACTIVE = false;",
    "let GRAPH_REFRESH_TIMER = null;",
    "",
    THIN_HELPERS,
    ""
  );

  const iV1 = findStart(lines, (l) => l.startsWith("// --- Realtime network graph ---"));
  const iKeys = findStart(lines, (l) => l.startsWith("function keysIsoLocalMin"));
  lines.splice(iV1, iKeys - iV1);

  const iControls = findStart(lines, (l) => l.trim() === "// graph controls");
  let iEnd = lines.length - 1;
  while (iEnd > iControls && !lines[iEnd].trim()) iEnd--;
  if (lines[iEnd].trim() !== "});") throw new Error(`expected }); got ${lines[iEnd]}`);
  lines.splice(iControls, iEnd - iControls, "  // graph V1 controls removed — AnalysisGraphV2 binds rg-* UI");
}

function stripKeys(lines) {
  const iKeysVars = findStart(lines, (l) => l.startsWith("let KEYS_DATA = []"));
  lines.splice(iKeysVars, 5);

  const iKeysDom = findStart(lines, (l) => l.includes("keys check container init"));
  const iGraphComment = findStart(lines, (l) => l.includes("graph V1 controls removed"));
  lines.splice(iKeysDom, iGraphComment - iKeysDom, "  // keys: analysis-keys.js", "");
}

function stripNetwork(lines) {
  const iNet = findStart(lines, (l) => l.startsWith("function _ruSessionsWord"));
  const iExport = findStart(lines, (l) => l.startsWith("async function exportCallsignForm"));
  lines.splice(iNet, iExport - iNet);

  const iExportNew = findStart(lines, (l) => l.startsWith("async function exportCallsignForm"));
  const iAfterExport = findStart(
    lines,
    (l) => l.startsWith("async function exportNetworkSummary"),
    iExportNew + 1
  );
  const iEscape = findStart(lines, (l) => l.startsWith("function escapeHtml"), iExportNew + 1);
  lines.splice(iAfterExport, iEscape - iAfterExport);
}

let lines = fs.readFileSync(srcPath, "utf-8").split("\n");
stripBlanksAi(lines);
stripGraphV1(lines);
stripKeys(lines);
stripNetwork(lines);

const text = lines.join("\n");
const must = [
  "function toIsoLocalMin",
  "let LAST_STATS_SEQ",
  "function callsignMatchesScope",
  "async function exportCallsignForm",
  "function escapeHtml",
  "async function loadState",
  'document.addEventListener("DOMContentLoaded"',
];
for (const m of must) {
  if (!text.includes(m)) throw new Error(`missing ${m}`);
}

fs.writeFileSync(dstPath, lines.join("\n") + (lines[lines.length - 1] === "" ? "" : "\n"), "utf-8");
console.log(`Wrote ${dstPath}: ${lines.length} lines`);
console.log(`  line 257: ${lines[256]?.slice(0, 50)}`);
console.log(`  export: line ${lines.findIndex((l) => l.startsWith("async function exportCallsignForm")) + 1}`);
