"""ASR train/models/feedback (физически из ``_impl``)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db



def add_asr_train_sample(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    file_key: str,
    audio_path: str,
    start_ts: float,
    end_ts: float,
    frequency: str,
    group_code: str,
    correspondent_id: str,
    source_text: str,
    target_text: str,
    alignment_score: float,
    status: str = "validated",
    meta_json: str = "{}",
) -> int:
    init_db(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO asr_train_samples
          (position_name, file_key, audio_path, start_ts, end_ts, frequency, group_code, correspondent_id,
           source_text, target_text, alignment_score, status, meta_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            str(position_name or ""),
            str(file_key or ""),
            str(audio_path or ""),
            float(start_ts or 0.0),
            float(end_ts or 0.0),
            str(frequency or ""),
            str(group_code or ""),
            str(correspondent_id or ""),
            str(source_text or ""),
            str(target_text or ""),
            float(alignment_score or 0.0),
            str(status or "validated"),
            str(meta_json or "{}"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def list_asr_train_samples(
    conn: sqlite3.Connection, *, position_name: str, status: str = "validated", limit: int = 20000
) -> list[dict[str, Any]]:
    init_db(conn)
    lim = max(1, min(int(limit or 1), 200000))
    rows = conn.execute(
        """
        SELECT id, file_key, audio_path, start_ts, end_ts, frequency, group_code, correspondent_id,
               source_text, target_text, alignment_score, status, meta_json, created_at
        FROM asr_train_samples
        WHERE position_name=? AND status=?
        ORDER BY created_at ASC, id ASC
        LIMIT ?
        """,
        (str(position_name or ""), str(status or "validated"), lim),
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "file_key": str(r["file_key"] or ""),
            "audio_path": str(r["audio_path"] or ""),
            "start_ts": float(r["start_ts"] or 0.0),
            "end_ts": float(r["end_ts"] or 0.0),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "correspondent_id": str(r["correspondent_id"] or ""),
            "source_text": str(r["source_text"] or ""),
            "target_text": str(r["target_text"] or ""),
            "alignment_score": float(r["alignment_score"] or 0.0),
            "status": str(r["status"] or ""),
            "meta_json": str(r["meta_json"] or "{}"),
            "created_at": str(r["created_at"] or ""),
        }
        for r in (rows or [])
    ]


def create_asr_training_run(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    run_id: str,
    model_version: str,
    params: dict[str, Any] | None = None,
) -> None:
    init_db(conn)
    conn.execute(
        """
        INSERT INTO asr_training_runs
          (position_name, run_id, model_version, status, params_json)
        VALUES (?, ?, ?, 'running', ?)
        """,
        (
            str(position_name or ""),
            str(run_id or ""),
            str(model_version or ""),
            json.dumps(params or {}, ensure_ascii=False),
        ),
    )
    conn.commit()


def finish_asr_training_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    status: str,
    metrics: dict[str, Any] | None = None,
    error_text: str = "",
) -> None:
    init_db(conn)
    conn.execute(
        """
        UPDATE asr_training_runs
        SET status=?, metrics_json=?, error_text=?, ended_at=CURRENT_TIMESTAMP
        WHERE run_id=?
        """,
        (
            str(status or "done"),
            json.dumps(metrics or {}, ensure_ascii=False),
            str(error_text or ""),
            str(run_id or ""),
        ),
    )
    conn.commit()


def upsert_asr_model(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    model_version: str,
    base_model: str,
    artifact_path: str,
    metrics: dict[str, Any] | None = None,
    is_active: bool = False,
) -> None:
    init_db(conn)
    pos = str(position_name or "")
    if is_active:
        conn.execute("UPDATE asr_models SET is_active=0 WHERE position_name=?", (pos,))
    conn.execute(
        """
        INSERT INTO asr_models
          (position_name, model_version, base_model, artifact_path, metrics_json, is_active, activated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(position_name, model_version) DO UPDATE SET
          base_model=excluded.base_model,
          artifact_path=excluded.artifact_path,
          metrics_json=excluded.metrics_json,
          is_active=excluded.is_active,
          activated_at=excluded.activated_at
        """,
        (
            pos,
            str(model_version or ""),
            str(base_model or ""),
            str(artifact_path or ""),
            json.dumps(metrics or {}, ensure_ascii=False),
            1 if is_active else 0,
            str(
                conn.execute("SELECT datetime('now')").fetchone()[0]
                if is_active
                else ""
            ),
        ),
    )
    conn.commit()


def list_asr_models(
    conn: sqlite3.Connection, *, position_name: str, limit: int = 20
) -> list[dict[str, Any]]:
    init_db(conn)
    lim = max(1, min(int(limit or 1), 200))
    rows = conn.execute(
        """
        SELECT model_version, base_model, artifact_path, metrics_json, is_active, created_at, activated_at
        FROM asr_models
        WHERE position_name=?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (str(position_name or ""), lim),
    ).fetchall()
    return [
        {
            "model_version": str(r["model_version"] or ""),
            "base_model": str(r["base_model"] or ""),
            "artifact_path": str(r["artifact_path"] or ""),
            "metrics": json.loads(str(r["metrics_json"] or "{}")),
            "is_active": bool(int(r["is_active"] or 0)),
            "created_at": str(r["created_at"] or ""),
            "activated_at": str(r["activated_at"] or ""),
        }
        for r in (rows or [])
    ]


def activate_asr_model(
    conn: sqlite3.Connection, *, position_name: str, model_version: str
) -> bool:
    init_db(conn)
    pos = str(position_name or "")
    mv = str(model_version or "")
    row = conn.execute(
        "SELECT id FROM asr_models WHERE position_name=? AND model_version=?",
        (pos, mv),
    ).fetchone()
    if not row:
        return False
    conn.execute("UPDATE asr_models SET is_active=0 WHERE position_name=?", (pos,))
    conn.execute(
        "UPDATE asr_models SET is_active=1, activated_at=datetime('now') WHERE position_name=? AND model_version=?",
        (pos, mv),
    )
    conn.commit()
    return True


def get_active_asr_model(
    conn: sqlite3.Connection, *, position_name: str
) -> dict[str, Any] | None:
    init_db(conn)
    row = conn.execute(
        """
        SELECT model_version, base_model, artifact_path, metrics_json, created_at, activated_at
        FROM asr_models
        WHERE position_name=? AND is_active=1
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(position_name or ""),),
    ).fetchone()
    if not row:
        return None
    return {
        "model_version": str(row["model_version"] or ""),
        "base_model": str(row["base_model"] or ""),
        "artifact_path": str(row["artifact_path"] or ""),
        "metrics": json.loads(str(row["metrics_json"] or "{}")),
        "created_at": str(row["created_at"] or ""),
        "activated_at": str(row["activated_at"] or ""),
    }


def get_asr_settings(conn: sqlite3.Connection, *, position_name: str) -> dict[str, Any]:
    init_db(conn)
    defaults = {
        "whisper_model_name": "small",
        "batch_size": 8,
        "learning_rate": 0.0001,
        "epochs": 6,
        "auto_activate": True,
        "min_alignment_score": 0.35,
        "auto_retrain": True,
        "auto_retrain_min_samples": 40,
        "auto_retrain_step": 20,
    }
    rows = conn.execute(
        "SELECT key, value FROM asr_settings WHERE position_name=?",
        (str(position_name or ""),),
    ).fetchall()
    out: dict[str, Any] = dict(defaults)
    kv = {str(r["key"] or ""): str(r["value"] or "") for r in (rows or [])}
    if "whisper_model_name" in kv:
        saved_model = str(kv["whisper_model_name"] or "").strip()
        if saved_model in {"tiny", "openai/whisper-tiny"}:
            saved_model = "small"
        out["whisper_model_name"] = saved_model
    for k, dv in {
        "batch_size": 8,
        "epochs": 6,
        "auto_retrain_min_samples": 40,
        "auto_retrain_step": 20,
    }.items():
        try:
            out[k] = max(1, int(kv.get(k, dv)))
        except Exception:
            out[k] = dv
    for k, dv in {"learning_rate": 0.0001, "min_alignment_score": 0.35}.items():
        try:
            out[k] = float(kv.get(k, dv))
        except Exception:
            out[k] = dv
    out["auto_activate"] = str(kv.get("auto_activate", "1")).lower() in {"1", "true", "yes"}
    out["auto_retrain"] = str(kv.get("auto_retrain", "1")).lower() in {"1", "true", "yes"}
    return out


def set_asr_settings(
    conn: sqlite3.Connection, *, position_name: str, settings: dict[str, Any]
) -> dict[str, Any]:
    init_db(conn)
    pos = str(position_name or "")
    for k, v in (settings or {}).items():
        conn.execute(
            """
            INSERT INTO asr_settings (position_name, key, value, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(position_name, key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
            """,
            (pos, str(k or ""), str(v)),
        )
    conn.commit()
    return get_asr_settings(conn, position_name=pos)


def add_asr_feedback(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    file_key: str,
    prediction_text: str,
    corrected_text: str,
    feedback_label: str,
    reviewer: str,
    status: str = "validated",
) -> int:
    init_db(conn)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO asr_feedback
          (position_name, file_key, prediction_text, corrected_text, feedback_label, reviewer, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(position_name or ""),
            str(file_key or ""),
            str(prediction_text or ""),
            str(corrected_text or ""),
            str(feedback_label or ""),
            str(reviewer or ""),
            str(status or "validated"),
        ),
    )
    conn.commit()
    return int(cur.lastrowid or 0)


def count_asr_feedback(
    conn: sqlite3.Connection, *, position_name: str, status: str = "validated"
) -> int:
    init_db(conn)
    row = conn.execute(
        "SELECT COUNT(*) FROM asr_feedback WHERE position_name=? AND status=?",
        (str(position_name or ""), str(status or "validated")),
    ).fetchone()
    return int((row[0] if row else 0) or 0)


__all__ = [
    "add_asr_train_sample",
    "list_asr_train_samples",
    "create_asr_training_run",
    "finish_asr_training_run",
    "upsert_asr_model",
    "list_asr_models",
    "activate_asr_model",
    "get_active_asr_model",
    "get_asr_settings",
    "set_asr_settings",
    "add_asr_feedback",
    "count_asr_feedback",
]
