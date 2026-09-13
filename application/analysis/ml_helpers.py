"""Общие ML-хелперы для analysis (без Flask)."""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

from web_portal.application.analysis.period_bounds import parse_analysis_datetime

_log = logging.getLogger("web_portal.analysis.ml_helpers")


def ml_setting_key(position_name: str, name: str) -> str:
    return f"ml:{str(position_name or '').strip()}:{str(name or '').strip()}"


def ml_get_setting(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    name: str,
    default_value: str,
) -> str:
    row = conn.execute(
        "SELECT value FROM ml_settings WHERE key=?",
        (ml_setting_key(position_name, name),),
    ).fetchone()
    if not row:
        return str(default_value)
    return str(row["value"] or default_value)


def ml_set_setting(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    name: str,
    value: str,
) -> None:
    conn.execute(
        """
        INSERT INTO ml_settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """,
        (ml_setting_key(position_name, name), str(value)),
    )


def ml_get_settings_map(
    conn: sqlite3.Connection, *, position_name: str
) -> dict[str, object]:
    defaults: dict[str, object] = {
        "window_minutes": 60,
        "train_epochs": 60,
        "train_lr": 0.001,
        "auto_activate": True,
        "retrain_min_samples": 30,
        "retrain_step": 10,
    }
    settings = dict(defaults)
    try:
        settings["window_minutes"] = max(
            5,
            min(
                720,
                int(
                    ml_get_setting(
                        conn,
                        position_name=position_name,
                        name="window_minutes",
                        default_value=str(defaults["window_minutes"]),
                    )
                ),
            ),
        )
    except Exception:
        settings["window_minutes"] = int(defaults["window_minutes"])
    try:
        settings["train_epochs"] = max(
            5,
            min(
                1000,
                int(
                    ml_get_setting(
                        conn,
                        position_name=position_name,
                        name="train_epochs",
                        default_value=str(defaults["train_epochs"]),
                    )
                ),
            ),
        )
    except Exception:
        settings["train_epochs"] = int(defaults["train_epochs"])
    try:
        settings["train_lr"] = max(
            0.00001,
            min(
                0.1,
                float(
                    ml_get_setting(
                        conn,
                        position_name=position_name,
                        name="train_lr",
                        default_value=str(defaults["train_lr"]),
                    )
                ),
            ),
        )
    except Exception:
        settings["train_lr"] = float(defaults["train_lr"])
    settings["auto_activate"] = (
        ml_get_setting(
            conn,
            position_name=position_name,
            name="auto_activate",
            default_value="1",
        )
        == "1"
    )
    try:
        settings["retrain_min_samples"] = max(
            10,
            min(
                10000,
                int(
                    ml_get_setting(
                        conn,
                        position_name=position_name,
                        name="retrain_min_samples",
                        default_value=str(defaults["retrain_min_samples"]),
                    )
                ),
            ),
        )
    except Exception:
        settings["retrain_min_samples"] = int(defaults["retrain_min_samples"])
    try:
        settings["retrain_step"] = max(
            1,
            min(
                1000,
                int(
                    ml_get_setting(
                        conn,
                        position_name=position_name,
                        name="retrain_step",
                        default_value=str(defaults["retrain_step"]),
                    )
                ),
            ),
        )
    except Exception:
        settings["retrain_step"] = int(defaults["retrain_step"])
    return settings


def ml_get_active_model_for_task(
    conn: sqlite3.Connection, *, task_type: str
) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT model_version, labels_json, feature_spec_json, metrics_json, artifact_path, task_type
        FROM ml_models
        WHERE is_active=1 AND task_type=?
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(task_type or "").strip(),),
    ).fetchone()


def ml_parse_scope_pairs(
    conn: sqlite3.Connection,
    *,
    unit_name: str,
    frequency: str,
    group_code: str,
) -> list[tuple[str, str]]:
    if frequency and group_code:
        return [(frequency, group_code)]
    if not unit_name:
        return []
    rows = conn.execute(
        "SELECT frequency, group_ FROM unit WHERE name=?",
        (unit_name,),
    ).fetchall()
    out: list[tuple[str, str]] = []
    for r in rows or []:
        out.append((str(r[0] or ""), str(r[1] or "")))
    return out


def ml_heuristic_label(features: dict[str, object] | None) -> str:
    f = features or {}
    active_ids = float(f.get("active_ids") or 0.0)
    sessions = float(f.get("sessions") or 0.0)
    new_ratio = float(f.get("new_ratio") or 0.0)
    gone_ratio = float(f.get("gone_ratio") or 0.0)
    hub_concentration = float(f.get("hub_concentration") or 0.0)
    cross_group_ratio = float(f.get("cross_group_ratio") or 0.0)
    density = float(f.get("density") or 0.0)
    if (
        new_ratio >= 0.35
        or gone_ratio >= 0.35
        or hub_concentration >= 0.48
        or cross_group_ratio >= 0.50
        or density >= 0.12
    ):
        return "alert_high"
    if (
        new_ratio >= 0.18
        or gone_ratio >= 0.18
        or hub_concentration >= 0.32
        or cross_group_ratio >= 0.30
        or (active_ids >= 12 and sessions >= 10)
    ):
        return "alert_medium"
    return "stable"


def ml_match_event_label(
    snap_start: str,
    snap_end: str,
    tag_rows: list[Any] | None,
) -> str:
    s = parse_analysis_datetime(snap_start)
    e = parse_analysis_datetime(snap_end)
    if not s or not e:
        return ""
    best_label = ""
    best_overlap = 0.0
    for tr in tag_rows or []:
        ts = parse_analysis_datetime(str(tr["start_ts"] or ""))
        te = parse_analysis_datetime(str(tr["end_ts"] or ""))
        if not ts or not te:
            continue
        left = max(s, ts)
        right = min(e, te)
        overlap = (right - left).total_seconds()
        if overlap > best_overlap:
            best_overlap = overlap
            best_label = str(tr["label"] or "")
    return best_label if best_overlap > 0 else ""


def ml_compute_retrain_recommended(
    conn: sqlite3.Connection,
    *,
    position_name: str,
) -> tuple[bool, int]:
    validated_count = int(
        (
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ml_event_tags
                WHERE position_name=? AND status='validated'
                """,
                (position_name,),
            ).fetchone()[0]
        )
        or 0
    )
    ml_settings = ml_get_settings_map(conn, position_name=position_name)
    retrain_min_samples = int(ml_settings.get("retrain_min_samples") or 30)
    retrain_step = max(1, int(ml_settings.get("retrain_step") or 10))
    retrain_recommended = bool(
        validated_count >= retrain_min_samples
        and ((validated_count - retrain_min_samples) % retrain_step == 0)
    )
    return retrain_recommended, validated_count
