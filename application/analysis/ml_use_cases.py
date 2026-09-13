"""Orchestration for /api/analysis/ml/* handlers (без Flask)."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Any

from web_portal.application.analysis.ml_helpers import (
    ml_get_active_model_for_task,
    ml_get_settings_map,
    ml_heuristic_label,
    ml_match_event_label,
    ml_parse_scope_pairs,
    ml_setting_key,
    ml_compute_retrain_recommended,
)
from web_portal.application.analysis.period_bounds import (
    fmt_analysis_dt,
    msk_now_naive,
    parse_analysis_datetime,
)
from web_portal.application.analysis.seans_rows import collect_seans_rows

_log = logging.getLogger("web_portal.analysis.ml_use_cases")

# Lazy ML deps: importing torch/sklearn at module import hangs cold starts / pytest collection.
_ML: dict[str, Any] | None = None


def _missing_optional(dep: str):
    def _raise(*_args, **_kwargs):
        raise RuntimeError(f"Опциональная зависимость '{dep}' недоступна в этой сборке")

    return _raise


def _ml() -> dict[str, Any]:
    """Load lib.ml symbols once (first ML execute_* call)."""
    global _ML
    if _ML is not None:
        return _ML
    try:
        from web_portal.lib.ml.features import (
            FEATURE_ORDER,
            build_forecast_samples as ml_build_forecast_samples,
            build_snapshots as ml_build_snapshots,
            vectorize_feature_dict as ml_vectorize_feature_dict,
        )
        from web_portal.lib.ml.train import train_multiclass as ml_train_multiclass
        from web_portal.lib.ml.predict import (
            predict_probabilities as ml_predict_probabilities,
        )
        from web_portal.lib.ml.model import save_checkpoint as ml_save_checkpoint
        from web_portal.lib.ml.explain import (
            explain_feature_contributions as ml_explain_feature_contributions,
            explain_hotspots as ml_explain_hotspots,
        )
        from web_portal.lib.ml.registry import ml_artifact_path_for, ml_new_model_version

        _ML = {
            "FEATURE_ORDER": FEATURE_ORDER,
            "ml_build_snapshots": ml_build_snapshots,
            "ml_build_forecast_samples": ml_build_forecast_samples,
            "ml_vectorize_feature_dict": ml_vectorize_feature_dict,
            "ml_train_multiclass": ml_train_multiclass,
            "ml_predict_probabilities": ml_predict_probabilities,
            "ml_save_checkpoint": ml_save_checkpoint,
            "ml_explain_feature_contributions": ml_explain_feature_contributions,
            "ml_explain_hotspots": ml_explain_hotspots,
            "ml_artifact_path_for": ml_artifact_path_for,
            "ml_new_model_version": ml_new_model_version,
        }
    except Exception:
        _log.debug("ML optional deps unavailable", exc_info=True)
        miss = _missing_optional("ML")
        _ML = {
            "FEATURE_ORDER": [],
            "ml_build_snapshots": miss,
            "ml_build_forecast_samples": miss,
            "ml_vectorize_feature_dict": miss,
            "ml_train_multiclass": miss,
            "ml_predict_probabilities": miss,
            "ml_save_checkpoint": miss,
            "ml_explain_feature_contributions": miss,
            "ml_explain_hotspots": miss,
            "ml_artifact_path_for": miss,
            "ml_new_model_version": miss,
        }
    return _ML


def _ensure_ml_globals() -> None:
    """Bind lazy ML symbols into module globals for execute_* bodies."""
    g = globals()
    if g.get("_ML_READY"):
        return
    g.update(_ml())
    g["_ML_READY"] = True


def _resolve_ml_time_range(
    start_raw: str,
    end_raw: str,
    *,
    default_delta: timedelta,
) -> tuple[datetime, datetime]:
    start = parse_analysis_datetime(start_raw)
    end = parse_analysis_datetime(end_raw)
    if not start or not end or end <= start:
        end = msk_now_naive()
        start = end - default_delta
    return start, end


def execute_ml_dataset_build(
    conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection,
    *,
    position_name: str,
    body: dict[str, object],
) -> dict[str, Any]:
    _ensure_ml_globals()
    start, end = _resolve_ml_time_range(
        str(body.get("start") or ""),
        str(body.get("end") or ""),
        default_delta=timedelta(days=7),
    )
    window_minutes = int(body.get("window_minutes") or 60)
    window_minutes = max(5, min(720, window_minutes))
    min_train_windows = max(8, int(body.get("min_train_windows") or 12))
    unit_name = str(body.get("unit_name") or "").strip()
    frequency = str(body.get("frequency") or "").strip()
    group_code = str(body.get("group") or "").strip()
    group_query = str(body.get("group_query") or "").strip()
    auto_expand_range = bool(body.get("auto_expand_range", True))

    expanded_range = False
    current_minutes = max(1.0, (end - start).total_seconds() / 60.0)
    required_minutes = float(window_minutes * min_train_windows)
    if auto_expand_range and current_minutes < required_minutes:
        start = end - timedelta(minutes=required_minutes)
        expanded_range = True

    ml_settings = ml_get_settings_map(conn, position_name=position_name)
    scope_pairs = ml_parse_scope_pairs(
        conn,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
    )
    if "window_minutes" not in body:
        window_minutes = int(ml_settings.get("window_minutes") or window_minutes)
    rows = collect_seans_rows(
        seans_conn,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        position_name=position_name,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
    )
    snapshots = ml_build_snapshots(
        rows,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        window_minutes=window_minutes,
    )
    tag_rows = conn.execute(
        """
        SELECT start_ts, end_ts, label
        FROM ml_event_tags
        WHERE position_name=? AND status='validated'
        ORDER BY start_ts ASC
        """,
        (position_name,),
    ).fetchall()

    inserted = 0
    manual_labeled = 0
    auto_labeled = 0
    conn.execute(
        """
        DELETE FROM ml_feature_snapshots
        WHERE position_name=? AND source='dataset-build' AND start_ts>=? AND end_ts<=? AND window_minutes=?
        """,
        (position_name, fmt_analysis_dt(start), fmt_analysis_dt(end), window_minutes),
    )
    auto_label_mode = str(body.get("auto_label_mode") or "heuristic").strip().lower()
    for snap in snapshots:
        label = ml_match_event_label(snap.start, snap.end, tag_rows)
        if label:
            manual_labeled += 1
        elif auto_label_mode in {"heuristic", "bootstrap"}:
            label = ml_heuristic_label(snap.features)
            auto_labeled += 1
        conn.execute(
            """
            INSERT INTO ml_feature_snapshots
                (position_name, start_ts, end_ts, window_minutes, feature_json, label, tag, source)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'dataset-build')
            """,
            (
                position_name,
                snap.start,
                snap.end,
                window_minutes,
                json.dumps(
                    {
                        "features": snap.features,
                        "top_units": snap.top_units,
                        "top_groups": snap.top_groups,
                        "top_ids": snap.top_ids,
                    },
                    ensure_ascii=False,
                ),
                label,
                label,
            ),
        )
        inserted += 1
    conn.commit()
    return {
        "ok": True,
        "inserted": inserted,
        "manual_labeled": manual_labeled,
        "auto_labeled": auto_labeled,
        "expanded_range": expanded_range,
        "min_train_windows": min_train_windows,
        "start": fmt_analysis_dt(start),
        "end": fmt_analysis_dt(end),
        "window_minutes": window_minutes,
        "auto_label_mode": auto_label_mode,
    }


def execute_ml_train(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    body: dict[str, object],
    activated_at: str,
) -> dict[str, Any]:
    _ensure_ml_globals()
    epochs = int(body.get("epochs") or 60)
    lr = float(body.get("lr") or 0.001)
    activate = bool(body.get("activate", True))
    val_split = str(body.get("val_split") or "stratified").strip().lower()
    if val_split not in ("stratified", "time"):
        val_split = "stratified"
    try:
        val_size = float(body.get("val_size") or 0.2)
    except (TypeError, ValueError):
        val_size = 0.2
    val_size = min(max(0.05, val_size), 0.5)
    try:
        random_seed = int(body.get("random_seed") or 42)
    except (TypeError, ValueError):
        random_seed = 42
    try:
        weight_decay = float(body.get("weight_decay") or 0.0)
    except (TypeError, ValueError):
        weight_decay = 0.0
    weight_decay = min(max(0.0, weight_decay), 0.1)
    run_id = f"run-{int(time.time())}"
    model_version = ml_new_model_version()
    try:
        ml_settings = ml_get_settings_map(conn, position_name=position_name)
        if "epochs" not in body:
            epochs = int(ml_settings.get("train_epochs") or epochs)
        if "lr" not in body:
            lr = float(ml_settings.get("train_lr") or lr)
        if "activate" not in body:
            activate = bool(ml_settings.get("auto_activate"))
        conn.execute(
            """
            INSERT INTO ml_training_runs (run_id, model_version, status, params_json)
            VALUES (?, ?, 'running', ?)
            """,
            (
                run_id,
                model_version,
                json.dumps(
                    {
                        "epochs": epochs,
                        "lr": lr,
                        "val_split": val_split,
                        "val_size": val_size,
                        "random_seed": random_seed,
                        "weight_decay": weight_decay,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        rows = conn.execute(
            """
            SELECT feature_json, label
            FROM ml_feature_snapshots
            WHERE position_name=? AND label<>''
            ORDER BY end_ts ASC
            """,
            (position_name,),
        ).fetchall()
        x: list[list[float]] = []
        y: list[str] = []
        for r in rows or []:
            try:
                snap_payload = json.loads(str(r["feature_json"] or "{}"))
                feats = snap_payload.get("features") or {}
                x.append(ml_vectorize_feature_dict(feats))
                y.append(str(r["label"] or ""))
            except Exception:
                continue
        min_samples = 8
        if len(x) < min_samples:
            raise RuntimeError(
                f"Недостаточно размеченных примеров (нужно минимум {min_samples}). "
                "Соберите датасет и/или добавьте теги событий."
            )
        unique_classes = sorted({str(v) for v in y})
        if len(unique_classes) < 2:
            raise RuntimeError(
                "Недостаточно классов для обучения (нужно минимум 2). "
                "Добавьте теги разных типов или пересоберите dataset в режиме auto_label_mode=heuristic."
            )

        train_res = ml_train_multiclass(
            x,
            y,
            epochs=epochs,
            lr=lr,
            weight_decay=weight_decay,
            val_split=val_split,
            val_size=val_size,
            random_seed=random_seed,
        )
        artifact = ml_artifact_path_for(model_version)
        ml_save_checkpoint(
            str(artifact),
            {
                "state_dict": train_res.state_dict,
                "labels": train_res.labels,
                "feature_order": FEATURE_ORDER,
                "mean": train_res.mean,
                "std": train_res.std,
                "metrics": train_res.metrics,
            },
        )
        if activate:
            conn.execute(
                "UPDATE ml_models SET is_active=0 WHERE task_type NOT LIKE 'forecast_h%'"
            )
        conn.execute(
            """
            INSERT INTO ml_models
                (model_version, framework, task_type, labels_json, feature_spec_json, metrics_json, artifact_path, is_active, activated_at)
            VALUES (?, 'pytorch', 'multiclass_event', ?, ?, ?, ?, ?, ?)
            """,
            (
                model_version,
                json.dumps(train_res.labels, ensure_ascii=False),
                json.dumps(
                    {
                        "feature_order": FEATURE_ORDER,
                        "val_split": val_split,
                        "random_seed": random_seed,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(train_res.metrics, ensure_ascii=False),
                str(artifact),
                1 if activate else 0,
                activated_at if activate else "",
            ),
        )
        conn.execute(
            """
            UPDATE ml_training_runs
            SET status='done', metrics_json=?, ended_at=CURRENT_TIMESTAMP
            WHERE run_id=?
            """,
            (json.dumps(train_res.metrics, ensure_ascii=False), run_id),
        )
        conn.execute(
            """
            INSERT INTO ml_settings (key, value, updated_at)
            VALUES (?, '0', CURRENT_TIMESTAMP)
            ON CONFLICT(key) DO UPDATE SET value='0', updated_at=CURRENT_TIMESTAMP
            """,
            (ml_setting_key(position_name, "retrain_recommended"),),
        )
        conn.commit()
        return {
            "ok": True,
            "run_id": run_id,
            "model_version": model_version,
            "metrics": train_res.metrics,
            "active": activate,
        }
    except Exception as e:
        try:
            conn.execute(
                """
                UPDATE ml_training_runs
                SET status='error', error_text=?, ended_at=CURRENT_TIMESTAMP
                WHERE run_id=?
                """,
                (str(e), run_id),
            )
            conn.commit()
        except Exception:
            _log.debug("execute_ml_train: suppressed error", exc_info=True)
        raise


def execute_ml_predict(
    conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection,
    *,
    position_name: str,
    body: dict[str, object],
) -> dict[str, Any]:
    _ensure_ml_globals()
    unit_name = str(body.get("unit_name") or "").strip()
    frequency = str(body.get("frequency") or "").strip()
    group_code = str(body.get("group") or "").strip()
    group_query = str(body.get("group_query") or "").strip()
    start = parse_analysis_datetime(str(body.get("start") or ""))
    end = parse_analysis_datetime(str(body.get("end") or ""))
    window_minutes = int(body.get("window_minutes") or 60)
    window_minutes = max(5, min(720, window_minutes))
    if not start or not end or end <= start:
        end = msk_now_naive()
        start = end - timedelta(minutes=window_minutes)

    active_model = ml_get_active_model_for_task(conn, task_type="multiclass_event")
    if not active_model:
        return {
            "ok": True,
            "model_ready": False,
            "ml_risk": {
                "score": 0,
                "level": "low",
                "top_label": "none",
                "probability": 0.0,
                "probabilities": [],
                "reasons": [{"reason": "ML-модель не обучена/не активирована"}],
                "hotspots": [],
            },
        }
    scope_pairs = ml_parse_scope_pairs(
        conn,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
    )
    rows = collect_seans_rows(
        seans_conn,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        position_name=position_name,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
    )
    snapshots = ml_build_snapshots(
        rows,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        window_minutes=window_minutes,
    )
    if not snapshots:
        raise RuntimeError("Нет данных для ML-прогноза")
    snap = snapshots[-1]
    vec = ml_vectorize_feature_dict(snap.features)
    pred = ml_predict_probabilities(str(active_model["artifact_path"] or ""), vec)
    probs = pred.get("probabilities") or []
    reasons = ml_explain_feature_contributions(snap.features, probs)
    hotspots = ml_explain_hotspots(snap.top_units, snap.top_groups, snap.top_ids)
    top = pred.get("top") or {"label": "none", "probability": 0.0}
    top_prob = float(top.get("probability") or 0.0)
    score = int(max(0, min(100, round(top_prob * 100.0))))
    level = "high" if score >= 65 else ("medium" if score >= 35 else "low")

    cur = conn.execute(
        """
        INSERT INTO ml_predictions
            (position_name, start_ts, end_ts, model_version, top_label, top_probability, probabilities_json, reasons_json, hotspots_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            position_name,
            snap.start,
            snap.end,
            str(active_model["model_version"] or ""),
            str(top.get("label") or "none"),
            top_prob,
            json.dumps(probs, ensure_ascii=False),
            json.dumps(reasons, ensure_ascii=False),
            json.dumps(hotspots, ensure_ascii=False),
        ),
    )
    pred_id = int(cur.lastrowid or 0)
    conn.commit()
    return {
        "ok": True,
        "model_ready": True,
        "prediction_id": pred_id,
        "window": {"start": snap.start, "end": snap.end},
        "ml_risk": {
            "score": score,
            "level": level,
            "top_label": str(top.get("label") or "none"),
            "probability": round(top_prob, 6),
            "probabilities": probs,
            "reasons": reasons,
            "hotspots": hotspots,
            "model_version": str(active_model["model_version"] or ""),
        },
    }


def execute_ml_feedback(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    body: dict[str, object],
    reviewer: str,
) -> dict[str, Any]:
    prediction_id = int(body.get("prediction_id") or 0)
    feedback_label = str(body.get("feedback_label") or "").strip()
    corrected_label = str(body.get("corrected_label") or "").strip()
    note = str(body.get("note") or "").strip()
    if prediction_id <= 0 or not feedback_label:
        raise ValueError("prediction_id и feedback_label обязательны")

    pred = conn.execute(
        """
        SELECT start_ts, end_ts, top_label
        FROM ml_predictions
        WHERE id=? AND position_name=?
        """,
        (prediction_id, position_name),
    ).fetchone()
    if not pred:
        raise LookupError("Прогноз не найден")
    conn.execute(
        """
        INSERT INTO ml_feedback
            (prediction_id, position_name, feedback_label, corrected_label, note, reviewer)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            prediction_id,
            position_name,
            feedback_label,
            corrected_label,
            note,
            reviewer,
        ),
    )
    if feedback_label in {"confirmed", "corrected"} or corrected_label:
        final_label = corrected_label or str(pred["top_label"] or "")
        if final_label:
            conn.execute(
                """
                INSERT INTO ml_event_tags
                    (position_name, start_ts, end_ts, label, tag, description, status, validated_by, validated_at, meta_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 'validated', ?, CURRENT_TIMESTAMP, '{}', CURRENT_TIMESTAMP)
                """,
                (
                    position_name,
                    str(pred["start_ts"] or ""),
                    str(pred["end_ts"] or ""),
                    final_label,
                    final_label,
                    f"auto-from-feedback:{prediction_id}",
                    reviewer,
                ),
            )
    retrain_recommended, validated_count = ml_compute_retrain_recommended(
        conn, position_name=position_name
    )
    conn.execute(
        """
        INSERT INTO ml_settings (key, value, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP
        """,
        (
            ml_setting_key(position_name, "retrain_recommended"),
            "1" if retrain_recommended else "0",
        ),
    )
    conn.commit()
    return {
        "ok": True,
        "retrain_recommended": retrain_recommended,
        "validated_samples": validated_count,
    }


def execute_ml_dataset_build_forecast(
    conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection,
    *,
    position_name: str,
    body: dict[str, object],
) -> dict[str, Any]:
    _ensure_ml_globals()
    start, end = _resolve_ml_time_range(
        str(body.get("start") or ""),
        str(body.get("end") or ""),
        default_delta=timedelta(days=7),
    )
    window_minutes = max(5, min(720, int(body.get("window_minutes") or 60)))
    unit_name = str(body.get("unit_name") or "").strip()
    frequency = str(body.get("frequency") or "").strip()
    group_code = str(body.get("group") or "").strip()
    group_query = str(body.get("group_query") or "").strip()
    horizons = [30, 60, 120]

    scope_pairs = ml_parse_scope_pairs(
        conn,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
    )
    rows = collect_seans_rows(
        seans_conn,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        position_name=position_name,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
    )
    tag_rows = conn.execute(
        """
        SELECT start_ts, end_ts, label
        FROM ml_event_tags
        WHERE position_name=? AND status='validated'
        ORDER BY start_ts ASC
        """,
        (position_name,),
    ).fetchall()
    tags = [
        (str(r["start_ts"] or ""), str(r["end_ts"] or ""), str(r["label"] or ""))
        for r in (tag_rows or [])
    ]
    forecast_samples = ml_build_forecast_samples(
        rows,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        window_minutes=window_minutes,
        tag_rows=tags,
        horizons=horizons,
    )
    conn.execute(
        """
        DELETE FROM ml_feature_snapshots
        WHERE position_name=? AND source='forecast-dataset' AND start_ts>=? AND end_ts<=? AND window_minutes=?
        """,
        (position_name, fmt_analysis_dt(start), fmt_analysis_dt(end), window_minutes),
    )
    inserted = 0
    by_h: dict[str, int] = {}
    for h in horizons:
        items = forecast_samples.get(h) or []
        by_h[str(h)] = len(items)
        for snap, lbl in items:
            conn.execute(
                """
                INSERT INTO ml_feature_snapshots
                    (position_name, start_ts, end_ts, window_minutes, feature_json, label, tag, source)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'forecast-dataset')
                """,
                (
                    position_name,
                    snap.start,
                    snap.end,
                    window_minutes,
                    json.dumps(
                        {
                            "features": snap.features,
                            "top_units": snap.top_units,
                            "top_groups": snap.top_groups,
                            "top_ids": snap.top_ids,
                            "horizon_minutes": int(h),
                        },
                        ensure_ascii=False,
                    ),
                    str(lbl),
                    f"h{int(h)}:{str(lbl)}",
                ),
            )
            inserted += 1
    conn.commit()
    return {
        "ok": True,
        "inserted": inserted,
        "by_horizon": by_h,
        "window_minutes": window_minutes,
        "horizons": horizons,
        "start": fmt_analysis_dt(start),
        "end": fmt_analysis_dt(end),
    }


def execute_ml_train_forecast(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    body: dict[str, object],
    activated_at: str,
) -> dict[str, Any]:
    _ensure_ml_globals()
    epochs = int(body.get("epochs") or 60)
    lr = float(body.get("lr") or 0.001)
    activate = bool(body.get("activate", True))
    val_split = str(body.get("val_split") or "stratified").strip().lower()
    if val_split not in ("stratified", "time"):
        val_split = "stratified"
    try:
        val_size = float(body.get("val_size") or 0.2)
    except (TypeError, ValueError):
        val_size = 0.2
    val_size = min(max(0.05, val_size), 0.5)
    try:
        random_seed = int(body.get("random_seed") or 42)
    except (TypeError, ValueError):
        random_seed = 42
    try:
        weight_decay = float(body.get("weight_decay") or 0.0)
    except (TypeError, ValueError):
        weight_decay = 0.0
    weight_decay = min(max(0.0, weight_decay), 0.1)
    horizons = [30, 60, 120]

    trained: list[dict[str, object]] = []
    for h in horizons:
        rows = conn.execute(
            """
            SELECT feature_json, label
            FROM ml_feature_snapshots
            WHERE position_name=? AND source='forecast-dataset' AND label<>''
            ORDER BY end_ts ASC
            """,
            (position_name,),
        ).fetchall()
        x: list[list[float]] = []
        y: list[str] = []
        for r in rows or []:
            try:
                pj = json.loads(str(r["feature_json"] or "{}"))
                if int(pj.get("horizon_minutes") or 0) != int(h):
                    continue
                x.append(ml_vectorize_feature_dict(pj.get("features") or {}))
                y.append(str(r["label"] or ""))
            except Exception:
                continue
        if len(x) < 8 or len(set(y)) < 2:
            continue
        run_id = f"run-fc-{h}-{int(time.time())}"
        model_version = ml_new_model_version()
        train_res = ml_train_multiclass(
            x,
            y,
            epochs=epochs,
            lr=lr,
            weight_decay=weight_decay,
            val_split=val_split,
            val_size=val_size,
            random_seed=random_seed + int(h),
        )
        artifact = ml_artifact_path_for(model_version)
        ml_save_checkpoint(
            str(artifact),
            {
                "state_dict": train_res.state_dict,
                "labels": train_res.labels,
                "feature_order": FEATURE_ORDER,
                "mean": train_res.mean,
                "std": train_res.std,
                "metrics": train_res.metrics,
            },
        )
        task_type = f"forecast_h{int(h)}"
        activate_this = bool(activate)
        if activate_this:
            active_same_task = conn.execute(
                """
                SELECT metrics_json
                FROM ml_models
                WHERE is_active=1 AND task_type=?
                ORDER BY id DESC
                LIMIT 1
                """,
                (task_type,),
            ).fetchone()
            if active_same_task:
                old_m = json.loads(str(active_same_task["metrics_json"] or "{}"))
                old_f1 = float(old_m.get("val_f1_macro") or 0.0)
                new_f1 = float(train_res.metrics.get("val_f1_macro") or 0.0)
                if new_f1 + 0.05 < old_f1:
                    activate_this = False
        if activate_this:
            conn.execute(
                "UPDATE ml_models SET is_active=0 WHERE task_type=?",
                (task_type,),
            )
        conn.execute(
            """
            INSERT INTO ml_models
                (model_version, framework, task_type, labels_json, feature_spec_json, metrics_json, artifact_path, is_active, activated_at)
            VALUES (?, 'pytorch', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                model_version,
                task_type,
                json.dumps(train_res.labels, ensure_ascii=False),
                json.dumps(
                    {"feature_order": FEATURE_ORDER, "horizon_minutes": int(h)},
                    ensure_ascii=False,
                ),
                json.dumps(train_res.metrics, ensure_ascii=False),
                str(artifact),
                1 if activate_this else 0,
                activated_at if activate_this else "",
            ),
        )
        conn.execute(
            """
            INSERT INTO ml_training_runs (run_id, model_version, status, params_json, metrics_json, ended_at)
            VALUES (?, ?, 'done', ?, ?, CURRENT_TIMESTAMP)
            """,
            (
                run_id,
                model_version,
                json.dumps(
                    {
                        "epochs": epochs,
                        "lr": lr,
                        "task_type": task_type,
                        "val_split": val_split,
                        "val_size": val_size,
                        "random_seed": random_seed,
                        "weight_decay": weight_decay,
                    },
                    ensure_ascii=False,
                ),
                json.dumps(train_res.metrics, ensure_ascii=False),
            ),
        )
        trained.append(
            {
                "horizon": int(h),
                "model_version": model_version,
                "metrics": train_res.metrics,
                "active": activate_this,
            }
        )
    if not trained:
        raise RuntimeError(
            "Недостаточно данных для forecast-train (нужны метки и минимум 2 класса по каждому горизонту)."
        )
    conn.commit()
    return {"ok": True, "trained": trained, "active": activate}


def execute_ml_predict_forecast(
    conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection,
    *,
    position_name: str,
    body: dict[str, object],
) -> dict[str, Any]:
    _ensure_ml_globals()
    unit_name = str(body.get("unit_name") or "").strip()
    frequency = str(body.get("frequency") or "").strip()
    group_code = str(body.get("group") or "").strip()
    group_query = str(body.get("group_query") or "").strip()
    start = parse_analysis_datetime(str(body.get("start") or ""))
    end = parse_analysis_datetime(str(body.get("end") or ""))
    window_minutes = max(5, min(720, int(body.get("window_minutes") or 60)))
    if not start or not end or end <= start:
        end = msk_now_naive()
        start = end - timedelta(minutes=window_minutes)

    scope_pairs = ml_parse_scope_pairs(
        conn,
        unit_name=unit_name,
        frequency=frequency,
        group_code=group_code,
    )
    rows = collect_seans_rows(
        seans_conn,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        position_name=position_name,
        scope_pairs=scope_pairs or None,
        group_query=group_query or None,
    )
    snapshots = ml_build_snapshots(
        rows,
        start_s=fmt_analysis_dt(start),
        end_s=fmt_analysis_dt(end),
        window_minutes=window_minutes,
    )
    if not snapshots:
        raise RuntimeError("Нет данных для forecast-прогноза")
    snap = snapshots[-1]
    vec = ml_vectorize_feature_dict(snap.features)
    out: dict[str, object] = {}
    ready = 0
    source = "forecast_models"
    base_model = ml_get_active_model_for_task(conn, task_type="multiclass_event")
    base_pred = (
        ml_predict_probabilities(str(base_model["artifact_path"] or ""), vec)
        if base_model
        else {"top": {"label": "none", "probability": 0.0}, "probabilities": []}
    )
    for h in (30, 60, 120):
        task = f"forecast_h{h}"
        m = ml_get_active_model_for_task(conn, task_type=task)
        if not m:
            top = base_pred.get("top") or {"label": "none", "probability": 0.0}
            probs = base_pred.get("probabilities") or []
            out[str(h)] = {
                "top1": {
                    "label": str(top.get("label") or "none"),
                    "probability": float(top.get("probability") or 0.0),
                },
                "all_probs": probs,
                "model_version": str(
                    (base_model["model_version"] if base_model else "") or ""
                ),
                "is_fallback": True,
            }
            source = "fallback_nowcast"
            continue
        pred = ml_predict_probabilities(str(m["artifact_path"] or ""), vec)
        probs = pred.get("probabilities") or []
        top = pred.get("top") or {"label": "none", "probability": 0.0}
        out[str(h)] = {
            "top1": {
                "label": str(top.get("label") or "none"),
                "probability": float(top.get("probability") or 0.0),
            },
            "all_probs": probs,
            "model_version": str(m["model_version"] or ""),
            "is_fallback": False,
        }
        ready += 1
    rel = "low"
    if ready >= 3:
        rel = "high"
    elif ready >= 1:
        rel = "medium"
    return {
        "ok": True,
        "forecast": {"horizons": out, "reliability": rel, "source": source},
    }
