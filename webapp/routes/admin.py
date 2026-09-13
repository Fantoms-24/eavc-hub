"""Маршруты админки (/admin, /api/admin/*), извлечены из app.py дословно."""

from __future__ import annotations

import json
import logging
import time
import uuid
from io import BytesIO

from flask import (
    Response,
    jsonify,
    render_template,
    request,
    send_file,
    stream_with_context,
)
from flask_login import current_user, login_required
from web_portal.app_perf import perf_route as _perf_route, perf_snapshot as _perf_snapshot
from web_portal.app_runtime_caches import all_caches_clear as _all_caches_clear
from web_portal.config import (
    DEFAULT_DB_NAME,
    db_path,
    deploy_announce_path,
    portal_db_path,
)
from web_portal.application.admin import (
    AdminUseCaseHTTP,
    assemble_admin_hubs_payload,
    assemble_admin_perf_caches,
    assemble_admin_roles_payload,
    assemble_admin_sync_status_payload,
    assemble_admin_targeting_list,
    assemble_admin_users_list_payload,
    assemble_ai_agent_watch_payload,
    assemble_llm_training_stats,
    assemble_user_positions_map,
    execute_admin_db_health,
    execute_ai_vector_index,
    execute_archive_seanses,
    execute_archive_seanses_to_file,
    execute_create_targeting,
    execute_llm_preference_hints_export,
    execute_llm_training_export,
    execute_seanses_multi_channel_day_report,
    iter_export_sessions_excel_events,
    parse_ai_vector_index_params,
    parse_archive_seanses_to_file_params,
    parse_create_targeting_input,
    parse_db_health_params,
    parse_llm_training_export_params,
    parse_positions_map_assignments,
    parse_seanses_multi_channel_day_params,
    require_user_id,
    resolve_ai_vector_db_path,
    resolve_export_sessions_folder,
    resolve_main_db_path,
)
from web_portal.lib.auth_db import (
    connect_portal,
    create_custom_role,
    create_user,
    delete_targeting,
    ensure_position,
    get_ai_chat_feedback_admin_overview,
    get_asr_training_policy,
    get_chat_channel_roles,
    get_user_sync_payload_by_id,
    list_ai_agent_actions,
    list_custom_roles,
    list_hub_activity,
    list_positions,
    set_asr_training_policy,
    set_chat_channel_roles,
    set_user_positions,
    update_user_password,
    update_user_role,
)
from web_portal.lib.db import (
    clear_seanses_by_client_name,
    connect,
    enqueue_sync_outbox,
    ensure_db,
)
from web_portal.lib.deploy_announce import bump_deploy_revision, write_announce
from web_portal.webapp.auth import require_perm, require_tab
from web_portal.webapp.context import AppContext
from web_portal.webapp.timeutils import _utc_now, _utc_now_str

_log = logging.getLogger("web_portal.webapp.routes.admin")


def register_admin_routes(app, ctx: AppContext):
    """Регистрирует маршруты админки через AppContext. Код перенесён из create_app дословно."""

    def _now_ts() -> str:
        # SQLite CURRENT_TIMESTAMP возвращает UTC, поэтому синк-таймстемпы держим в UTC.
        return _utc_now_str()

    @app.get("/admin/users")
    @login_required
    @require_tab("tab_admin")
    def admin_users():
        return render_template("admin_users.html")

    @app.post("/api/admin/deploy-announce")
    @login_required
    @require_perm("tab_admin")
    def api_admin_deploy_announce_post():
        data = request.get_json(silent=True) or {}
        msg = str(data.get("message") or "").strip()
        rev_in = str(data.get("revision") or "").strip()
        clear = bool(data.get("clear"))
        path = deploy_announce_path()
        if clear:
            ann = write_announce(path, "", "")
            return jsonify({"ok": True, **ann, "cleared": True})
        rev = rev_in or bump_deploy_revision()
        ann = write_announce(path, rev, msg)
        return jsonify({"ok": True, **ann})

    @app.get("/api/admin/users")
    @_perf_route("api/admin/users")
    @require_perm("tab_admin")
    def api_admin_list_users():
        conn = connect_portal(portal_db_path())
        try:
            return jsonify(assemble_admin_users_list_payload(conn))
        finally:
            conn.close()

    @app.get("/api/admin/roles")
    @require_perm("tab_admin")
    def api_admin_list_roles():
        """Справочник ролей, кастомные роли и категории вкладок (галочки)."""
        conn = connect_portal(portal_db_path())
        try:
            custom = list_custom_roles(conn)
            return jsonify(assemble_admin_roles_payload(custom))
        finally:
            conn.close()

    @app.post("/api/admin/roles")
    @require_perm("tab_admin")
    def api_admin_create_custom_role():
        """Создать кастомную роль с доступом по вкладкам (галочкам)."""
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        permissions = data.get("permissions") or []
        if not name:
            return jsonify({"ok": False, "error": "Имя роли обязательно"}), 400
        conn = connect_portal(portal_db_path())
        try:
            rid = create_custom_role(conn, name, permissions)
            return jsonify({"ok": True, "id": rid})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.get("/api/admin/chat-access")
    @require_perm("tab_admin")
    def api_admin_get_chat_access():
        """Получить настройки доступа к чату «Рабочая атмосфера» (роли)."""
        channel = request.args.get("channel") or "work_atmosphere"
        conn = connect_portal(portal_db_path())
        try:
            roles = get_chat_channel_roles(conn, channel)
            return jsonify({"ok": True, "channel": channel, "roles": roles})
        finally:
            conn.close()

    @app.post("/api/admin/chat-access")
    @require_perm("tab_admin")
    def api_admin_set_chat_access():
        """Задать роли с доступом к чату «Рабочая атмосфера»."""
        data = request.get_json(silent=True) or {}
        channel = (
            str(data.get("channel") or "work_atmosphere").strip() or "work_atmosphere"
        )
        roles = data.get("roles")
        if not isinstance(roles, list):
            roles = []
        roles = [str(r).strip() for r in roles if str(r).strip()]
        conn = connect_portal(portal_db_path())
        try:
            set_chat_channel_roles(conn, channel, roles)
            return jsonify({"ok": True, "channel": channel, "roles": roles})
        finally:
            conn.close()

    @app.get("/api/admin/asr-training")
    @require_perm("tab_admin")
    def api_admin_get_asr_training():
        """Глобальные настройки обучения ASR (портал)."""
        conn = connect_portal(portal_db_path())
        try:
            policy = get_asr_training_policy(conn)
            return jsonify({"ok": True, "policy": policy})
        finally:
            conn.close()

    @app.post("/api/admin/asr-training")
    @require_perm("tab_admin")
    def api_admin_set_asr_training():
        """Включить/выключить сбор обучающих примеров ASR."""
        data = request.get_json(silent=True) or {}

        def _bool(key: str, default: bool = False) -> bool:
            if key not in data:
                return default
            v = data.get(key)
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() in ("1", "true", "yes", "on")

        conn = connect_portal(portal_db_path())
        try:
            set_asr_training_policy(
                conn,
                training_enabled=_bool("training_enabled", default=False),
                learn_on_blank_send=_bool("learn_on_blank_send", default=True),
                learn_on_feedback=_bool("learn_on_feedback", default=True),
            )
            policy = get_asr_training_policy(conn)
            return jsonify({"ok": True, "policy": policy})
        finally:
            conn.close()

    @app.post("/api/admin/clear-client-name")
    @require_perm("tab_admin")
    def api_admin_clear_client_name():
        data = request.get_json(silent=True) or {}
        client_name = str(data.get("client_name") or "").strip()
        if not client_name:
            return jsonify({"ok": False, "error": "client_name обязателен"}), 400
        from web_portal.lib.seans_db import connect_seans_storage

        conn = connect_seans_storage()
        try:
            deleted = clear_seanses_by_client_name(conn, client_name)
            return jsonify({"ok": True, "client_name": client_name, "deleted": deleted})
        finally:
            conn.close()

    @app.get("/api/admin/db-health")
    @require_perm("tab_admin")
    def api_admin_db_health():
        """Проверка согласованности seanses/unit (wildcard, неоднозначности, разбор ID)."""
        try:
            params = parse_db_health_params(request.args)
            resolve_main_db_path(params.db_name)
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        conn = connect(db_path(params.db_name))
        try:
            return jsonify(execute_admin_db_health(conn, params))
        finally:
            conn.close()

    @app.post("/api/admin/ai-vector-index")
    @require_perm("tab_admin")
    def api_admin_ai_vector_index():
        """Догон / полная переиндексация семантического векторного индекса (RAG)."""
        data = request.get_json(silent=True) or {}
        try:
            params = parse_ai_vector_index_params(data)
            p = resolve_ai_vector_db_path(params.db_name)
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        conn = connect(p)
        try:
            return jsonify(execute_ai_vector_index(conn, params))
        except Exception as e:  # noqa: BLE001
            return jsonify({"ok": False, "error": str(e)}), 500
        finally:
            conn.close()

    @app.get("/api/admin/seanses-multi-channel-day")
    @require_perm("tab_admin")
    def api_admin_seanses_multi_channel_day():
        """ID за сутки, у которых сеансы на нескольких парах частота+группа."""
        try:
            params = parse_seanses_multi_channel_day_params(request.args)
            resolve_main_db_path(params.db_name)
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        conn = connect(db_path(params.db_name))
        try:
            payload, status = execute_seanses_multi_channel_day_report(conn, params)
            return jsonify(payload), status
        finally:
            conn.close()

    @app.get("/api/admin/seans-db/status")
    @require_perm("tab_admin")
    def api_admin_seans_db_status():
        """Статус разделения seans.sqlite / main.sqlite."""
        from web_portal.lib.seans_migrate import get_seans_db_migration_status

        return jsonify(get_seans_db_migration_status())

    @app.post("/api/admin/seans-db/migrate")
    @require_perm("tab_admin")
    def api_admin_seans_db_migrate():
        """
        Фоновый перенос сеансов в seans.sqlite.
        JSON: { \"confirm\": true, \"dry_run\": false, \"stop_watch\": true }
        """
        data = request.get_json(silent=True) or {}
        if not data.get("confirm"):
            return (
                jsonify({"ok": False, "error": "Подтвердите: confirm=true"}),
                400,
            )
        if bool(data.get("stop_watch", True)):
            try:
                if hasattr(app, "session_watchers") and app.session_watchers.get(
                    "hub_global"
                ):
                    w = app.session_watchers["hub_global"]
                    if w.get("mode") == "subprocess":
                        sp = w.get("stop_path")
                        proc = w.get("proc")
                        if sp:
                            try:
                                sp.touch()
                            except Exception:
                                _log.debug("api_admin_seans_db_migrate: suppressed error", exc_info=True)
                        if proc:
                            try:
                                proc.terminate()
                                proc.wait(timeout=8)
                            except Exception:
                                try:
                                    proc.kill()
                                except Exception:
                                    _log.debug("api_admin_seans_db_migrate: suppressed error", exc_info=True)
                    else:
                        stop_ev = w.get("stop")
                        if stop_ev:
                            stop_ev.set()
            except Exception:
                _log.debug("api_admin_seans_db_migrate: suppressed error", exc_info=True)
            time.sleep(3.0)

        from web_portal.lib.seans_migrate import start_seans_db_migration_background

        out = start_seans_db_migration_background(dry_run=bool(data.get("dry_run")))
        if not out.get("ok"):
            return jsonify(out), 409
        return jsonify(out)

    @app.post("/api/admin/seans-db/vacuum-main")
    @require_perm("tab_admin")
    def api_admin_seans_db_vacuum_main():
        """VACUUM main.sqlite после миграции seans (уменьшает файл)."""
        data = request.get_json(silent=True) or {}
        if not data.get("confirm"):
            return (
                jsonify({"ok": False, "error": "Подтвердите: confirm=true"}),
                400,
            )
        from web_portal.lib.seans_migrate import vacuum_main_database

        result = vacuum_main_database()
        if not result.get("ok"):
            return jsonify(result), 400
        return jsonify(result)

    @app.post("/api/admin/seans-db/purge-main")
    @require_perm("tab_admin")
    def api_admin_seans_db_purge_main():
        """Удалить дубликаты сеансов из main.sqlite (после миграции в seans.sqlite)."""
        data = request.get_json(silent=True) or {}
        if not data.get("confirm"):
            return (
                jsonify({"ok": False, "error": "Подтвердите: confirm=true"}),
                400,
            )
        from web_portal.lib.seans_migrate import purge_seans_from_main_database

        result = purge_seans_from_main_database()
        if not result.get("ok"):
            return jsonify(result), 400
        return jsonify(result)

    @app.post("/api/admin/archive-seanses")
    @require_perm("tab_admin")
    def api_admin_archive_seanses():
        data = request.get_json(silent=True) or {}
        from web_portal.lib.seans_db import connect_seans_storage

        conn = connect_seans_storage()
        try:
            return jsonify(
                execute_archive_seanses(
                    conn,
                    mode=str(data.get("mode") or "day"),
                    batch_size=int(data.get("batch_size") or 5000),
                    keep_date=str(data.get("keep_date") or "").strip()[:10] or None,
                )
            )
        finally:
            conn.close()

    @app.post("/api/admin/archive-seanses-to-file")
    @require_perm("tab_admin")
    def api_admin_archive_seanses_to_file():
        """
        Переносит строки, у которых календарная дата (первые 10 символов date_time)
        строго раньше before_date, в отдельный файл (например data/seanses_21_04_2026.sqlite)
        и удаляет их из основной БД.
        """
        data = request.get_json(silent=True) or {}
        try:
            params = parse_archive_seanses_to_file_params(data)
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        from web_portal.lib.seans_db import ensure_seans_storage, resolve_seans_storage_path

        src_p = resolve_seans_storage_path()
        ensure_seans_storage(src_p)
        try:
            return jsonify(execute_archive_seanses_to_file(params, main_db_path=src_p))
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code

    @app.post("/api/admin/export-sessions-excel")
    @require_perm("tab_admin")
    def api_admin_export_sessions_excel():
        """Парсит result0.txt в папке, стримит прогресс (NDJSON), в конце отдаёт token для скачивания."""
        data = request.get_json(silent=True) or {}
        try:
            path = resolve_export_sessions_folder(str(data.get("folder_path") or ""))
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code

        def _stream():
            for ev in iter_export_sessions_excel_events(path):
                if ev.get("stage") == "done":
                    token = uuid.uuid4().hex
                    if not hasattr(app, "export_tokens"):
                        app.export_tokens = {}
                    app.export_tokens[token] = (ev["content"], ev["filename"])
                    yield json.dumps(
                        {
                            "stage": "done",
                            "token": token,
                            "filename": ev["filename"],
                        }
                    ) + "\n"
                else:
                    public = {k: v for k, v in ev.items() if k != "content"}
                    yield json.dumps(public) + "\n"

        return Response(
            stream_with_context(_stream()),
            content_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/admin/export-sessions-excel/download/<token>")
    @require_perm("tab_admin")
    def api_admin_export_sessions_excel_download(token):
        """Скачивание готового Excel по одноразовому token."""
        if not hasattr(app, "export_tokens"):
            return jsonify({"ok": False, "error": "Файл не найден или устарел"}), 404
        data = app.export_tokens.pop(token, None)
        if not data:
            return jsonify({"ok": False, "error": "Файл не найден или устарел"}), 404
        buf_bytes, filename = data
        return send_file(
            BytesIO(buf_bytes),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name=filename,
        )

    @app.get("/api/admin/perf-metrics")
    @require_perm("tab_admin")
    def api_admin_perf_metrics():
        return jsonify(
            {
                "ok": True,
                "metrics": _perf_snapshot(),
                "caches": assemble_admin_perf_caches(),
            }
        )

    @app.get("/api/admin/ai-agent/actions")
    @require_perm("tab_admin")
    def api_admin_ai_agent_actions():
        try:
            limit = int(request.args.get("limit") or 100)
        except Exception:
            limit = 100
        tool = str(request.args.get("tool") or "").strip()
        user_id_raw = str(request.args.get("user_id") or "").strip()
        user_id_filter = int(user_id_raw) if user_id_raw.isdigit() else None
        conn = connect_portal(portal_db_path())
        try:
            actions = list_ai_agent_actions(
                conn,
                user_id=user_id_filter,
                tool=tool,
                limit=limit,
            )
            return jsonify({"ok": True, "actions": actions})
        finally:
            conn.close()

    @app.get("/api/admin/ai-agent/chat-feedback")
    @require_perm("tab_admin")
    def api_admin_ai_agent_chat_feedback():
        """Сводка и лента оценок ответов EAVC Manager в AI-чате."""
        try:
            limit = int(request.args.get("limit") or 50)
        except Exception:
            limit = 50
        conn = connect_portal(portal_db_path())
        try:
            overview = get_ai_chat_feedback_admin_overview(
                conn, recent_limit=limit
            )
            return jsonify({"ok": True, **overview})
        finally:
            conn.close()

    @app.get("/api/admin/ai-agent/llm-training-export")
    @require_perm("tab_admin")
    def api_admin_ai_agent_llm_training_export():
        """JSONL (chat user/assistant) для SFT/LoRA вне портала (Ollama, Unsloth, и т.д.)."""
        params = parse_llm_training_export_params(request.args)
        conn = connect_portal(portal_db_path())
        try:
            body = execute_llm_training_export(conn, params)
            return Response(
                body,
                mimetype="application/x-ndjson; charset=utf-8",
                headers={
                    "Content-Disposition": 'attachment; filename="eavc_llm_sft.jsonl"'
                },
            )
        finally:
            conn.close()

    @app.get("/api/admin/ai-agent/llm-training-stats")
    @require_perm("tab_admin")
    def api_admin_ai_agent_llm_training_stats():
        """Сводка датасета для дообучения без скачивания файла."""
        conn = connect_portal(portal_db_path())
        try:
            return jsonify(assemble_llm_training_stats(conn))
        finally:
            conn.close()

    @app.get("/api/admin/ai-agent/llm-preference-hints-export")
    @require_perm("tab_admin")
    def api_admin_ai_agent_llm_preference_hints_export():
        """JSONL: thumbs down + комментарий + уточняющее сообщение (для DPO/RLHF-пайплайна)."""
        try:
            lim = int(request.args.get("limit") or 5000)
        except (TypeError, ValueError):
            lim = 5000
        conn = connect_portal(portal_db_path())
        try:
            body = execute_llm_preference_hints_export(conn, limit=lim)
            return Response(
                body,
                mimetype="application/x-ndjson; charset=utf-8",
                headers={
                    "Content-Disposition": 'attachment; filename="eavc_llm_preference_hints.jsonl"'
                },
            )
        finally:
            conn.close()

    @app.get("/api/admin/ai-agent/watch-status")
    @require_perm("tab_admin")
    def api_admin_ai_agent_watch_status():
        conn = connect_portal(portal_db_path())
        try:
            return jsonify(assemble_ai_agent_watch_payload(conn, persist=False))
        finally:
            conn.close()

    @app.post("/api/admin/ai-agent/watch-run")
    @require_perm("tab_admin")
    def api_admin_ai_agent_watch_run():
        conn = connect_portal(portal_db_path())
        try:
            return jsonify(assemble_ai_agent_watch_payload(conn, persist=True))
        finally:
            conn.close()

    @app.post("/api/admin/caches-clear")
    @require_perm("tab_admin")
    def api_admin_caches_clear():
        """Полный сброс всех TTL-кэшей (для диагностики/после ручных правок БД)."""
        cleared = _all_caches_clear()
        return jsonify({"ok": True, "cleared": cleared})

    @app.post("/api/admin/users")
    @require_perm("tab_admin")
    def api_admin_create_user():
        data = request.get_json(silent=True) or {}
        username = data.get("username", "")
        callsign = data.get("callsign", "")
        role = data.get("role", "")
        password = data.get("password", "")
        if not username or not password:
            return (
                jsonify({"ok": False, "error": "username и password обязательны"}),
                400,
            )
        conn = connect_portal(portal_db_path())
        try:
            uid = create_user(conn, username, callsign, role, password)
            # HUB: синхронизируем пользователя на центральный сервер
            if ctx.is_sync_hub():
                try:
                    payload = get_user_sync_payload_by_id(conn, int(uid))
                    if payload:
                        mconn = connect(db_path(DEFAULT_DB_NAME))
                        try:
                            enqueue_sync_outbox(
                                mconn, kind="portal:user", payload=payload
                            )
                        finally:
                            mconn.close()
                except Exception:
                    _log.debug("api_admin_create_user: suppressed error", exc_info=True)
            return jsonify({"ok": True, "id": uid})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400

    @app.post("/api/admin/users/role")
    @require_perm("tab_admin")
    def api_admin_update_role():
        data = request.get_json(silent=True) or {}
        conn = connect_portal(portal_db_path())
        try:
            user_id = int(data.get("user_id") or 0)
            update_user_role(conn, user_id, str(data.get("role")))
            if ctx.sync_upstream and ctx.sync_key and user_id:
                try:
                    payload = get_user_sync_payload_by_id(conn, user_id)
                    if payload:
                        mconn = connect(db_path(DEFAULT_DB_NAME))
                        try:
                            enqueue_sync_outbox(
                                mconn, kind="portal:user", payload=payload
                            )
                        finally:
                            mconn.close()
                except Exception:
                    _log.debug("api_admin_update_role: suppressed error", exc_info=True)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/admin/users/password")
    @require_perm("tab_admin")
    def api_admin_update_password():
        data = request.get_json(silent=True) or {}
        pw = str(data.get("password") or "")
        if not pw:
            return jsonify({"ok": False, "error": "Пароль пустой"}), 400
        conn = connect_portal(portal_db_path())
        try:
            user_id = int(data.get("user_id") or 0)
            update_user_password(conn, user_id, pw)
            if ctx.sync_upstream and ctx.sync_key and user_id:
                try:
                    payload = get_user_sync_payload_by_id(conn, user_id)
                    if payload:
                        mconn = connect(db_path(DEFAULT_DB_NAME))
                        try:
                            enqueue_sync_outbox(
                                mconn, kind="portal:user", payload=payload
                            )
                        finally:
                            mconn.close()
                except Exception:
                    _log.debug("api_admin_update_password: suppressed error", exc_info=True)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/admin/users/positions")
    @require_perm("tab_admin")
    def api_admin_update_user_positions():
        data = request.get_json(silent=True) or {}
        user_id = int(data.get("user_id") or 0)
        positions = data.get("positions") or []
        if not user_id:
            return jsonify({"ok": False, "error": "user_id обязателен"}), 400
        if not isinstance(positions, list):
            return jsonify({"ok": False, "error": "positions должен быть list"}), 400
        conn = connect_portal(portal_db_path())
        try:
            set_user_positions(conn, user_id, [str(x) for x in positions])
            if ctx.sync_upstream and ctx.sync_key and user_id:
                try:
                    r = conn.execute(
                        "SELECT username FROM users WHERE id=?",
                        (int(user_id),),
                    ).fetchone()
                    uname = str(r["username"] or "") if r else ""
                    if uname:
                        mconn = connect(db_path(DEFAULT_DB_NAME))
                        try:
                            enqueue_sync_outbox(
                                mconn,
                                kind="portal:positions",
                                payload={
                                    "username": uname,
                                    "positions": [str(x) for x in positions],
                                },
                            )
                        finally:
                            mconn.close()
                except Exception:
                    _log.debug("api_admin_update_user_positions: suppressed error", exc_info=True)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/admin/positions")
    @require_perm("tab_admin")
    def api_admin_list_positions():
        conn = connect_portal(portal_db_path())
        try:
            return jsonify({"ok": True, "positions": list_positions(conn)})
        finally:
            conn.close()

    @app.post("/api/admin/positions")
    @require_perm("tab_admin")
    def api_admin_create_position():
        data = request.get_json(silent=True) or {}
        name = str(data.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "name обязателен"}), 400
        conn = connect_portal(portal_db_path())
        try:
            ensure_position(conn, name)
            if ctx.is_sync_hub():
                try:
                    mconn = connect(db_path(DEFAULT_DB_NAME))
                    try:
                        enqueue_sync_outbox(
                            mconn, kind="portal:position", payload={"name": str(name)}
                        )
                    finally:
                        mconn.close()
                except Exception:
                    _log.debug("api_admin_create_position: suppressed error", exc_info=True)
            return jsonify({"ok": True})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.get("/api/admin/targeting")
    @require_perm("tab_admin")
    def api_admin_list_targeting():
        """Получить все нацеливания (для админа)."""
        conn = connect_portal(portal_db_path())
        try:
            targeting = assemble_admin_targeting_list(conn, now_iso=_utc_now_str())
            return jsonify({"ok": True, "targeting": targeting})
        finally:
            conn.close()

    @app.post("/api/admin/targeting")
    @require_perm("tab_admin")
    def api_admin_create_targeting():
        """Создать новое нацеливание."""
        data = request.get_json(silent=True) or {}
        try:
            params = parse_create_targeting_input(
                data,
                created_by=current_user.username,
            )
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        conn = connect_portal(portal_db_path())
        try:
            return jsonify(
                execute_create_targeting(
                    conn,
                    params,
                    is_sync_hub=ctx.is_sync_hub(),
                )
            )
        finally:
            conn.close()

    @app.post("/api/admin/targeting/delete")
    @require_perm("tab_admin")
    def api_admin_delete_targeting():
        """Удалить нацеливание."""
        data = request.get_json(silent=True) or {}
        targeting_id = int(data.get("targeting_id") or 0)
        if not targeting_id:
            return jsonify({"ok": False, "error": "targeting_id обязателен"}), 400
        conn = connect_portal(portal_db_path())
        try:
            deleted = delete_targeting(conn, targeting_id=targeting_id)
            if not deleted:
                return jsonify({"ok": False, "error": "Нацеливание не найдено"}), 404
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/admin/sync/status")
    @require_perm("tab_admin")
    def api_admin_sync_status():
        """
        Диагностика синхронизации для админ-панели.
        Показывает статус синхронизации (Hub/Server, outbox, метаданные).
        """
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            return jsonify(
                assemble_admin_sync_status_payload(
                    conn,
                    now_ts=_now_ts(),
                    sync_upstream=ctx.sync_upstream,
                    sync_key=ctx.sync_key,
                )
            )
        finally:
            conn.close()

    @app.post("/api/admin/users/positions-map")
    @require_perm("tab_admin")
    def api_admin_update_user_positions_map():
        """
        assignments: { "Москва": "operator", "Рязань": "chief" }
        """
        data = request.get_json(silent=True) or {}
        try:
            user_id = require_user_id(data)
            tokens = parse_positions_map_assignments(data.get("assignments") or {})
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        conn = connect_portal(portal_db_path())
        try:
            try:
                set_user_positions(conn, user_id, tokens)
            except Exception as e:
                return jsonify({"ok": False, "error": str(e)}), 400
            if ctx.sync_upstream and ctx.sync_key and user_id:
                try:
                    r = conn.execute(
                        "SELECT username FROM users WHERE id=?",
                        (int(user_id),),
                    ).fetchone()
                    uname = str(r["username"] or "") if r else ""
                    if uname:
                        mconn = connect(db_path(DEFAULT_DB_NAME))
                        try:
                            enqueue_sync_outbox(
                                mconn,
                                kind="portal:positions",
                                payload={"username": uname, "positions": tokens},
                            )
                        finally:
                            mconn.close()
                except Exception:
                    _log.debug("api_admin_update_user_positions_map: suppressed error", exc_info=True)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/admin/users/positions-map")
    @require_perm("tab_admin")
    def api_admin_get_user_positions_map():
        """Получить карту назначений позиций для пользователя: {position_name: role}."""
        try:
            user_id = require_user_id(request.args.get("user_id", 0, type=int) or 0)
        except AdminUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        conn = connect_portal(portal_db_path())
        try:
            return jsonify(assemble_user_positions_map(conn, user_id))
        finally:
            conn.close()

    @app.get("/api/admin/hubs")
    @require_perm("tab_admin")
    def api_admin_list_hubs():
        """Получить список активных Hub'ов."""
        max_age = request.args.get("max_age_minutes", 60, type=int)
        conn = connect_portal(portal_db_path())
        try:
            hubs = list_hub_activity(conn, max_age_minutes=max_age)
            result = assemble_admin_hubs_payload(
                hubs,
                now=_utc_now().replace(tzinfo=None),
            )
            return jsonify({"ok": True, "hubs": result})
        finally:
            conn.close()
