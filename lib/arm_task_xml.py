"""
Парсинг XML задания поста (ArmTask / Tempfinder_*.xml) и сопоставление с позицией по частотам справочника перехватов.
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from web_portal.lib.safe_paths import run_path_io

ARM_TASK_META_KEY = "arm_task_xml_dir"
ENV_ARM_TASK_DIR = "WEB_PORTAL_ARM_TASK_XML_DIR"


def _strip_ns(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _child_text(el: ET.Element | None, name: str) -> str:
    if el is None:
        return ""
    for c in el:
        if _strip_ns(c.tag) == name:
            return (c.text or "").strip()
    return ""


def _children_named(el: ET.Element | None, name: str) -> list[ET.Element]:
    if el is None:
        return []
    return [c for c in el if _strip_ns(c.tag) == name]


def freq_portal_to_hz(portal_freq: str) -> int | None:
    """Частота из справочника (МГц или Гц) -> целые Гц."""
    s = str(portal_freq or "").strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v < 1e5:
        v *= 1e6
    return int(round(v))


def _resolve_arm_task_xml_path_sync(raw: str) -> tuple[Path | None, str, bool]:
    """
    Возвращает (path, error, picked_from_dir).
    Если configured — файл, используется он; если каталог — самый новый по mtime Tempfinder*.xml, иначе любой *.xml.
    """
    try:
        p = Path(raw)
    except Exception:
        return None, "Некорректный путь.", False
    try:
        if not p.exists():
            return None, f"Не найдено: {raw}", False
    except OSError as e:
        return None, f"Доступ к пути: {e}", False
    if p.is_file():
        try:
            return p.resolve(), "", False
        except OSError as e:
            return None, str(e), False
    # каталог
    candidates: list[tuple[float, Path]] = []
    for pat in ("Tempfinder*.xml", "*.xml"):
        try:
            for f in p.glob(pat):
                if not f.is_file():
                    continue
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                candidates.append((m, f))
        except OSError:
            continue
    if not candidates:
        return None, f"В каталоге нет XML-файлов: {raw}", True
    candidates.sort(key=lambda x: -x[0])
    try:
        return candidates[0][1].resolve(), "", True
    except OSError as e:
        return None, str(e), True


def resolve_arm_task_xml_path(configured: str) -> tuple[Path | None, str, bool]:
    raw = (configured or "").strip()
    if not raw:
        return None, "Путь к XML не задан (hub_config.json: arm_task_xml_dir или WEB_PORTAL_ARM_TASK_XML_DIR).", False
    result, timed = run_path_io(
        lambda: _resolve_arm_task_xml_path_sync(raw),
        timeout_message="таймаут доступа к XML задания поста",
    )
    if timed is not None:
        return None, str(timed.error or "таймаут доступа к XML задания поста"), False
    return result if result is not None else (None, "Ошибка доступа к XML.", False)


def format_freq_mhz_from_hz(hz: int) -> str:
    """МГц для отображения и заданий: всегда 4 знака после запятой (157.0250, 166.8000)."""
    if not hz:
        return "0.0000"
    return f"{hz / 1e6:.4f}"


def _parse_dt(s: str) -> datetime | None:
    t = (s or "").strip()
    if not t:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(t[:19], fmt)
        except ValueError:
            continue
    return None


def _collect_task_block_freqs(block_el: ET.Element) -> tuple[list[dict[str, Any]], set[int]]:
    rows: list[dict[str, Any]] = []
    hz_set: set[int] = set()
    tbi = None
    for c in block_el:
        if _strip_ns(c.tag) == "TaskBlockItems":
            tbi = c
            break
    if tbi is None:
        return rows, hz_set
    for t in tbi:
        if _strip_ns(t.tag) != "TaskBlockItem":
            continue
        ft = _child_text(t, "Freq")
        try:
            hz = int(float(ft))
        except (ValueError, TypeError):
            hz = 0
        if hz:
            hz_set.add(hz)
        comment = _child_text(t, "Comment").replace("\r", " ").replace("\n", " ")
        comment = " ".join(comment.split())
        rows.append(
            {
                "freq_hz": hz,
                "freq_mhz": format_freq_mhz_from_hz(hz),
                "comment": comment,
            }
        )
    return rows, hz_set


def _channel_ids(arm_item: ET.Element) -> list[str]:
    out: list[str] = []
    for ch_wrap in _children_named(arm_item, "Channels"):
        for ch in ch_wrap:
            if _strip_ns(ch.tag) != "Channel":
                continue
            cid = _child_text(ch, "ID")
            if cid:
                out.append(cid)
    return out


def _plugin_title(block_el: ET.Element) -> str:
    for c in block_el:
        if _strip_ns(c.tag) != "PluginData":
            continue
        return _child_text(c, "Title")
    return ""


def parse_arm_task_file(path: Path) -> dict[str, Any]:
    tree = ET.parse(path)
    root = tree.getroot()
    if _strip_ns(root.tag) != "ArmTask":
        raise ValueError("Корень XML должен быть ArmTask")

    items_container = None
    for c in root:
        if _strip_ns(c.tag) == "ArmTaskItems":
            items_container = c
            break
    if items_container is None:
        raise ValueError("Нет узла ArmTaskItems")

    blocks: list[dict[str, Any]] = []
    idx = 0
    for arm_item in items_container:
        if _strip_ns(arm_item.tag) != "ArmTaskItem":
            continue
        block_el = None
        for c in arm_item:
            if _strip_ns(c.tag) == "Block":
                block_el = c
                break
        if block_el is None:
            continue
        name = _child_text(block_el, "Name")
        creation_time = _child_text(block_el, "CreationTime")
        rows, hz_set = _collect_task_block_freqs(block_el)
        ch_ids = _channel_ids(arm_item)
        blocks.append(
            {
                "index": idx,
                "name": name,
                "creation_time": creation_time,
                "creation_sort": _parse_dt(creation_time),
                "plugin_title": _plugin_title(block_el),
                "channel_ids": ch_ids,
                "channel_count": len(ch_ids),
                "rows": rows,
                "freq_hz_set": hz_set,
            }
        )
        idx += 1

    return {"blocks": blocks}


def _norm_block_name(name: object) -> str:
    return " ".join(str(name or "").strip().lower().replace("ё", "е").split())


def _is_post_assignment_block(block: dict[str, Any]) -> bool:
    name = _norm_block_name(block.get("name"))
    # В XML встречается "Сментика"; пользователь также называет блок "Семантика".
    return "сментик" in name or "семантик" in name


def match_block_for_position_hz(
    blocks: list[dict[str, Any]], position_hz: set[int]
) -> tuple[int | None, int]:
    """
    Для задания поста сначала берём XML-блок "Сментика/Семантика".
    Если такого блока нет, запасной вариант: максимальное пересечение частот
    со справочником позиции, затем более поздний CreationTime.
    """
    if not blocks:
        return None, 0

    preferred = [b for b in blocks if _is_post_assignment_block(b)]
    if preferred:
        preferred.sort(
            key=lambda b: b.get("creation_sort")
            if isinstance(b.get("creation_sort"), datetime)
            else datetime.min,
            reverse=True,
        )
        chosen = preferred[0]
        hz_set = chosen.get("freq_hz_set") or set()
        score = len(hz_set & position_hz) if position_hz else 0
        return int(chosen["index"]), score

    scored: list[tuple[int, datetime, int]] = []
    for b in blocks:
        hz_set = b.get("freq_hz_set") or set()
        inter = len(hz_set & position_hz) if position_hz else 0
        cdt = b.get("creation_sort")
        dt = cdt if isinstance(cdt, datetime) else datetime.min
        scored.append((inter, dt, int(b["index"])))
    scored.sort(
        key=lambda x: (
            -x[0],
            -x[1].year,
            -x[1].month,
            -x[1].day,
            -x[1].hour,
            -x[1].minute,
            -x[1].second,
        )
    )
    best_inter, _dt, best_idx = scored[0]
    if position_hz and best_inter == 0:
        # только по дате
        with_dt = [
            (b.get("creation_sort"), int(b["index"]))
            for b in blocks
            if isinstance(b.get("creation_sort"), datetime)
        ]
        if with_dt:
            with_dt.sort(key=lambda x: x[0], reverse=True)  # type: ignore[type-var]
            return with_dt[0][1], 0
    return best_idx, max(0, best_inter)


def build_arm_task_view(
    *,
    xml_path: Path,
    position_catalog: list[dict[str, Any]],
) -> dict[str, Any]:
    try:
        st = xml_path.stat()
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        mtime = ""

    position_hz: set[int] = set()
    for r in position_catalog or []:
        hz = freq_portal_to_hz(str(r.get("frequency") or ""))
        if hz:
            position_hz.add(hz)

    parsed = parse_arm_task_file(xml_path)
    blocks_raw: list[dict[str, Any]] = parsed["blocks"]
    matched_idx, score = match_block_for_position_hz(blocks_raw, position_hz)

    blocks_out: list[dict[str, Any]] = []
    for b in blocks_raw:
        hz_set: set[int] = set(b.get("freq_hz_set") or [])
        rows: list[dict[str, Any]] = list(b.get("rows") or [])
        rows_out = []
        for row in rows:
            hz = int(row.get("freq_hz") or 0)
            rows_out.append(
                {
                    **row,
                    "in_catalog": hz in position_hz if hz else False,
                }
            )
        blocks_out.append(
            {
                "index": b["index"],
                "name": b.get("name"),
                "creation_time": b.get("creation_time"),
                "plugin_title": b.get("plugin_title"),
                "channel_ids": b.get("channel_ids"),
                "channel_count": b.get("channel_count"),
                "freq_match_count": len(hz_set & position_hz),
                "rows": rows_out,
            }
        )
    matched = None
    if matched_idx is not None:
        for bo in blocks_out:
            if int(bo["index"]) == matched_idx:
                matched = bo
                break

    return {
        "ok": True,
        "source_path": str(xml_path),
        "source_mtime": mtime,
        "position_freq_hz_count": len(position_hz),
        "position_freqs_mhz_sample": sorted(
            {format_freq_mhz_from_hz(int(h)) for h in position_hz}
        )[:40],
        "blocks": blocks_out,
        "matched_block_index": matched_idx,
        "matched_freq_intersections": score,
        "matched": matched,
    }


def effective_arm_task_dir_from_env() -> str:
    return (os.environ.get(ENV_ARM_TASK_DIR) or "").strip()
