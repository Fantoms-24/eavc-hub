from pathlib import Path

src_path = Path(r"C:/Users/user/Desktop/web_portal/static/js/analysis.js")
dst_path = Path(__file__).resolve().parents[1] / "static" / "js" / "analysis-network.js"
src = src_path.read_text(encoding="utf-8")
lines = src.splitlines(keepends=True)

# Correct 0-based slices from web_portal/static/js/analysis.js
block1 = lines[1541:1998]  # _ruSessionsWord .. buildNetworkSummary
block2 = lines[2025:2158]  # exportNetworkSummary .. mergeIntensity2hTo6h (skip exportCallsignForm)
block3 = lines[2159:2653]  # networkOrderStorageKey .. initNetworkOrderUI
init_block = lines[5537:5591]  # network summary container init

header = """(function () {
  "use strict";

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }

"""

footer = """
  function boot() {
    if (!window.AnalysisRuntime?.isModule("network")) return;
    window.__ANALYSIS_ACTIVE_BUNDLE__ = "network";
"""

boot_body = []
for line in init_block:
    s = line.rstrip("\n")
    if not s.strip():
        boot_body.append("")
        continue
    if s.strip() == "// network summary container init":
        continue
    if s.startswith("  "):
        s = s[2:]
    boot_body.append("    " + s)

footer += "\n".join(boot_body)
footer += """
  }

  window.AnalysisRuntime?.onReady(boot);
})();
"""

body = "".join(block1 + block2 + block3)
# Strip leading "function " declarations to module scope (already at top level inside IIFE)
out = header + body + footer
dst_path.write_text(out, encoding="utf-8")
print(f"Wrote {dst_path}: {len(out.splitlines())} lines")
