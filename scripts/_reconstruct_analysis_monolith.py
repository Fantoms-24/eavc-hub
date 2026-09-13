"""Reconstruct pre-callsign-extraction analysis.js (~1640 lines) from web_portal source."""
from __future__ import annotations

from pathlib import Path

SRC = Path(r"C:\Users\user\Desktop\web_portal\static\js\analysis.js")
DST = Path(__file__).resolve().parents[1] / "static" / "js" / "analysis.js"

THIN_HELPERS = """
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
"""

ESCAPE_HTML = """
function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s;
  return div.innerHTML;
}
"""


def find_start(lines: list[str], pred, start: int = 0) -> int:
    for i in range(start, len(lines)):
        if pred(lines[i]):
            return i
    raise SystemExit(f"marker not found from line {start + 1}")


def strip_blanks_ai(lines: list[str]) -> None:
    i_ai = find_start(lines, lambda l: l.startswith("let AI_LAST_REPORT_ID"))
    del lines[i_ai : i_ai + 2]

    i_blanks = find_start(lines, lambda l: l.startswith("// ---- Поиск по перехватам"))
    i_dom = find_start(lines, lambda l: l.startswith('document.addEventListener("DOMContentLoaded"'))
    helper_lines = [ln + "\n" for ln in ESCAPE_HTML.strip().split("\n")] + ["\n"]
    lines[i_blanks:i_dom] = helper_lines

    i_net = find_start(lines, lambda l: "network summary container init" in l)
    i_blank_dom = find_start(lines, lambda l: "Поиск по перехватам (бланки)" in l)
    lines[i_net:i_blank_dom] = ["  // network: analysis-network.js\n\n"]

    i_ai_dom = find_start(lines, lambda l: l.strip() == "initAiDates();")
    i_form = find_start(lines, lambda l: 'formExportBtn = $("an-export-form-btn")' in l)
    lines[i_ai_dom:i_form] = [
        "  // blanks-search / AI: analysis-blanks.js / analysis-ai.js\n\n",
    ]


def strip_graph_v1(lines: list[str]) -> None:
    i_range = find_start(lines, lambda l: l.startswith("function readGraphRangeInputs"))
    i_state = find_start(lines, lambda l: l.startswith("let STATE = null"))
    del lines[i_range:i_state]

    i_graph_timer = find_start(lines, lambda l: l.startswith("let GRAPH_TIMER = null"))
    i_meta = find_start(lines, lambda l: l.startswith("const AN_MOBILE_CONTAINER_META"))
    helper_lines = [ln + "\n" for ln in THIN_HELPERS.strip().split("\n")]
    lines[i_graph_timer:i_meta] = [
        "let GRAPH_ACTIVE = false;\n",
        "let GRAPH_REFRESH_TIMER = null;\n",
        "\n",
        *helper_lines,
        "\n",
    ]

    i_v1 = find_start(lines, lambda l: l.startswith("// --- Realtime network graph ---"))
    i_keys = find_start(lines, lambda l: l.startswith("function keysIsoLocalMin"))
    del lines[i_v1:i_keys]

    i_controls = find_start(lines, lambda l: l.strip() == "// graph controls")
    i_end = len(lines) - 1
    while i_end > i_controls and not lines[i_end].strip():
        i_end -= 1
    if lines[i_end].strip() != "});":
        raise SystemExit(f"expected closing }}); got {lines[i_end]!r}")
    lines[i_controls:i_end] = [
        "  // graph V1 controls removed — AnalysisGraphV2 binds rg-* UI\n",
    ]


def strip_keys(lines: list[str]) -> None:
    i_keys_vars = find_start(lines, lambda l: l.startswith("let KEYS_DATA = []"))
    del lines[i_keys_vars : i_keys_vars + 5]

    i_keys_dom = find_start(lines, lambda l: "keys check container init" in l)
    i_graph_comment = find_start(lines, lambda l: "graph V1 controls removed" in l)
    lines[i_keys_dom:i_graph_comment] = ["  // keys: analysis-keys.js\n\n"]


def strip_network(lines: list[str]) -> None:
    i_net = find_start(lines, lambda l: l.startswith("function _ruSessionsWord"))
    i_export = find_start(lines, lambda l: l.startswith("async function exportCallsignForm"))
    del lines[i_net:i_export]

    i_after_export = find_start(lines, lambda l: l.startswith("async function exportNetworkSummary"))
    i_escape = find_start(lines, lambda l: l.startswith("function escapeHtml"), i_export)
    del lines[i_after_export:i_escape]


def verify(lines: list[str]) -> None:
    text = "".join(lines)
    for needle in [
        "function toIsoLocalMin",
        "let LAST_STATS_SEQ",
        "function callsignMatchesScope",
        "async function exportCallsignForm",
        "function escapeHtml",
        "async function loadState",
        'document.addEventListener("DOMContentLoaded"',
    ]:
        if needle not in text:
            raise SystemExit(f"verification failed: missing {needle}")

    for needle in [
        "function _ruSessionsWord",
        "async function buildNetworkSummary",
        "function keysIsoLocalMin",
        "async function runBlanksSearch",
        "function _graphColorForUnit",
        "let KEYS_DATA",
        "let AI_LAST_REPORT_ID",
    ]:
        if needle in text:
            raise SystemExit(f"verification failed: still contains {needle}")

    print(f"  line 1: {lines[0].strip()[:40]}")
    print(f"  line 44: {lines[43].strip()[:40]}")
    print(f"  line 45: {lines[44].strip()[:40]}")
    print(f"  line 257: {lines[256].strip()[:40]}")
    print(f"  export line: {next(i+1 for i,l in enumerate(lines) if l.startswith('async function exportCallsignForm'))}")
    print(f"  escape line: {next(i+1 for i,l in enumerate(lines) if l.startswith('function escapeHtml'))}")
    print(f"  dom line: {next(i+1 for i,l in enumerate(lines) if l.startswith('document.addEventListener'))}")


def main() -> None:
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    strip_blanks_ai(lines)
    strip_graph_v1(lines)
    strip_keys(lines)
    strip_network(lines)
    verify(lines)
    DST.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote {DST} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
