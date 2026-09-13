from __future__ import annotations

import re
from typing import Any


def operator_ru_formatter(text: str) -> str:
    s = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    s = s.replace("Ґ", "Г").replace("ґ", "г")
    if s and s[0].isalpha():
        s = s[0].upper() + s[1:]
    if s and s[-1] not in ".!?":
        s += "."
    return f"-{s}"


def operator_line_with_id(text: str, correspondent_id: str) -> str:
    line = operator_ru_formatter(text)
    if not line:
        return ""
    cid = str(correspondent_id or "").strip()
    if not cid:
        return line
    body = line[1:] if line.startswith("-") else line
    body = body.rstrip(".")
    return f"-{body} ({cid})."


def format_operator_time_header(recorded_at: str) -> str:
    s = str(recorded_at or "").strip()
    if not s:
        return ""
    m = re.search(r"(\d{1,2})[:.](\d{2})", s)
    if m:
        hh = int(m.group(1))
        mm = int(m.group(2))
        if 0 <= hh <= 23 and 0 <= mm <= 59:
            return f"{hh:02d}.{mm:02d}"
    m2 = re.search(r"\b(\d{2}):(\d{2})(?::\d{2})?\b", s)
    if m2:
        return f"{m2.group(1)}.{m2.group(2)}"
    return ""


def build_operator_blank(
    *,
    recorded_at: str,
    segment_lines: list[str],
) -> str:
    lines: list[str] = []
    header = format_operator_time_header(recorded_at)
    if header:
        lines.append(header)
    for ln in segment_lines or []:
        t = str(ln or "").strip()
        if t:
            lines.append(t)
    return "\n".join(lines).strip()


def estimate_confidence(raw_result: dict[str, Any] | None) -> float:
    if not raw_result:
        return 0.0
    try:
        chunks = raw_result.get("chunks") or raw_result.get("segments") or []
        if not chunks:
            return 0.5
        scores = []
        for c in chunks:
            v = c.get("confidence")
            if v is None:
                v = c.get("avg_logprob")
                if v is not None:
                    v = max(0.0, min(1.0, 1.0 + float(v) / 5.0))
            if v is not None:
                scores.append(float(v))
        if not scores:
            return 0.5
        return max(0.0, min(1.0, float(sum(scores) / len(scores))))
    except Exception:
        return 0.5
