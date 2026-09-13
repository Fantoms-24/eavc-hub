"""ArmTask XML: настройки, просмотр, применение аудиозаданий (без Flask)."""

from __future__ import annotations

import sqlite3
from typing import Any
from xml.etree import ElementTree as ET

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.application.intercepts.audio_arm_task_sync import (
    AUDIO_GLOBAL_POS,
    apply_desired_audio_freqs_from_arm_task,
    audio_task_freq_from_arm_task,
)
from web_portal.lib.arm_task_xml import (
    ARM_TASK_META_KEY,
    build_arm_task_view,
    effective_arm_task_dir_from_env,
    resolve_arm_task_xml_path,
)
from web_portal.lib.db import (
    get_sync_meta,
    list_intercept_audio_tasks,
    list_intercept_catalog,
    set_sync_meta,
)


def arm_task_effective_dir(conn: sqlite3.Connection) -> str:
    dbv = get_sync_meta(conn, ARM_TASK_META_KEY).strip()
    if dbv:
        return dbv
    return effective_arm_task_dir_from_env()


def load_arm_task_view_for_position(
    conn: sqlite3.Connection,
    position_name: str,
) -> tuple[dict[str, Any] | None, str, str, bool, bool]:
    cfg_dir = arm_task_effective_dir(conn)
    path, err, picked = resolve_arm_task_xml_path(cfg_dir)
    db_override = bool(get_sync_meta(conn, ARM_TASK_META_KEY).strip())
    if not path:
        return None, err, cfg_dir, picked, db_override
    catalog = list_intercept_catalog(conn, position_name)
    view = build_arm_task_view(xml_path=path, position_catalog=catalog)
    view["configured_path"] = cfg_dir
    view["picked_newest_from_dir"] = picked
    view["from_db_override"] = db_override
    view["position"] = position_name
    return view, "", cfg_dir, picked, db_override


def assemble_arm_task_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    dbv = get_sync_meta(conn, ARM_TASK_META_KEY).strip()
    envv = effective_arm_task_dir_from_env()
    merged = dbv or envv
    return {
        "ok": True,
        "effective_path": merged,
        "from_db": bool(dbv),
        "from_env": bool(envv),
        "db_path": dbv,
        "env_path": envv,
    }


def execute_arm_task_settings_save(
    conn: sqlite3.Connection,
    dir_s: str,
) -> dict[str, Any]:
    dir_s = str(dir_s or "").strip()
    if not dir_s:
        set_sync_meta(conn, ARM_TASK_META_KEY, "")
        return {"ok": True, "cleared": True}
    _path, err, _picked = resolve_arm_task_xml_path(dir_s)
    if not _path:
        raise AnalysisUseCaseHTTP(400, {"ok": False, "error": err})
    set_sync_meta(conn, ARM_TASK_META_KEY, dir_s)
    return {"ok": True, "saved": dir_s}


def execute_arm_task_view(
    conn: sqlite3.Connection,
    position_name: str,
) -> dict[str, Any]:
    try:
        view, err, cfg_dir, _picked, db_override = load_arm_task_view_for_position(
            conn, position_name
        )
    except ET.ParseError as e:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": f"Ошибка разбора XML: {e}"},
        ) from e
    except ValueError as e:
        raise AnalysisUseCaseHTTP(400, {"ok": False, "error": str(e)}) from e
    if not view:
        # Сохраняем прежний контракт GET (без явного HTTP 4xx в теле).
        return {
            "ok": False,
            "error": err,
            "configured_path": cfg_dir,
            "from_db_override": db_override,
        }
    return view


def execute_arm_task_apply_audio_tasks(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    created_by: str = "",
) -> dict[str, Any]:
    try:
        view, err, cfg_dir, _picked, db_override = load_arm_task_view_for_position(
            conn, position_name
        )
    except ET.ParseError as e:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": f"Ошибка разбора XML: {e}"},
        ) from e

    if not view:
        raise AnalysisUseCaseHTTP(
            400,
            {
                "ok": False,
                "error": err,
                "configured_path": cfg_dir,
                "from_db_override": db_override,
            },
        )

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
        raise AnalysisUseCaseHTTP(
            400,
            {
                "ok": False,
                "error": "В выбранном блоке XML нет частот для задания аудиоперехватов.",
            },
        )

    created_or_updated = apply_desired_audio_freqs_from_arm_task(
        conn,
        desired,
        created_by=created_by,
    )
    tasks = list_intercept_audio_tasks(conn, AUDIO_GLOBAL_POS)
    return {
        "ok": True,
        "position": position_name,
        "source_path": view.get("source_path"),
        "matched_block_index": view.get("matched_block_index"),
        "created_or_updated": created_or_updated,
        "active_count": len(desired),
        "tasks": tasks,
    }
