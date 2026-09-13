from __future__ import annotations

from pathlib import Path
from datetime import datetime
from collections import defaultdict
from typing import Any
import json
import re

from web_portal.lib.intercept_audio import scan_intercept_audio_files
from web_portal.lib.db import add_asr_train_sample


def _parse_time_header(line: str) -> int | None:
    s = str(line or "").strip()
    m = re.match(r"^(\d{1,2})[:.](\d{2})$", s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if hh < 0 or hh > 23 or mm < 0 or mm > 59:
        return None
    return hh * 60 + mm


def _split_blocks(content: str) -> list[tuple[int | None, list[str]]]:
    lines = str(content or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[tuple[int | None, list[str]]] = []
    cur_key: int | None = None
    cur_lines: list[str] = []
    for ln in lines:
        t = _parse_time_header(ln.strip())
        if t is not None:
            if cur_lines:
                blocks.append((cur_key, cur_lines))
            cur_key = t
            cur_lines = [f"{t // 60:02d}.{t % 60:02d}"]
        else:
            if cur_lines:
                cur_lines.append(ln)
            elif str(ln or "").strip():
                cur_lines = [ln]
                cur_key = None
    if cur_lines:
        blocks.append((cur_key, cur_lines))
    return blocks


def _group_norm(v: str) -> str:
    return str(v or "").strip().lstrip("Gg").strip()


def _freq_norm(v: str) -> str:
    return str(v or "").strip().replace(",", ".")


def _date_key(ts: str) -> str:
    try:
        d = datetime.fromisoformat(str(ts or "").replace("Z", ""))
        return d.strftime("%Y-%m-%d")
    except Exception:
        return str(ts or "")[:10]


def _minute_of_day(ts: str) -> int:
    try:
        d = datetime.fromisoformat(str(ts or "").replace("Z", ""))
        return d.hour * 60 + d.minute
    except Exception:
        return 0


def _extract_target_text(block_lines: list[str]) -> str:
    if not block_lines:
        return ""
    body = [x for x in block_lines[1:] if str(x or "").strip()]
    txt = "\n".join(body).strip()
    return txt


def build_supervised_samples(
    conn,
    *,
    position_name: str,
    folder_paths: list[str],
    min_alignment_score: float = 0.35,
    limit_per_folder: int = 8000,
    tasks_only: bool = False,
) -> dict[str, Any]:
    pos = str(position_name or "").strip()
    if not pos:
        raise ValueError("position_name обязателен")
    bases: list[Path] = []
    for p in folder_paths or []:
        base = Path(str(p).strip())
        if base.exists() and base.is_dir():
            bases.append(base)
    if not bases:
        raise ValueError("Не найдены валидные папки с аудио")

    rows = conn.execute(
        """
        SELECT i.frequency, i.group_code, i.content, s.started_at
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id=i.session_id
        WHERE s.position_name=?
          AND COALESCE(i.content, '')<>''
        """,
        (pos,),
    ).fetchall()

    block_map: dict[tuple[str, str, str], list[tuple[int, str]]] = defaultdict(list)
    for r in rows or []:
        freq = _freq_norm(str(r["frequency"] or ""))
        grp = _group_norm(str(r["group_code"] or ""))
        day = _date_key(str(r["started_at"] or ""))
        for minute, lines in _split_blocks(str(r["content"] or "")):
            if minute is None:
                continue
            tgt = _extract_target_text(lines)
            if not tgt:
                continue
            block_map[(freq, grp, day)].append((int(minute), tgt))

    inserted = 0
    skipped = 0
    scanned = 0
    for base in bases:
        entries = scan_intercept_audio_files(
            base,
            tasks_only=bool(tasks_only),
            limit=int(limit_per_folder),
            newest_first=True,
        )
        for e in entries or []:
            scanned += 1
            freq = _freq_norm(e.frequency)
            grp = _group_norm(e.group_code)
            day = _date_key(e.recorded_at)
            blocks = block_map.get((freq, grp, day), [])
            if not blocks:
                skipped += 1
                continue
            am = _minute_of_day(e.recorded_at)
            best_diff = None
            best_text = ""
            best_minute = 0
            for bm, bt in blocks:
                diff = abs(int(bm) - int(am))
                if best_diff is None or diff < best_diff:
                    best_diff = diff
                    best_text = bt
                    best_minute = bm
            if best_diff is None:
                skipped += 1
                continue
            score = max(0.0, 1.0 - (float(best_diff) / 25.0))
            if score < float(min_alignment_score):
                skipped += 1
                continue
            audio_path = str((base / e.file_rel).resolve())
            sample_meta = {
                "alignment": {
                    "audio_minute": am,
                    "block_minute": int(best_minute),
                    "minute_diff": int(best_diff),
                },
                "recorded_at": e.recorded_at,
            }
            add_asr_train_sample(
                conn,
                position_name=pos,
                file_key=e.file_key,
                audio_path=audio_path,
                start_ts=float(e.recorded_ts or 0.0),
                end_ts=float(e.recorded_ts or 0.0) + float(e.duration_sec or 0.0),
                frequency=e.frequency,
                group_code=e.group_code,
                correspondent_id=e.correspondent_id,
                source_text="",
                target_text=best_text,
                alignment_score=score,
                status="validated",
                meta_json=json.dumps(sample_meta, ensure_ascii=False),
            )
            inserted += 1

    return {"scanned": scanned, "inserted": inserted, "skipped": skipped}

