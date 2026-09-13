"""Синхронизация заданий аудиоперехватов из ArmTask XML (без Flask)."""

from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.arm_task_xml import (
    ARM_TASK_META_KEY,
    build_arm_task_view,
    effective_arm_task_dir_from_env,
    resolve_arm_task_xml_path,
)
from web_portal.lib.db import (
    add_intercept_audio_task,
    get_intercept_audio_state,
    get_sync_meta,
    list_intercept_catalog,
    upsert_intercept_audio_state,
)

# Для аудиоперехватов настройки «задания поста» и папок общие для всего хаба.
AUDIO_GLOBAL_POS = "__audio_global__"


def audio_task_freq_from_arm_task(freq_mhz: object) -> str:
    """МГц в задании аудио: ровно 4 знака после запятой, без отсечения нулей."""
    s = str(freq_mhz or "").strip().replace(",", ".")
    if not s:
        return ""
    try:
        return f"{float(s):.4f}"
    except Exception:
        return s


def apply_desired_audio_freqs_from_arm_task(
    conn: sqlite3.Connection,
    desired: dict[str, str],
    *,
    created_by: str = "",
) -> int:
    """
    Записывает desired {freq: unit_name} в глобальные аудиозадания,
    выключает частоты вне списка. Возвращает число созданных/обновлённых.
    """
    created_or_updated = 0
    for freq, unit_name in desired.items():
        tid = add_intercept_audio_task(
            conn,
            position_name=AUDIO_GLOBAL_POS,
            frequency=freq,
            unit_name=unit_name,
            created_by=created_by,
        )
        conn.execute(
            """
            UPDATE intercept_audio_tasks
            SET unit_name=?, is_active=1
            WHERE id=? AND position_name=?
            """,
            (unit_name, int(tid or 0), AUDIO_GLOBAL_POS),
        )
        created_or_updated += 1

    # Текущее XML-задание — источник истины для активных аудиочастот.
    placeholders = ",".join("?" for _ in desired)
    conn.execute(
        f"""
        UPDATE intercept_audio_tasks
        SET is_active=0
        WHERE position_name=? AND frequency NOT IN ({placeholders})
        """,
        [AUDIO_GLOBAL_POS, *desired.keys()],
    )
    conn.commit()

    state = get_intercept_audio_state(conn, position_name=AUDIO_GLOBAL_POS)
    upsert_intercept_audio_state(
        conn,
        position_name=AUDIO_GLOBAL_POS,
        folder_path=str(state.get("folder_path") or ""),
        tasks_only=True,
        last_time_ts=float(state.get("last_time_ts") or 0),
        is_running=True,
    )
    return created_or_updated


def sync_intercepts_audio_tasks_from_arm_task(
    conn: sqlite3.Connection, *, position_name: str, created_by: str = ""
) -> dict[str, Any]:
    """
    Подтягивает текущий ArmTask в глобальное задание аудиоперехватов.
    Вызывается и из раздела анализа, и при открытии аудиоперехватов.
    """
    cfg_dir = (
        get_sync_meta(conn, ARM_TASK_META_KEY).strip()
        or effective_arm_task_dir_from_env()
    )
    path, err, _picked = resolve_arm_task_xml_path(cfg_dir)
    if not path:
        return {"ok": False, "error": err, "active_count": 0}

    catalog = list_intercept_catalog(conn, position_name)
    view = build_arm_task_view(xml_path=path, position_catalog=catalog)
    matched = view.get("matched") if isinstance(view, dict) else None
    rows = matched.get("rows", []) if isinstance(matched, dict) else []

    desired: dict[str, str] = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        freq = audio_task_freq_from_arm_task(row.get("freq_mhz"))
        if not freq:
            continue
        desired[freq] = str(row.get("comment") or "").strip()
    if not desired:
        return {
            "ok": False,
            "error": "В XML не найдено частот для аудиозадания.",
            "active_count": 0,
        }

    apply_desired_audio_freqs_from_arm_task(
        conn,
        desired,
        created_by=created_by,
    )
    return {
        "ok": True,
        "active_count": len(desired),
        "source_path": str(path),
        "matched_block_index": view.get("matched_block_index"),
    }
