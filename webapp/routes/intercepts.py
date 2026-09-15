"""Перехваты (/intercepts, /api/intercepts/*, audio, ASR), извлечено из app.py дословно.

Общая job-машинерия create_app (submit/record-хелперы) передаётся параметрами.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path

from flask import jsonify, render_template, request, send_file, url_for
from flask_login import current_user, login_required

from web_portal.app_perf import perf_route as _perf_route
from web_portal.app_runtime_caches import (
    assignments_cache_invalidate as _assignments_cache_invalidate,
    audio_listening_snapshot as _audio_listening_snapshot,
    audio_listening_start as _audio_listening_start,
    audio_listening_stop as _audio_listening_stop,
    audio_listening_token_client,
    audio_listening_token_username,
    callsigns_cache_invalidate as _callsigns_cache_invalidate,
    intercept_item_live_wait as _intercept_item_live_wait,
    intercepts_state_cache_clear as _intercepts_state_cache_clear,
    intercepts_state_cache_get as _intercepts_state_cache_get,
    intercepts_state_cache_set as _intercepts_state_cache_set,
    units_tree_cache_invalidate as _units_tree_cache_invalidate,
)
from web_portal.application.intercepts import (
    AUDIO_GLOBAL_POS,
    InterceptsGate,
    InterceptsUseCaseHTTP,
    assemble_intercepts_day_blank_payload,
    assemble_intercepts_get_item_payload,
    assemble_intercepts_state_payload,
    build_intercepts_audio_list_payload,
    build_intercepts_export_docx_file,
    execute_intercepts_ai_proofread,
    execute_intercepts_callsign_delete,
    execute_intercepts_callsign_update_label,
    execute_intercepts_callsign_upsert,
    execute_intercepts_callsigns_last_seen,
    execute_intercepts_catalog_archive_toggle,
    execute_intercepts_catalog_delete,
    execute_intercepts_catalog_delete_unit,
    execute_intercepts_catalog_favorite_toggle,
    execute_intercepts_catalog_rename_unit,
    execute_intercepts_catalog_update_location,
    execute_intercepts_catalog_upsert,
    execute_intercepts_item_update,
    execute_intercepts_session_start_new,
    execute_intercepts_set_unit_order,
    execute_intercepts_set_view_mode,
    execute_intercepts_typing,
    load_intercept_catalog_prefs_for_user,
    parse_intercepts_audio_list_params,
    sync_intercepts_audio_tasks_from_arm_task,
)
from web_portal.application.intercepts.state_sig import (
    attach_intercepts_state_sig,
    compute_intercept_item_content_sig,
    normalize_intercept_item_content_sig,
)
from web_portal.config import DEFAULT_DB_NAME, db_path, portal_db_path, search_online_db_path
from web_portal.lib.auth_db import (
    connect_portal,
    get_asr_training_policy,
    get_user_intercept_unit_order,
    get_user_intercept_view_mode,
)
from web_portal.lib.db import (
    activate_asr_model,
    add_asr_feedback,
    add_asr_train_sample,
    add_intercept_audio_task,
    connect,
    count_asr_feedback,
    create_asr_training_run,
    delete_intercept_audio_task,
    ensure_db,
    finish_asr_training_run,
    get_active_asr_model,
    get_asr_settings,
    get_intercept_audio_state,
    get_intercept_audio_transcript,
    list_asr_models,
    list_asr_train_samples,
    list_intercept_audio_tasks,
    list_intercept_callsigns,
    list_intercept_catalog,
    list_online_search_unit_avatar_files,
    list_online_search_unit_families,
    mark_intercept_audio_listened,
    search_intercept_items,
    set_asr_settings,
    set_intercept_audio_task_active,
    update_ai_job,
    upsert_asr_model,
    upsert_intercept_audio_state,
    upsert_intercept_audio_transcript,
)
from web_portal.lib.flask_db import get_request_main_db, get_request_portal_db
from web_portal.lib.intercept_audio_bundle import (
    probe_bundle_layout,
)
from web_portal.lib.safe_paths import (
    probe_audio_file as _probe_audio_file,
    probe_path as _probe_path,
)
from web_portal.positions import (
    current_user_position_role,
    get_selected_position,
    require_position_role,
)
from web_portal.webapp.auth import require_tab
from web_portal.webapp.context import AppContext
from web_portal.application.online_search.media_urls import (
    collect_family_unit_keys,
    lookup_unit_avatar_url,
    resolve_unit_avatar_urls,
)

_log = logging.getLogger("web_portal.webapp.routes.intercepts")


def _attach_intercept_catalog_avatars(catalog: list) -> list:
    """Подставляет avatar_url из онлайн-поиска (фото группы → дочерние unit_name)."""
    rows = [c for c in (catalog or []) if isinstance(c, dict)]
    unit_keys = sorted(
        {
            str(c.get("unit_name") or "").strip()
            for c in rows
            if str(c.get("unit_name") or "").strip()
        }
    )
    if not unit_keys:
        for c in rows:
            c.setdefault("avatar_url", "")
        return catalog
    try:
        search_p = search_online_db_path()
        ensure_db(search_p)
        search_conn = connect(search_p)
        try:
            families = list_online_search_unit_families(search_conn)
            avatar_keys = sorted(set(unit_keys) | set(collect_family_unit_keys(families)))
            avatar_files = list_online_search_unit_avatar_files(search_conn, avatar_keys)
            avatar_map = resolve_unit_avatar_urls(
                families,
                avatar_files,
                build_url=lambda filename: url_for(
                    "api_online_search_unit_avatar_file",
                    filename=filename,
                ),
            )
        finally:
            search_conn.close()
    except Exception:
        _log.debug("attach intercept catalog avatars failed", exc_info=True)
        avatar_map = {}
    for c in rows:
        c["avatar_url"] = lookup_unit_avatar_url(
            avatar_map, str(c.get("unit_name") or "")
        )
    return catalog




def _missing_optional(dep: str):
    def _raise(*_args, **_kwargs):
        raise RuntimeError(f"Опциональная зависимость '{dep}' недоступна в этой сборке")

    return _raise


try:
    from web_portal.lib.asr.dataset import (
        build_supervised_samples as asr_build_supervised_samples,
    )
    from web_portal.lib.asr.infer import (
        make_group_transcript_key,
        transcribe_audio_to_operator_ru,
        transcribe_track_segments_to_operator_blank,
    )
    from web_portal.lib.asr.learn_from_blank import learn_from_operator_blank
    from web_portal.lib.asr.runtime import asr_runtime
    from web_portal.lib.asr.train import train_whisper_adaptation
except Exception:
    _log.debug("ASR optional deps unavailable", exc_info=True)
    asr_build_supervised_samples = _missing_optional("ASR")
    transcribe_audio_to_operator_ru = _missing_optional("ASR")
    transcribe_track_segments_to_operator_blank = _missing_optional("ASR")
    make_group_transcript_key = _missing_optional("ASR")
    learn_from_operator_blank = _missing_optional("ASR")
    asr_runtime = None
    train_whisper_adaptation = _missing_optional("ASR")


def register_intercepts_routes(app, ctx: AppContext):
    """Регистрирует маршруты перехватов через AppContext. Код перенесён из create_app дословно."""
    logger = _log

    def _schedule_hub_sync_push_bg() -> None:
        """Только срочный outbox (бланки/смены). Bulk — в run_sync_loop."""
        try:
            from web_portal.lib.sync_agent import sync_push_priority_once  # noqa: E402

            def _push_bg():
                upstream = app.config.get("SYNC_UPSTREAM") or ""
                key = app.config.get("SYNC_KEY") or ""
                positions = app.config.get("SYNC_POSITIONS") or []
                try:
                    sync_push_priority_once(
                        upstream_base=upstream,
                        sync_key=key,
                        position_names=positions,
                    )
                except Exception:
                    _log.debug("_push_bg: suppressed error", exc_info=True)

            threading.Thread(target=_push_bg, daemon=True, name="sync-push-priority").start()
        except Exception:
            _log.debug("_schedule_hub_sync_push_bg: suppressed error", exc_info=True)

    TYPING: dict[tuple[str, int, int], dict[str, dict]] = {}

    def _typing_cleanup(now_ts: float, ttl_sec: float = 6.0) -> None:
        dead_keys: list[tuple[str, int, int]] = []
        for k, m in list(TYPING.items()):
            mm: dict[str, dict] = {}
            for u, v in (m or {}).items():
                try:
                    ts = float((v or {}).get("ts") or 0.0)
                except Exception:
                    ts = 0.0
                if (now_ts - ts) <= ttl_sec:
                    mm[str(u)] = {
                        "ts": ts,
                        "time_header": str((v or {}).get("time_header") or "").strip(),
                    }
            if mm:
                TYPING[k] = mm
            else:
                dead_keys.append(k)
        for k in dead_keys:
            TYPING.pop(k, None)

    def _typing_users(
        position_name: str, session_id: int, catalog_id: int, exclude: str | None = None
    ) -> list[str]:
        import time as _time

        now_ts = float(_time.time())
        _typing_cleanup(now_ts)
        key = (str(position_name or "").strip(), int(session_id), int(catalog_id))
        m = TYPING.get(key, {}) or {}
        out = []
        for u in sorted(m.keys()):
            if exclude and u == exclude:
                continue
            th = ""
            try:
                th = str((m.get(u) or {}).get("time_header") or "").strip()
            except Exception:
                th = ""
            out.append(f"{u} ({th})" if th else str(u))
        return out

    @app.get("/intercepts")
    @login_required
    @require_tab("tab_intercepts")
    def intercepts():
        return render_template(
            "intercepts.html", page_mode="intercepts", show_audio=False
        )

    @app.get("/api/intercepts/asr/training-policy")
    @login_required
    def api_intercepts_asr_training_policy():
        """Политика обучения ASR для UI оператора (только чтение)."""
        conn = connect_portal(portal_db_path())
        try:
            policy = get_asr_training_policy(conn)
            return jsonify({"ok": True, "policy": policy})
        finally:
            conn.close()

    @app.get("/api/intercepts/state")
    @_perf_route("api/intercepts/state")
    @login_required
    def api_intercepts_state():
        pos = get_selected_position()
        requested_sid = request.args.get("session_id", 0, type=int)
        explicit_pick = str(request.args.get("explicit_pick") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        req_freq = str(request.args.get("frequency") or "").strip()
        req_group = str(request.args.get("group_code") or "").strip()
        client_state_sig = str(request.args.get("state_sig") or "").strip()
        skip_catalog = str(request.args.get("skip_catalog") or "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        view_mode = "pretty"
        unit_order: list[str] = []
        catalog_prefs: dict = {"favorites": [], "archived": []}
        try:
            pconn = get_request_portal_db()
            view_mode = get_user_intercept_view_mode(
                pconn, user_id=int(current_user.id)
            )
            unit_order = get_user_intercept_unit_order(
                pconn, user_id=int(current_user.id)
            )
            catalog_prefs = load_intercept_catalog_prefs_for_user(
                pconn, user_id=int(current_user.id)
            )
        except Exception:
            view_mode = "pretty"
            unit_order = []
            catalog_prefs = {"favorites": [], "archived": []}

        def _merge_user_ui_fields(payload: dict) -> dict:
            out = dict(payload)
            out["view_mode"] = view_mode
            out["unit_order"] = unit_order
            out["catalog_prefs"] = catalog_prefs
            return attach_intercepts_state_sig(out)

        def _respond_state(payload: dict):
            merged = _merge_user_ui_fields(payload)
            if isinstance(merged.get("catalog"), list):
                _attach_intercept_catalog_avatars(merged["catalog"])
            if skip_catalog:
                merged = dict(merged)
                merged.pop("catalog", None)
                merged.pop("callsigns", None)
                merged["catalog_omitted"] = True
            sig = str(merged.get("state_sig") or "")
            if client_state_sig and sig and client_state_sig == sig:
                return jsonify({"ok": True, "unchanged": True, "state_sig": sig})
            return jsonify(merged)

        if current_user.role == "admin" and not pos:
            return _respond_state(
                {
                    "ok": True,
                    "position": None,
                    "catalog": [],
                    "sessions": [],
                }
            )
        if not pos:
            return _respond_state(
                {
                    "ok": True,
                    "position": None,
                    "catalog": [],
                    "sessions": [],
                }
            )
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет доступа к позиции"}), 403

        role = current_user_position_role(pos) or "operator"
        cache_key = (
            f"u={int(getattr(current_user, 'id', 0) or 0)}|"
            f"pos={pos}|sid={requested_sid}|f={req_freq}|g={req_group}"
            f"|ep={1 if explicit_pick else 0}"
        )
        cached_payload = _intercepts_state_cache_get(cache_key)
        if cached_payload is not None:
            return _respond_state(cached_payload)

        conn = get_request_main_db()
        gate = InterceptsGate(
            permit_edit=require_position_role(pos, "edit"),
            permit_export=require_position_role(pos, "export"),
            permit_start=require_position_role(pos, "start"),
        )
        payload = assemble_intercepts_state_payload(
            conn,
            position_name=pos,
            username=str(getattr(current_user, "username", "") or ""),
            role=role,
            requested_sid=requested_sid,
            explicit_pick=explicit_pick,
            req_freq=req_freq,
            req_group=req_group,
            view_mode=view_mode,
            unit_order=unit_order,
            catalog_prefs=catalog_prefs,
            gate=gate,
        )
        _intercepts_state_cache_set(cache_key, payload)
        return _respond_state(payload)

    @app.get("/api/intercepts/catalog")
    @_perf_route("api/intercepts/catalog")
    @login_required
    def api_intercepts_catalog():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": True, "catalog": [], "callsigns": []})
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет доступа к позиции"}), 403
        conn = get_request_main_db()
        catalog = list_intercept_catalog(conn, pos) or []
        _attach_intercept_catalog_avatars(catalog)
        callsigns = list_intercept_callsigns(conn, pos) or []
        cat_max = ""
        for c in catalog:
            v = str((c or {}).get("updated_at") or "")
            if v > cat_max:
                cat_max = v
        cs_max = ""
        for c in callsigns:
            v = str((c or {}).get("updated_at") or "")
            if v > cs_max:
                cs_max = v
        catalog_sig = f"{len(catalog)}|{cat_max}|{len(callsigns)}|{cs_max}"
        client_sig = str(request.args.get("catalog_sig") or "").strip()
        if client_sig and client_sig == catalog_sig:
            return jsonify({"ok": True, "unchanged": True, "catalog_sig": catalog_sig})
        return jsonify(
            {
                "ok": True,
                "catalog": catalog,
                "callsigns": callsigns,
                "catalog_sig": catalog_sig,
            }
        )

    def _maybe_sync_arm_task_audio(
        conn: sqlite3.Connection,
    ) -> dict[str, object] | None:
        sync_result = None
        pos = get_selected_position()
        if pos and require_position_role(pos, "view"):
            try:
                sync_result = sync_intercepts_audio_tasks_from_arm_task(
                    conn,
                    position_name=pos,
                    created_by=str(getattr(current_user, "username", "") or ""),
                )
            except Exception as e:
                logger.exception("ArmTask audio auto-sync failed")
                sync_result = {"ok": False, "error": str(e), "active_count": 0}
        return sync_result

    @app.get("/api/intercepts/audio/tasks")
    @login_required
    def api_intercepts_audio_tasks():
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            sync_result = _maybe_sync_arm_task_audio(conn)
            # Задания поста общие по хабу: используем глобальный ключ.
            tasks = list_intercept_audio_tasks(conn, AUDIO_GLOBAL_POS)
            return jsonify({"ok": True, "tasks": tasks, "arm_task_sync": sync_result})
        finally:
            conn.close()

    @app.post("/api/intercepts/audio/tasks")
    @login_required
    def api_intercepts_audio_tasks_add():
        data = request.get_json(silent=True) or {}
        freq = str(data.get("frequency") or "").strip()
        unit_name = str(data.get("unit_name") or "").strip()
        if not freq:
            return (
                jsonify({"ok": False, "error": "frequency обязательна"}),
                400,
            )
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            tid = add_intercept_audio_task(
                conn,
                # Храним задания поста глобально для хаба, а не по позициям.
                position_name=AUDIO_GLOBAL_POS,
                frequency=freq,
                unit_name=unit_name,
                created_by=str(getattr(current_user, "username", "") or ""),
            )
            return jsonify({"ok": True, "id": tid})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.post("/api/intercepts/audio/tasks/delete")
    @login_required
    def api_intercepts_audio_tasks_delete():
        data = request.get_json(silent=True) or {}
        tid = int(data.get("id") or 0)
        if not tid:
            return jsonify({"ok": False, "error": "id обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            deleted = delete_intercept_audio_task(
                conn, position_name=AUDIO_GLOBAL_POS, task_id=tid
            )
            return jsonify({"ok": True, "deleted": bool(deleted)})
        finally:
            conn.close()

    @app.get("/api/intercepts/audio/state")
    @login_required
    def api_intercepts_audio_state_get():
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            # Состояние аудиопанели общее по хабу (глобальный ключ).
            state = get_intercept_audio_state(conn, position_name=AUDIO_GLOBAL_POS)
            return jsonify({"ok": True, "state": state})
        finally:
            conn.close()

    @app.post("/api/intercepts/audio/state")
    @login_required
    def api_intercepts_audio_state_set():
        data = request.get_json(silent=True) or {}
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            current = get_intercept_audio_state(conn, position_name=AUDIO_GLOBAL_POS)
            # Управление сканером (путь к папке на сервере, фильтр, запуск) —
            # только для ролей с правом редактирования или админа.
            # Пользовательские поля (last_time_ts, layout_mode) доступны всем.
            _sel_pos = get_selected_position() or ""
            can_manage = bool(
                getattr(current_user, "role", "") == "admin"
                or (_sel_pos and require_position_role(_sel_pos, "edit"))
            )
            if can_manage:
                folder_path = str(data.get("folder_path") or current["folder_path"] or "")
            else:
                folder_path = str(current["folder_path"] or "")
            tasks_only = data.get("tasks_only") if can_manage else None
            if tasks_only is None:
                tasks_only = current["tasks_only"]
            else:
                tasks_only = bool(tasks_only)
            last_time_ts = data.get("last_time_ts")
            if last_time_ts is None:
                last_time_ts = current["last_time_ts"]
            else:
                try:
                    last_time_ts = float(last_time_ts or 0.0)
                except Exception:
                    last_time_ts = current["last_time_ts"]
            is_running = data.get("is_running") if can_manage else None
            if is_running is None:
                is_running = current["is_running"]
            else:
                is_running = bool(is_running)
            layout_mode = data.get("layout_mode")
            if layout_mode is None:
                layout_mode = current.get("layout_mode") or "dmr"
            else:
                layout_mode = (
                    "bundle"
                    if str(layout_mode or "").strip().lower() == "bundle"
                    else "dmr"
                )
            upsert_intercept_audio_state(
                conn,
                # Сохраняем настройки для глобального ключа.
                position_name=AUDIO_GLOBAL_POS,
                folder_path=folder_path,
                tasks_only=tasks_only,
                last_time_ts=last_time_ts,
                is_running=is_running,
                layout_mode=layout_mode,
            )
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/intercepts/audio/tasks/active")
    @login_required
    def api_intercepts_audio_tasks_active():
        data = request.get_json(silent=True) or {}
        tid = int(data.get("id") or 0)
        is_active = str(data.get("is_active") or "").lower() in {
            "1",
            "true",
            "yes",
        }
        if not tid:
            return jsonify({"ok": False, "error": "id обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            updated = set_intercept_audio_task_active(
                # Активность задания тоже общая для хаба.
                conn,
                position_name=AUDIO_GLOBAL_POS,
                task_id=tid,
                is_active=is_active,
            )
            return jsonify(
                {"ok": True, "updated": bool(updated), "is_active": is_active}
            )
        finally:
            conn.close()

    @app.get("/api/intercepts/audio/list")
    @login_required
    def api_intercepts_audio_list():
        params = parse_intercepts_audio_list_params(
            request.args,
            current_username=str(getattr(current_user, "username", "") or ""),
        )
        if not params.folder_paths:
            return jsonify({"ok": False, "error": "folder_path обязателен"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            sync_result = _maybe_sync_arm_task_audio(conn)
            payload = build_intercepts_audio_list_payload(
                conn,
                params=params,
                arm_task_sync=sync_result,
                listening_snapshot=_audio_listening_snapshot(),
                listening_token_username=audio_listening_token_username,
                listening_token_client=audio_listening_token_client,
                probe_path_fn=_probe_path,
            )
            return jsonify(payload)
        finally:
            conn.close()

    @app.get("/api/intercepts/audio/file")
    @login_required
    def api_intercepts_audio_file():
        folder_path = str(request.args.get("folder_path") or "").strip()
        file_rel = str(request.args.get("file_rel") or "").strip()
        if not folder_path or not file_rel:
            return (
                jsonify({"ok": False, "error": "folder_path и file_rel обязательны"}),
                400,
            )
        probe = _probe_audio_file(folder_path, file_rel)
        if probe.timed_out:
            return (
                jsonify({"ok": False, "error": probe.error or "Таймаут доступа к файлу"}),
                504,
            )
        if not probe.ok:
            return jsonify({"ok": False, "error": probe.error or "Недопустимый путь"}), 400
        if not probe.exists or not probe.is_file:
            return jsonify({"ok": False, "error": "Файл не найден"}), 404
        try:
            return send_file(
                probe.resolved,
                mimetype="audio/wav",
                as_attachment=False,
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.get("/api/intercepts/audio/check-path")
    @login_required
    def api_intercepts_audio_check_path():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        folder_path = str(request.args.get("folder_path") or "").strip()
        if not folder_path:
            return jsonify({"ok": False, "error": "folder_path обязателен"}), 400
        probe = _probe_path(folder_path)
        if probe.timed_out:
            return jsonify(
                {
                    "ok": True,
                    "exists": False,
                    "is_dir": False,
                    "timed_out": True,
                    "path": str(folder_path),
                    "error": probe.error,
                }
            )
        layout_hint = "dmr"
        if probe.ok and probe.exists and probe.is_dir:
            try:
                layout_hint = (
                    "bundle"
                    if probe_bundle_layout(Path(probe.resolved or folder_path))
                    else "dmr"
                )
            except Exception:
                layout_hint = "dmr"
        return jsonify(
            {
                "ok": True,
                "exists": bool(probe.exists),
                "is_dir": bool(probe.is_dir),
                "timed_out": False,
                "path": probe.resolved or str(folder_path),
                "layout_hint": layout_hint,
            }
        )

    @app.post("/api/intercepts/audio/mark-listened")
    @login_required
    def api_intercepts_audio_mark_listened():
        data = request.get_json(silent=True) or {}
        key = str(data.get("file_key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": "file_key обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            mark_intercept_audio_listened(conn, int(current_user.id), key)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/intercepts/audio/listening/start")
    @login_required
    def api_intercepts_audio_listening_start():
        data = request.get_json(silent=True) or {}
        key = str(data.get("file_key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": "file_key обязателен"}), 400
        _audio_listening_start(
            key,
            str(getattr(current_user, "username", "") or ""),
            str(data.get("client_id") or "").strip(),
        )
        return jsonify({"ok": True})

    @app.post("/api/intercepts/audio/listening/stop")
    @login_required
    def api_intercepts_audio_listening_stop():
        data = request.get_json(silent=True) or {}
        key = str(data.get("file_key") or "").strip()
        if not key:
            return jsonify({"ok": False, "error": "file_key обязателен"}), 400
        _audio_listening_stop(
            key,
            str(getattr(current_user, "username", "") or ""),
            str(data.get("client_id") or "").strip(),
        )
        return jsonify({"ok": True})

    @app.get("/api/intercepts/audio/listening")
    @login_required
    def api_intercepts_audio_listening():
        """Лёгкий снимок «кто сейчас слушает» без повторного сканирования папки."""
        from web_portal.app_runtime_caches import (
            audio_listening_token_client,
            audio_listening_token_username,
        )

        current_name = str(getattr(current_user, "username", "") or "")
        client_id = str(request.args.get("client_id") or "").strip()
        snap = _audio_listening_snapshot()
        listening: dict[str, list[str]] = {}
        for file_key, tokens in (snap or {}).items():
            key = str(file_key or "").strip()
            if not key:
                continue
            others: list[str] = []
            for token in tokens or []:
                name = audio_listening_token_username(token).strip()
                if not name:
                    continue
                tok_client = audio_listening_token_client(token)
                # Исключаем только эту вкладку: одинаковый логин на другом
                # компьютере должен отображаться как «слушает».
                if name == current_name and (
                    (client_id and tok_client == client_id) or (not client_id and not tok_client)
                ):
                    continue
                if name not in others:
                    others.append(name)
            if others:
                listening[key] = others
        return jsonify({"ok": True, "listening": listening})

    def _resolve_audio_file_path(folder_path: str, file_rel: str) -> Path:
        base = Path(str(folder_path or "").strip()).resolve()
        rel = str(file_rel or "").strip()
        if not base or not rel:
            raise ValueError("folder_path и file_rel обязательны")
        file_path = (base / rel).resolve()
        if not str(file_path).lower().endswith(".wav"):
            raise ValueError("Поддерживается только .wav")
        if base not in file_path.parents and file_path != base:
            raise ValueError("Недопустимый путь")
        if not file_path.exists() or not file_path.is_file():
            raise FileNotFoundError("Файл не найден")
        return file_path

    @app.get("/api/intercepts/asr/settings")
    @login_required
    def api_intercepts_asr_settings_get():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            settings = get_asr_settings(conn, position_name=pos)
            return jsonify({"ok": True, "settings": settings})
        finally:
            conn.close()

    @app.post("/api/intercepts/asr/settings")
    @login_required
    def api_intercepts_asr_settings_set():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        payload = request.get_json(silent=True) or {}
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            current = get_asr_settings(conn, position_name=pos)
            merged = dict(current)
            merged.update(payload if isinstance(payload, dict) else {})
            settings = set_asr_settings(conn, position_name=pos, settings=merged)
            return jsonify({"ok": True, "settings": settings})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.post("/api/intercepts/asr/dataset-build")
    @login_required
    def api_intercepts_asr_dataset_build():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        payload = request.get_json(silent=True) or {}
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            settings = get_asr_settings(conn, position_name=pos)
            state = get_intercept_audio_state(conn, position_name=AUDIO_GLOBAL_POS)
            fp_raw = str(
                payload.get("folder_path") or state.get("folder_path") or ""
            ).strip()
            folder_paths = [x.strip() for x in fp_raw.splitlines() if x.strip()]
            if not folder_paths:
                return jsonify({"ok": False, "error": "Не задан путь к аудио"}), 400
            min_score = float(
                payload.get("min_alignment_score")
                or settings.get("min_alignment_score")
                or 0.35
            )
            limit_per_folder = int(payload.get("limit_per_folder") or 8000)
            tasks_only = bool(payload.get("tasks_only", state.get("tasks_only", False)))
        finally:
            conn.close()

        job_id = ctx.create_ai_job_record(
            task_type="asr_dataset_build",
            position_name=str(pos),
            params={
                "folder_paths": folder_paths,
                "min_alignment_score": min_score,
                "limit_per_folder": limit_per_folder,
                "tasks_only": tasks_only,
            },
            created_by=ctx.ai_created_by(),
        )

        def _run() -> None:
            bg_conn = connect(p)
            try:
                update_ai_job(bg_conn, job_id, status="running")
                out = asr_build_supervised_samples(
                    bg_conn,
                    position_name=pos,
                    folder_paths=folder_paths,
                    min_alignment_score=min_score,
                    limit_per_folder=limit_per_folder,
                    tasks_only=tasks_only,
                )
                update_ai_job(bg_conn, job_id, status="completed", result=out)
            except Exception as exc:
                update_ai_job(
                    bg_conn,
                    job_id,
                    status="failed",
                    error_text=str(exc),
                )
                raise
            finally:
                bg_conn.close()

        payload_out, status_code = ctx.submit_ai_job(job_id, "asr-dataset-build", _run)
        return jsonify(payload_out), status_code

    @app.post("/api/intercepts/asr/train")
    @login_required
    def api_intercepts_asr_train():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        payload = request.get_json(silent=True) or {}
        run_id = f"asr-run-{int(time.time())}"
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            settings = get_asr_settings(conn, position_name=pos)
            base_model = str(
                payload.get("base_model")
                or settings.get("whisper_model_name")
                or "openai/whisper-small"
            )
            activate = bool(
                payload.get("activate", settings.get("auto_activate", True))
            )
        finally:
            conn.close()
        job_id = ctx.create_ai_job_record(
            task_type="asr_train",
            position_name=str(pos),
            params={"run_id": run_id, "base_model": base_model, "activate": activate},
            created_by=ctx.ai_created_by(),
        )

        def _run() -> None:
            bg_conn = connect(p)
            try:
                update_ai_job(bg_conn, job_id, status="running")
                settings = get_asr_settings(bg_conn, position_name=pos)
                samples = list_asr_train_samples(
                    bg_conn, position_name=pos, status="validated", limit=200000
                )
                model_version_hint = str(payload.get("model_version") or "")
                create_asr_training_run(
                    bg_conn,
                    position_name=pos,
                    run_id=run_id,
                    model_version=model_version_hint or f"pending-{int(time.time())}",
                    params={
                        "base_model": base_model,
                        "samples": len(samples),
                        "activate": activate,
                    },
                )
                train_res = train_whisper_adaptation(
                    samples=samples,
                    base_model=base_model,
                    force_gpu=True,
                )
                model_version = str(train_res.get("model_version") or "")
                active_model_now = get_active_asr_model(bg_conn, position_name=pos)
                new_metrics = train_res.get("metrics") or {}
                allow_activate = bool(activate)
                activation_reason = "activated"
                if allow_activate and active_model_now:
                    old_metrics = active_model_now.get("metrics") or {}
                    old_wer = float(old_metrics.get("val_wer", 999.0))
                    new_wer = float(new_metrics.get("val_wer", 999.0))
                    if new_wer > (old_wer + 0.03):
                        allow_activate = False
                        activation_reason = "blocked_by_quality_gate"
                elif not allow_activate:
                    activation_reason = "saved_inactive_by_settings"
                upsert_asr_model(
                    bg_conn,
                    position_name=pos,
                    model_version=model_version,
                    base_model=base_model,
                    artifact_path=str(train_res.get("artifact_path") or ""),
                    metrics=train_res.get("metrics") or {},
                    is_active=allow_activate,
                )
                finish_asr_training_run(
                    bg_conn,
                    run_id=run_id,
                    status="done",
                    metrics=train_res.get("metrics") or {},
                )
                update_ai_job(
                    bg_conn,
                    job_id,
                    status="completed",
                    result={
                        "run_id": run_id,
                        "model_version": model_version,
                        "metrics": train_res.get("metrics") or {},
                        "mode": train_res.get("mode") or "",
                        "active": allow_activate,
                        "activation_reason": activation_reason,
                    },
                )
            except Exception as exc:
                try:
                    finish_asr_training_run(
                        bg_conn,
                        run_id=run_id,
                        status="error",
                        error_text=str(exc),
                    )
                except Exception:
                    _log.debug("_run: suppressed error", exc_info=True)
                update_ai_job(bg_conn, job_id, status="failed", error_text=str(exc))
                raise
            finally:
                bg_conn.close()

        payload_out, status_code = ctx.submit_ai_job(job_id, "asr-train", _run)
        payload_out["run_id"] = run_id
        return jsonify(payload_out), status_code

    @app.get("/api/intercepts/asr/model-status")
    @login_required
    def api_intercepts_asr_model_status():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            settings = get_asr_settings(conn, position_name=pos)
            active_model = get_active_asr_model(conn, position_name=pos)
            models = list_asr_models(conn, position_name=pos, limit=20)
            sample_count = int(
                (
                    conn.execute(
                        "SELECT COUNT(*) FROM asr_train_samples WHERE position_name=? AND status='validated'",
                        (pos,),
                    ).fetchone()[0]
                )
                or 0
            )
            fb_count = count_asr_feedback(conn, position_name=pos, status="validated")
            min_samples = int(settings.get("auto_retrain_min_samples") or 40)
            step = max(1, int(settings.get("auto_retrain_step") or 20))
            retrain_recommended = (
                bool(settings.get("auto_retrain"))
                and fb_count >= min_samples
                and ((fb_count - min_samples) % step == 0)
            )
            return jsonify(
                {
                    "ok": True,
                    "active_model": active_model,
                    "models": models,
                    "settings": settings,
                    "diagnostics": {
                        "validated_samples": sample_count,
                        "validated_feedback": fb_count,
                        "retrain_recommended": retrain_recommended,
                    },
                }
            )
        finally:
            conn.close()

    @app.post("/api/intercepts/asr/model-activate")
    @login_required
    def api_intercepts_asr_model_activate():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        payload = request.get_json(silent=True) or {}
        model_version = str(payload.get("model_version") or "").strip()
        if not model_version:
            return jsonify({"ok": False, "error": "model_version обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            ok = activate_asr_model(
                conn, position_name=pos, model_version=model_version
            )
            if not ok:
                return jsonify({"ok": False, "error": "Модель не найдена"}), 404
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/intercepts/asr/bootstrap")
    @login_required
    def api_intercepts_asr_bootstrap():
        if not asr_runtime:
            return jsonify({"ok": False, "error": "ASR модуль недоступен"}), 503
        status = dict(asr_runtime.bootstrap or {})
        settings_model = "small"
        pos = get_selected_position()
        if pos:
            p = db_path(DEFAULT_DB_NAME)
            ensure_db(p)
            conn = connect(p)
            try:
                settings = get_asr_settings(conn, position_name=pos)
                settings_model = str(settings.get("whisper_model_name") or "small")
            finally:
                conn.close()
        if not status.get("ready") and str(status.get("state") or "") in {
            "idle",
            "offline",
            "error",
        }:
            asr_runtime.schedule_bootstrap(settings_model)
        return jsonify({"ok": True, "bootstrap": status})

    @app.post("/api/intercepts/asr/transcribe")
    @login_required
    def api_intercepts_asr_transcribe():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        payload = request.get_json(silent=True) or {}
        mode = str(payload.get("mode") or "file").strip().lower()
        file_key = str(payload.get("file_key") or "").strip()
        folder_path = str(payload.get("folder_path") or "").strip()
        file_rel = str(payload.get("file_rel") or "").strip()
        force = bool(payload.get("force", False))
        group_key = str(payload.get("group_key") or "").strip()
        segments = payload.get("segments") if isinstance(payload.get("segments"), list) else []
        if mode == "group":
            if not group_key or not segments:
                return (
                    jsonify({"ok": False, "error": "group_key и segments обязательны"}),
                    400,
                )
            try:
                file_key = make_group_transcript_key(group_key)
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            if not folder_path:
                folder_path = str(payload.get("folder_path") or "").strip()
        elif not file_key:
            return jsonify({"ok": False, "error": "file_key обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            existing = get_intercept_audio_transcript(
                conn, position_name=pos, file_key=file_key
            )
            if existing and not force and str(existing.get("status") or "") == "done":
                return jsonify({"ok": True, "transcript": existing, "cached": True})
            if mode == "group":
                if not folder_path:
                    if existing:
                        folder_path = str(existing.get("folder_path") or "")
                    if not folder_path:
                        folder_path = str(
                            (segments[0] or {}).get("folder_path") or ""
                        ).strip()
                if not folder_path:
                    return (
                        jsonify({"ok": False, "error": "folder_path обязателен"}),
                        400,
                    )
                file_rel = str((segments[0] or {}).get("file_rel") or file_rel).strip()
                audio_file = None
            else:
                if not folder_path or not file_rel:
                    if existing:
                        folder_path = str(existing.get("folder_path") or "")
                        file_rel = str(existing.get("file_rel") or "")
                if not folder_path or not file_rel:
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": "folder_path и file_rel обязательны (или должны быть в сохраненной расшифровке)",
                            }
                        ),
                        400,
                    )
                try:
                    audio_file = _resolve_audio_file_path(folder_path, file_rel)
                except Exception as e:
                    upsert_intercept_audio_transcript(
                        conn,
                        position_name=pos,
                        file_key=file_key,
                        folder_path=folder_path,
                        file_rel=file_rel,
                        status="error",
                        error_text=str(e),
                    )
                    return jsonify({"ok": False, "error": str(e)}), 400

            settings = get_asr_settings(conn, position_name=pos)
            active_model = get_active_asr_model(conn, position_name=pos)
            model_name = str(
                (active_model.get("base_model") if active_model else "")
                or settings.get("whisper_model_name")
                or "small"
            )
            model_version = str(
                active_model.get("model_version") if active_model else ""
            )
            job_id = ctx.create_ai_job_record(
                task_type="asr_transcribe",
                position_name=str(pos),
                params={
                    "file_key": file_key,
                    "folder_path": folder_path,
                    "file_rel": file_rel,
                    "model_name": model_name,
                    "model_version": model_version,
                    "mode": mode,
                    "group_key": group_key,
                },
                created_by=ctx.ai_created_by(),
            )

            def _resolve_seg_path(rel: str) -> str:
                try:
                    return str(_resolve_audio_file_path(folder_path, rel))
                except Exception:
                    return ""

            def _run() -> None:
                bg_conn = connect(p)
                try:
                    update_ai_job(bg_conn, job_id, status="running")
                    if mode == "group":
                        result = transcribe_track_segments_to_operator_blank(
                            segments=segments,
                            resolve_audio_path=_resolve_seg_path,
                            model_name=model_name,
                            model_version=model_version,
                            recorded_at=str(payload.get("recorded_at") or ""),
                            frequency=str(payload.get("frequency") or ""),
                            group_code=str(payload.get("group_code") or ""),
                        )
                        first_rel = str(
                            (segments[0] or {}).get("file_rel") or ""
                        ).strip()
                    else:
                        result = transcribe_audio_to_operator_ru(
                            audio_file=str(audio_file),
                            model_name=model_name,
                            model_version=model_version,
                            correspondent_id=str(payload.get("correspondent_id") or ""),
                        )
                        first_rel = file_rel
                    upsert_intercept_audio_transcript(
                        bg_conn,
                        position_name=pos,
                        file_key=file_key,
                        folder_path=folder_path,
                        file_rel=first_rel or file_rel,
                        frequency=str(
                            payload.get("frequency") or result.get("frequency") or ""
                        ),
                        group_code=str(
                            payload.get("group_code") or result.get("group_code") or ""
                        ),
                        correspondent_id=str(payload.get("correspondent_id") or ""),
                        recorded_at=str(
                            payload.get("recorded_at") or result.get("recorded_at") or ""
                        ),
                        duration_sec=float(payload.get("duration_sec") or 0.0),
                        ua_text=str(result.get("ua_text") or ""),
                        ru_text=str(result.get("ru_text") or ""),
                        formatted_text=str(result.get("formatted_text") or ""),
                        segments_json=json.dumps(
                            result.get("segments") or [], ensure_ascii=False
                        ),
                        confidence=float(result.get("confidence") or 0.0),
                        model_version=str(result.get("model_version") or model_version),
                        status="done",
                    )
                    transcript = get_intercept_audio_transcript(
                        bg_conn, position_name=pos, file_key=file_key
                    )
                    update_ai_job(
                        bg_conn,
                        job_id,
                        status="completed",
                        result={"transcript": transcript, "cached": False},
                    )
                except Exception as exc:
                    upsert_intercept_audio_transcript(
                        bg_conn,
                        position_name=pos,
                        file_key=file_key,
                        folder_path=folder_path,
                        file_rel=file_rel,
                        status="error",
                        error_text=str(exc),
                    )
                    update_ai_job(bg_conn, job_id, status="failed", error_text=str(exc))
                    raise
                finally:
                    bg_conn.close()

            payload_out, status_code = ctx.submit_ai_job(job_id, "asr-transcribe", _run)
            return jsonify(payload_out), status_code
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.get("/api/intercepts/asr/transcript")
    @login_required
    def api_intercepts_asr_transcript():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        file_key = str(request.args.get("file_key") or "").strip()
        if not file_key:
            return jsonify({"ok": False, "error": "file_key обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            row = get_intercept_audio_transcript(
                conn, position_name=pos, file_key=file_key
            )
            if not row:
                return jsonify({"ok": True, "transcript": None})
            return jsonify({"ok": True, "transcript": row})
        finally:
            conn.close()

    @app.post("/api/intercepts/asr/feedback")
    @login_required
    def api_intercepts_asr_feedback():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        payload = request.get_json(silent=True) or {}
        file_key = str(payload.get("file_key") or "").strip()
        feedback_label = str(payload.get("feedback_label") or "").strip()
        corrected_text = str(payload.get("corrected_text") or "").strip()
        prediction_text = str(payload.get("prediction_text") or "").strip()
        if not file_key or not feedback_label:
            return (
                jsonify(
                    {"ok": False, "error": "file_key и feedback_label обязательны"}
                ),
                400,
            )
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            add_asr_feedback(
                conn,
                position_name=pos,
                file_key=file_key,
                prediction_text=prediction_text,
                corrected_text=corrected_text,
                feedback_label=feedback_label,
                reviewer=str(getattr(current_user, "username", "") or ""),
                status="validated",
            )
            tr = get_intercept_audio_transcript(
                conn, position_name=pos, file_key=file_key
            )
            portal_conn = connect_portal(portal_db_path())
            try:
                asr_policy = get_asr_training_policy(portal_conn)
            finally:
                portal_conn.close()
            if (
                asr_policy.get("training_enabled")
                and asr_policy.get("learn_on_feedback")
                and tr
                and corrected_text
            ):
                audio_path = str(
                    (
                        Path(str(tr.get("folder_path") or ""))
                        / str(tr.get("file_rel") or "")
                    ).resolve()
                )
                add_asr_train_sample(
                    conn,
                    position_name=pos,
                    file_key=file_key,
                    audio_path=audio_path,
                    start_ts=0.0,
                    end_ts=float(tr.get("duration_sec") or 0.0),
                    frequency=str(tr.get("frequency") or ""),
                    group_code=str(tr.get("group_code") or ""),
                    correspondent_id=str(tr.get("correspondent_id") or ""),
                    source_text=str(tr.get("ua_text") or ""),
                    target_text=corrected_text,
                    alignment_score=1.0,
                    status="validated",
                    meta_json=json.dumps(
                        {"source": "asr_feedback"}, ensure_ascii=False
                    ),
                )
            settings = get_asr_settings(conn, position_name=pos)
            fb_count = count_asr_feedback(conn, position_name=pos, status="validated")
            min_samples = int(settings.get("auto_retrain_min_samples") or 40)
            step = max(1, int(settings.get("auto_retrain_step") or 20))
            retrain_recommended = (
                bool(settings.get("auto_retrain"))
                and fb_count >= min_samples
                and ((fb_count - min_samples) % step == 0)
            )
            return jsonify(
                {
                    "ok": True,
                    "validated_feedback": fb_count,
                    "retrain_recommended": retrain_recommended,
                }
            )
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.post("/api/intercepts/asr/learn-from-blank")
    @login_required
    def api_intercepts_asr_learn_from_blank():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        portal_conn = connect_portal(portal_db_path())
        try:
            policy = get_asr_training_policy(portal_conn)
        finally:
            portal_conn.close()
        if not policy.get("training_enabled"):
            return (
                jsonify({"ok": False, "error": "Обучение ASR отключено администратором"}),
                403,
            )
        if not policy.get("learn_on_blank_send"):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "Сбор примеров при отправке в бланк отключён",
                    }
                ),
                403,
            )
        payload = request.get_json(silent=True) or {}
        operator_text = str(payload.get("operator_text") or "").strip()
        if not operator_text:
            return jsonify({"ok": False, "error": "operator_text обязателен"}), 400
        segments = payload.get("segments")
        if not isinstance(segments, list):
            segments = []
        folder_path = str(payload.get("folder_path") or "").strip()
        prediction_text = str(payload.get("prediction_text") or "").strip()
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            result = learn_from_operator_blank(
                conn,
                position_name=pos,
                operator_text=operator_text,
                prediction_text=prediction_text,
                folder_path=folder_path,
                segments=segments,
                reviewer=str(getattr(current_user, "username", "") or ""),
            )
            return jsonify(result)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.get("/api/intercepts/day-blank")
    @login_required
    def api_intercepts_day_blank():
        """
        Бланк перехвата за сутки по выбранной частоте/группе.
        Параметры: frequency, group_code, date (YYYY-MM-DD).
        Возвращает объединённый контент всех бланков за день по этой паре (все смены).
        """
        frequency = str(request.args.get("frequency") or "").strip()
        group_code = str(request.args.get("group_code") or "").strip()
        date_ymd = str(request.args.get("date") or "").strip()[:10]
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = assemble_intercepts_day_blank_payload(
                conn, frequency=frequency, group_code=group_code, date_ymd=date_ymd
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            conn.close()

    @app.post("/api/intercepts/ai/proofread")
    @login_required
    def api_intercepts_ai_proofread():
        """AI-проверка бланка: предлагает точечные исправления очевидных ошибок."""
        ai_enabled = str(os.environ.get("WEB_PORTAL_AI_ENABLED") or "1").strip().lower()
        if ai_enabled in {"0", "false", "no", "off"}:
            return jsonify({"ok": False, "error": "AI-корректор отключен"}), 503
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав на редактирование"}), 403
        data = request.get_json(silent=True) or {}
        text = str(data.get("text") or "")
        if not text.strip():
            return jsonify({"ok": False, "error": "Текст бланка пуст"}), 400
        if len(text) > 12000:
            return jsonify({"ok": False, "error": "Текст слишком большой для AI-проверки"}), 400
        return jsonify(execute_intercepts_ai_proofread(text=text))

    @app.post("/api/intercepts/view-mode")
    @login_required
    def api_intercepts_set_view_mode():
        data = request.get_json(silent=True) or {}
        pconn = connect_portal(portal_db_path())
        try:
            payload = execute_intercepts_set_view_mode(
                pconn, user_id=int(current_user.id), mode=str(data.get("mode") or "")
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            pconn.close()

    @app.post("/api/intercepts/unit-order")
    @login_required
    def api_intercepts_unit_order():
        data = request.get_json(silent=True) or {}
        pconn = connect_portal(portal_db_path())
        try:
            payload = execute_intercepts_set_unit_order(
                pconn, user_id=int(current_user.id), order=data.get("order") or []
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            pconn.close()

    @app.post("/api/intercepts/catalog/favorite")
    @login_required
    def api_intercepts_catalog_favorite():
        data = request.get_json(silent=True) or {}
        pconn = connect_portal(portal_db_path())
        try:
            payload = execute_intercepts_catalog_favorite_toggle(
                pconn,
                user_id=int(current_user.id),
                catalog_id=int(data.get("catalog_id") or data.get("id") or 0),
                frequency=str(data.get("frequency") or ""),
                group_code=str(data.get("group_code") or data.get("group") or ""),
            )
            _intercepts_state_cache_clear()
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            pconn.close()

    @app.post("/api/intercepts/catalog/archive")
    @login_required
    def api_intercepts_catalog_archive():
        data = request.get_json(silent=True) or {}
        pconn = connect_portal(portal_db_path())
        try:
            payload = execute_intercepts_catalog_archive_toggle(
                pconn,
                user_id=int(current_user.id),
                catalog_id=int(data.get("catalog_id") or data.get("id") or 0),
                frequency=str(data.get("frequency") or ""),
                group_code=str(data.get("group_code") or data.get("group") or ""),
            )
            _intercepts_state_cache_clear()
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            pconn.close()

    @app.post("/api/intercepts/callsigns")
    @login_required
    def api_intercepts_callsigns_upsert():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        label = str(data.get("label") or "")
        code = str(data.get("code") or "")
        unit_name = str(data.get("unit_name") or "")
        frequency = str(data.get("frequency") or "")
        group_code = str(data.get("group_code") or "")
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:

            def _inv_all():
                _callsigns_cache_invalidate(pos)
                _units_tree_cache_invalidate(pos)
                _assignments_cache_invalidate(pos)
                _intercepts_state_cache_clear()

            payload = execute_intercepts_callsign_upsert(
                conn,
                position_name=pos,
                label=label,
                code=code,
                unit_name=unit_name,
                frequency=frequency,
                group_code=group_code,
                hub_sync_enabled=ctx.is_sync_hub(),
                invalidate_caches=_inv_all,
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.post("/api/intercepts/callsigns/update")
    @login_required
    def api_intercepts_callsigns_update():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        cid = int(data.get("id") or 0)
        label = str(data.get("label") or "")
        if not cid or not label.strip():
            return jsonify({"ok": False, "error": "id и label обязательны"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:

            def _inv_label():
                _callsigns_cache_invalidate(pos)
                _assignments_cache_invalidate(pos)
                _intercepts_state_cache_clear()

            payload = execute_intercepts_callsign_update_label(
                conn,
                position_name=pos,
                callsign_id=cid,
                label=label,
                invalidate_caches=_inv_label,
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.post("/api/intercepts/callsigns/delete")
    @login_required
    def api_intercepts_callsigns_delete():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        cid = int(data.get("id") or 0)
        if not cid:
            return jsonify({"ok": False, "error": "id обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:

            def _inv_del():
                _callsigns_cache_invalidate(pos)
                _units_tree_cache_invalidate(pos)
                _assignments_cache_invalidate(pos)
                _intercepts_state_cache_clear()

            payload = execute_intercepts_callsign_delete(
                conn, callsign_id=cid, invalidate_caches=_inv_del
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            conn.close()

    @app.post("/api/intercepts/callsigns/last-seen")
    @login_required
    def api_intercepts_callsigns_last_seen():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403

        data = request.get_json(silent=True) or {}
        frequency = str(data.get("frequency") or "").strip()
        group_code = str(data.get("group_code") or "").strip()
        raw_codes = data.get("codes") or []

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = execute_intercepts_callsigns_last_seen(
                conn,
                position_name=str(pos),
                frequency=frequency,
                group_code=group_code,
                raw_codes=raw_codes,
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.get("/api/analysis/intercepts-search")
    @login_required
    def api_analysis_intercepts_search():
        """Поиск по ключевым словам в бланках перехватов по всем программам."""
        q = str(request.args.get("q") or "").strip()
        if not q:
            return jsonify({"ok": False, "error": "Параметр q (ключевые слова) обязателен"}), 400
        pos = get_selected_position()
        if not pos and current_user.role == "admin":
            pos = "__all__"
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if pos != "__all__" and not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет доступа к позиции"}), 403
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            results = search_intercept_items(
                conn,
                query=q,
                position_name=pos,
                limit=200,
            )
            return jsonify({"ok": True, "results": results})
        finally:
            conn.close()

    @app.post("/api/intercepts/export-docx-job")
    @_perf_route("api/intercepts/export-docx-job")
    @login_required
    def api_intercepts_export_docx_job():
        data = request.get_json(silent=True) or {}
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "export"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        try:
            session_id = int(data.get("session_id") or 0)
        except Exception:
            return jsonify({"ok": False, "error": "Некорректный session_id"}), 400
        if not session_id:
            return jsonify({"ok": False, "error": "session_id обязателен"}), 400
        job_id = ctx.create_export_job_record(
            job_type="intercepts_docx",
            position_name=str(pos),
            params={"session_id": session_id, "position_name": str(pos)},
            created_by=ctx.ai_created_by(),
        )

        def _build() -> dict[str, object]:
            return ctx.build_intercepts_docx_export_result(job_id, {"session_id": session_id, "position_name": str(pos)})

        payload, status = ctx.submit_export_job(
            job_id,
            "intercepts-docx-export",
            _build,
        )
        return jsonify(payload), status

    @app.post("/api/intercepts/catalog")
    @login_required
    def api_intercepts_catalog_upsert():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "start"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        unit_name = str(data.get("unit_name") or "")
        frequency = str(data.get("frequency") or "")
        group_code = str(data.get("group_code") or "")
        location = str(data.get("location") or "")
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = execute_intercepts_catalog_upsert(
                conn,
                position_name=str(pos),
                unit_name=unit_name,
                frequency=frequency,
                group_code=group_code,
                location=location,
                hub_sync_enabled=ctx.is_sync_hub(),
            )
            return jsonify(payload)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.post("/api/intercepts/catalog/update-location")
    @login_required
    def api_intercepts_catalog_update_location():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "start"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        catalog_id = int(data.get("id") or 0)
        location = str(data.get("location") or "").strip()
        if not catalog_id:
            return jsonify({"ok": False, "error": "id обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = execute_intercepts_catalog_update_location(
                conn,
                position_name=str(pos),
                catalog_id=catalog_id,
                location=location,
                hub_sync_enabled=ctx.is_sync_hub(),
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.post("/api/intercepts/catalog/delete")
    @login_required
    def api_intercepts_catalog_delete():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "start"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        cid = int(data.get("id") or 0)
        if not cid:
            return jsonify({"ok": False, "error": "id обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = execute_intercepts_catalog_delete(
                conn,
                position_name=str(pos),
                catalog_id=cid,
                hub_sync_enabled=ctx.is_sync_hub(),
                schedule_hub_push_in_background=(
                    _schedule_hub_sync_push_bg if ctx.is_sync_hub() else None
                ),
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            conn.close()

    @app.post("/api/intercepts/catalog/rename-unit")
    @login_required
    def api_intercepts_catalog_rename_unit():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "start"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        old_name = str(data.get("old_name") or "").strip()
        new_name = str(data.get("new_name") or "").strip()
        if not old_name or not new_name:
            return (
                jsonify({"ok": False, "error": "old_name и new_name обязательны"}),
                400,
            )
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = execute_intercepts_catalog_rename_unit(
                conn,
                position_name=str(pos),
                old_name=old_name,
                new_name=new_name,
                hub_sync_enabled=ctx.is_sync_hub(),
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            conn.close()

    @app.post("/api/intercepts/catalog/delete-unit")
    @login_required
    def api_intercepts_catalog_delete_unit():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "start"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        unit_name = str(data.get("unit_name") or "").strip()
        if not unit_name:
            return jsonify({"ok": False, "error": "unit_name обязателен"}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = execute_intercepts_catalog_delete_unit(
                conn,
                position_name=str(pos),
                unit_name=unit_name,
                hub_sync_enabled=ctx.is_sync_hub(),
                schedule_hub_push_in_background=(
                    _schedule_hub_sync_push_bg if ctx.is_sync_hub() else None
                ),
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        finally:
            conn.close()

    @app.get("/api/intercepts/item")
    @login_required
    def api_intercepts_get_item():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        session_id = request.args.get("session_id", 0, type=int)
        catalog_id = request.args.get("catalog_id", 0, type=int)
        frequency = str(request.args.get("frequency") or "").strip()
        group_code = str(request.args.get("group_code") or "").strip()
        if not session_id:
            return jsonify({"ok": False, "error": "session_id обязателен"}), 400
        if not catalog_id and (not frequency or not group_code):
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "нужны session_id + (catalog_id или frequency+group_code)",
                    }
                ),
                400,
            )
        conn = get_request_main_db()
        try:
            payload = assemble_intercepts_get_item_payload(
                conn,
                position_name=str(pos),
                session_id=int(session_id),
                catalog_id=int(catalog_id or 0),
                frequency=frequency,
                group_code=group_code,
                permit_edit_when_open=require_position_role(pos, "edit"),
                exclude_typing_user=str(getattr(current_user, "username", "") or ""),
                hub_sync_enabled=ctx.is_sync_hub(),
                list_typing_labels=_typing_users,
            )
            client_sig = normalize_intercept_item_content_sig(
                request.args.get("item_sig") or ""
            )
            if client_sig:
                item = payload.get("item") if isinstance(payload, dict) else {}
                if isinstance(item, dict):
                    content = str(item.get("content") or "")
                    updated_at = str(item.get("updated_at") or "")
                    server_sig = normalize_intercept_item_content_sig(
                        compute_intercept_item_content_sig(updated_at, content)
                    )
                    if server_sig == client_sig:
                        return jsonify(
                            {
                                "ok": True,
                                "unchanged": True,
                                "item_sig": server_sig,
                                "assignments": payload.get("assignments"),
                                "typing": payload.get("typing"),
                            }
                        )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.get("/api/intercepts/item/wait")
    @login_required
    def api_intercepts_item_wait():
        """Long-poll: клиент ждёт изменения бланка (мгновенно для всех операторов)."""
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        item_id = request.args.get("item_id", 0, type=int)
        if item_id <= 0:
            return jsonify({"ok": False, "error": "item_id обязателен"}), 400
        try:
            timeout = float(request.args.get("timeout") or 25)
        except Exception:
            timeout = 25.0
        client_sig = normalize_intercept_item_content_sig(
            request.args.get("item_sig") or ""
        )
        result = _intercept_item_live_wait(item_id, client_sig, timeout_sec=timeout)
        return jsonify({"ok": True, **result})

    @app.post("/api/intercepts/typing")
    @login_required
    def api_intercepts_typing():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        session_id = int(data.get("session_id") or 0)
        catalog_id = int(data.get("catalog_id") or 0)
        is_typing = bool(data.get("typing", True))
        time_header = str(data.get("time_header") or "").strip()
        now_ts = float(time.time())
        try:
            payload = execute_intercepts_typing(
                typing_store=TYPING,
                typing_cleanup=_typing_cleanup,
                now_ts=now_ts,
                position_name=str(pos),
                username=str(current_user.username),
                session_id=session_id,
                catalog_id=catalog_id,
                is_typing=is_typing,
                time_header=time_header,
            )
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)

    @app.post("/api/intercepts/item/update")
    @login_required
    def api_intercepts_update_item():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "edit"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        item_id = int(data.get("item_id") or 0)
        content = str(data.get("content") or "")
        merge = bool(data.get("merge") or False)
        if not item_id:
            return jsonify({"ok": False, "error": "item_id обязателен"}), 400
        conn = get_request_main_db()
        try:
            payload = execute_intercepts_item_update(
                conn,
                item_id=item_id,
                content=content,
                merge=merge,
                updated_by=str(getattr(current_user, "username", "") or ""),
                hub_sync_enabled=ctx.is_sync_hub(),
                forward_payload=ctx.forward_intercept_payload_async,
            )
            item = payload.get("item") if isinstance(payload, dict) else {}
            if isinstance(item, dict):
                ctx.bump_intercept_item_live(
                    int(item.get("id") or item_id),
                    updated_at=str(item.get("updated_at") or ""),
                    content=str(item.get("content") or ""),
                )
            _intercepts_state_cache_clear()
            if ctx.is_sync_hub():
                _schedule_hub_sync_push_bg()
            if isinstance(payload, dict):
                payload = {k: v for k, v in payload.items() if k != "sync_payload"}
            return jsonify(payload)
        except InterceptsUseCaseHTTP as e:
            return jsonify(e.payload), int(e.status_code)
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/intercepts/session/start-new")
    @login_required
    def api_intercepts_start_new():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "start"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            payload = execute_intercepts_session_start_new(
                conn,
                position_name=str(pos),
                username=str(getattr(current_user, "username", "") or ""),
                hub_sync_enabled=ctx.is_sync_hub(),
            )
            # Старт новой смены — это самое заметное изменение state. Сбрасываем кэш
            # state, иначе остальные клиенты до истечения TTL продолжают видеть старую
            # активную смену и не переключаются автоматически.
            _intercepts_state_cache_clear()
            if ctx.is_sync_hub():
                _schedule_hub_sync_push_bg()
            return jsonify(payload)
        finally:
            conn.close()

    @app.get("/api/intercepts/export-docx")
    @_perf_route("api/intercepts/export-docx")
    @login_required
    def api_intercepts_export_docx():
        pos = get_selected_position()
        if not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if not require_position_role(pos, "export"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        session_id = request.args.get("session_id", 0, type=int)

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            try:
                tmp_path, filename = build_intercepts_export_docx_file(
                    conn, position_name=str(pos), session_id=session_id
                )
            except InterceptsUseCaseHTTP as e:
                return jsonify(e.payload), int(e.status_code)
            try:
                return send_file(
                    str(tmp_path),
                    as_attachment=True,
                    download_name=filename,
                    mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            finally:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    _log.debug("api_intercepts_export_docx: suppressed error", exc_info=True)
        finally:
            conn.close()
