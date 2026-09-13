from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from web_portal.lib.asr.model import operator_line_with_id
from web_portal.lib.db import add_asr_train_sample, add_asr_feedback

_LINE_WITH_ID_RE = re.compile(
    r"^-(.+?)\s*\((\d+)\)\s*\.?\s*$",
    re.UNICODE,
)


def parse_operator_blank_lines(text: str) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for raw in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        ln = str(raw or "").strip()
        if not ln or ln[0].isdigit():
            continue
        m = _LINE_WITH_ID_RE.match(ln)
        if not m:
            continue
        body = str(m.group(1) or "").strip().rstrip(".")
        cid = str(m.group(2) or "").strip()
        if not body or not cid:
            continue
        out.append(
            {
                "correspondent_id": cid,
                "line": operator_line_with_id(body, cid),
                "text": body,
            }
        )
    return out


def _prediction_line_for_id(prediction_text: str, correspondent_id: str) -> str:
    cid = str(correspondent_id or "").strip()
    if not cid:
        return ""
    for raw in str(prediction_text or "").replace("\r\n", "\n").split("\n"):
        ln = str(raw or "").strip()
        if f"({cid})" in ln:
            return ln
    return ""


def learn_from_operator_blank(
    conn,
    *,
    position_name: str,
    operator_text: str,
    prediction_text: str = "",
    folder_path: str,
    segments: list[dict[str, Any]],
    reviewer: str = "",
) -> dict[str, Any]:
    pos = str(position_name or "").strip()
    if not pos:
        raise ValueError("position_name обязателен")
    lines = parse_operator_blank_lines(operator_text)
    if not lines:
        return {"ok": True, "learned": 0, "skipped": 0, "reason": "no_parsed_lines"}

    seg_by_cid: dict[str, dict[str, Any]] = {}
    for seg in segments or []:
        cid = str(seg.get("correspondent_id") or "").strip()
        if cid and cid not in seg_by_cid:
            seg_by_cid[cid] = seg

    learned = 0
    skipped = 0
    base = Path(str(folder_path or "").strip())

    for row in lines:
        cid = row["correspondent_id"]
        seg = seg_by_cid.get(cid)
        if not seg:
            skipped += 1
            continue
        file_key = str(seg.get("file_key") or "").strip()
        file_rel = str(seg.get("file_rel") or "").strip()
        if not file_key or not file_rel:
            skipped += 1
            continue
        has_key = bool(seg.get("has_key"))
        has_message = bool(seg.get("has_message"))
        if has_key and not has_message:
            skipped += 1
            continue

        target = str(row.get("line") or "").strip()
        pred_line = _prediction_line_for_id(prediction_text, cid)
        audio_path = str((base / file_rel).resolve()) if base and file_rel else ""

        add_asr_feedback(
            conn,
            position_name=pos,
            file_key=file_key,
            prediction_text=pred_line or str(prediction_text or ""),
            corrected_text=target,
            feedback_label="operator_blank",
            reviewer=str(reviewer or ""),
            status="validated",
        )
        add_asr_train_sample(
            conn,
            position_name=pos,
            file_key=file_key,
            audio_path=audio_path,
            start_ts=0.0,
            end_ts=float(seg.get("duration_sec") or 0.0),
            frequency=str(seg.get("frequency") or ""),
            group_code=str(seg.get("group_code") or ""),
            correspondent_id=cid,
            source_text=pred_line,
            target_text=target,
            alignment_score=1.0,
            status="validated",
            meta_json=json.dumps(
                {"source": "operator_blank_send", "correspondent_id": cid},
                ensure_ascii=False,
            ),
        )
        learned += 1

    return {"ok": True, "learned": learned, "skipped": skipped}
