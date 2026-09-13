"""Sync API (push/pull/status) без логина, по X-Sync-Key. Извлечено из app.py дословно."""

from __future__ import annotations

import hmac
import logging

from flask import jsonify, request

from web_portal.config import DEFAULT_DB_NAME, db_path, portal_db_path
from web_portal.app_perf import perf_route as _perf_route
from web_portal.lib.auth_db import connect_portal, update_hub_activity
from web_portal.lib.db import (
    connect,
    ensure_db,
    get_sync_meta,
    list_sync_outbox_pending,
)
from web_portal.lib.heavy_workers import run_sync_pull_blocking as _run_sync_pull_blocking
from web_portal.lib.sync_pull_builder import build_sync_pull_payload as _build_sync_pull_payload
from web_portal.webapp.context import AppContext
from web_portal.webapp.timeutils import _utc_now_str

_log = logging.getLogger("web_portal.webapp.routes.sync_api")
logger = logging.getLogger(__name__)


def register_sync_routes(app, ctx: AppContext):
    """Регистрирует маршруты синхронизации. Код перенесён из create_app дословно."""

    def _require_sync_key() -> bool:
        if not ctx.sync_key:
            return False
        got = (request.headers.get("X-Sync-Key") or "").strip()
        return bool(got) and hmac.compare_digest(got, ctx.sync_key)

    def _now_ts() -> str:
        if ctx.now_ts is not None:
            return ctx.now_ts()
        return _utc_now_str()

    @app.post("/api/sync/push")
    def api_sync_push():
        if not _require_sync_key():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        data = request.get_json(silent=True) or {}
        events = data.get("events") or []
        if not isinstance(events, list):
            return jsonify({"ok": False, "error": "events должен быть list"}), 400

        # Отслеживание активности Hub
        hub_id = data.get("hub_id") or request.remote_addr or "unknown"
        hub_name = data.get("hub_name") or ""
        position_name = data.get("position_name") or ""
        ip_address = request.remote_addr or ""

        pconn = connect_portal(portal_db_path())
        try:
            update_hub_activity(
                pconn,
                hub_id=str(hub_id),
                hub_name=hub_name,
                position_name=position_name,
                ip_address=ip_address,
                last_push=True,
            )
        finally:
            pconn.close()

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        applied = 0
        try:
            from web_portal.lib.db import set_connection_defer_commit
            from web_portal.lib.sync_push_apply import (
                apply_sync_push_event,
                is_sync_push_external_kind,
                partition_sync_push_events,
            )

            priority_ev, bulk_ev = partition_sync_push_events(events)
            phase_errors: list[str] = []

            def _apply_one(ev: dict, *, fail_fast: bool) -> None:
                nonlocal applied
                kind = str(ev.get("kind") or "").strip()
                payload = ev.get("payload") or {}
                if not isinstance(payload, dict):
                    payload = {}
                try:
                    applied += apply_sync_push_event(
                        conn,
                        kind=kind,
                        payload=payload,
                        forward_intercept=ctx.forward_intercept_payload_async,
                    )
                    if kind == "intercepts:item":
                        ctx.bump_intercept_item_live_from_sync(conn, payload)
                        ctx.intercepts_state_cache_clear()
                except Exception as exc:
                    phase_errors.append(f"{kind}: {exc}")
                    if fail_fast:
                        raise

            def _apply_phase(
                phase_events: list,
                *,
                fail_fast: bool,
                split_external: bool,
            ) -> None:
                if not phase_events:
                    return
                if not split_external:
                    set_connection_defer_commit(conn, True)
                    conn.execute("BEGIN IMMEDIATE")
                    try:
                        for ev in phase_events:
                            if not isinstance(ev, dict):
                                continue
                            _apply_one(ev, fail_fast=fail_fast)
                    finally:
                        conn.commit()
                        set_connection_defer_commit(conn, False)
                    return

                external: list[dict] = []
                main_events: list[dict] = []
                for ev in phase_events:
                    if not isinstance(ev, dict):
                        continue
                    kind = str(ev.get("kind") or "").strip()
                    if is_sync_push_external_kind(kind):
                        external.append(ev)
                    else:
                        main_events.append(ev)
                for ev in external:
                    _apply_one(ev, fail_fast=False)
                if not main_events:
                    return
                set_connection_defer_commit(conn, True)
                conn.execute("BEGIN IMMEDIATE")
                try:
                    for ev in main_events:
                        _apply_one(ev, fail_fast=False)
                finally:
                    conn.commit()
                    set_connection_defer_commit(conn, False)

            # Фаза 1: бланки/смены — короткая транзакция, без seanses:batch.
            _apply_phase(priority_ev, fail_fast=True, split_external=False)
            # Фаза 2: seans/search/portal без блокировки main; unit/aviation — короткий commit.
            _apply_phase(bulk_ev, fail_fast=False, split_external=True)

            body: dict = {"ok": True, "applied": applied, "now": _now_ts()}
            if phase_errors:
                body["errors"] = phase_errors[:8]
            return jsonify(body)
        except Exception as exc:
            try:
                conn.rollback()
            except Exception:
                _log.debug("api_sync_push: suppressed error", exc_info=True)
            logger.exception("api/sync/push failed: %s", exc)
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": str(exc),
                        "applied": applied,
                        "now": _now_ts(),
                    }
                ),
                500,
            )
        finally:
            from web_portal.lib.db import finish_connection_defer_commit

            finish_connection_defer_commit(conn, rollback=True)
            try:
                from web_portal.lib.db import unregister_connection

                unregister_connection(conn)
                conn.close()
            except Exception:
                _log.debug("api_sync_push: suppressed error", exc_info=True)

    @app.get("/api/sync/pull")
    @_perf_route("api/sync/pull")
    def api_sync_pull():
        if not _require_sync_key():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        since = str(request.args.get("since") or "").strip() or "1970-01-01 00:00:00"
        positions_raw = (
            str(
                request.args.get("positions") or request.args.get("position_name") or ""
            )
        ).strip()
        position_names = [p.strip() for p in positions_raw.split(",") if p.strip()]
        include_seanses = str(request.args.get("include_seanses") or "").strip().lower()
        allow_seanses = include_seanses not in {"0", "false", "no", "off"}
        import os as _os_pull

        _def_seanses = int(_os_pull.environ.get("WEB_PORTAL_SYNC_PULL_SEANSES_LIMIT") or 2000)
        _def_unit = int(_os_pull.environ.get("WEB_PORTAL_SYNC_PULL_UNIT_LIMIT") or 2000)
        _def_online = int(_os_pull.environ.get("WEB_PORTAL_SYNC_PULL_ONLINE_LIMIT") or 1200)
        try:
            seanses_limit = max(
                200, min(int(request.args.get("seanses_limit") or _def_seanses), 4000)
            )
        except Exception:
            seanses_limit = max(200, min(_def_seanses, 4000))
        try:
            unit_limit = max(200, min(int(request.args.get("unit_limit") or _def_unit), 4000))
        except Exception:
            unit_limit = max(200, min(_def_unit, 4000))
        try:
            online_limit = max(
                200, min(int(request.args.get("online_limit") or _def_online), 3000)
            )
        except Exception:
            online_limit = max(200, min(_def_online, 3000))

        # Отслеживание активности Hub
        hub_id = request.args.get("hub_id") or request.remote_addr or "unknown"
        hub_name = request.args.get("hub_name") or ""
        position_name = request.args.get("position_name") or positions_raw or ""
        ip_address = request.remote_addr or ""

        pconn = connect_portal(portal_db_path())
        try:
            update_hub_activity(
                pconn,
                hub_id=str(hub_id),
                hub_name=hub_name,
                position_name=position_name,
                ip_address=ip_address,
                last_pull=True,
            )
        finally:
            pconn.close()

        import logging as _logging_pull
        import time as _time_pull

        _pull_log = _logging_pull.getLogger("web_portal.sync")
        _pull_t0 = _time_pull.perf_counter()

        def _build() -> dict:
            return _build_sync_pull_payload(
                since=since,
                position_names=position_names,
                allow_seanses=allow_seanses,
                seanses_limit=seanses_limit,
                unit_limit=unit_limit,
                online_limit=online_limit,
            )

        status, result = _run_sync_pull_blocking(_build)
        if status == "busy":
            if ctx.log_portal_event is not None:
                ctx.log_portal_event(
                    level="WARNING",
                    category="sync",
                    action="sync_pull_busy",
                    message="sync/pull отклонён: занят воркер",
                    ip=ip_address,
                    path="/api/sync/pull",
                    method="GET",
                    status_code=503,
                    details={"hub_id": hub_id, "positions": positions_raw},
                )
            resp = jsonify(
                {
                    "ok": False,
                    "error": "sync_pull_busy",
                    "message": "Сервер обрабатывает другой sync pull. Повторите через несколько секунд.",
                }
            )
            resp.headers["Retry-After"] = "5"
            return resp, 503
        if status == "timeout":
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "sync_pull_timeout",
                        "message": "Превышено время ожидания sync pull на сервере.",
                    }
                ),
                504,
            )
        if status != "ok" or result is None:
            return jsonify({"ok": False, "error": "sync_pull_failed"}), 500

        _pull_ms = int((_time_pull.perf_counter() - _pull_t0) * 1000)
        if _pull_ms >= 15000:
            _pull_log.warning(
                "sync/pull медленный ответ: %sms | seanses=%s items=%s | remote=%s",
                _pull_ms,
                len(result.get("seanses") or []),
                len(result.get("items") or []),
                ip_address,
            )
            if ctx.log_portal_event is not None:
                ctx.log_portal_event(
                    level="WARNING",
                    category="sync",
                    action="sync_pull_slow",
                    message=f"sync/pull {_pull_ms} ms",
                    ip=ip_address,
                    path="/api/sync/pull",
                    method="GET",
                    status_code=200,
                    duration_ms=_pull_ms,
                    details={
                        "seanses": len(result.get("seanses") or []),
                        "items": len(result.get("items") or []),
                        "hub_id": hub_id,
                    },
                )
        return jsonify(result)

    @app.get("/api/sync/status")
    def api_sync_status():
        """
        Диагностика синхронизации (для проверки что "всё едет").
        Защищено X-Sync-Key, логин не нужен.
        """
        if not _require_sync_key():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            meta_keys = [
                "last_pull_ts",
                "seanses_last_rowid",
                "unit_last_rowid",
                "online_search_last_ts",
                "online_search_last_id",
            ]
            if ctx.sync_upstream and ctx.sync_key:
                from web_portal.lib.sync_delivery import load_cursor, pending_delivery, session_source

                pending = pending_delivery(p, limit=200)
                meta = {
                    key: load_cursor(session_source() if key == "seanses_last_rowid" else p, key)
                    for key in meta_keys
                }
            else:
                pending = list_sync_outbox_pending(conn, limit=200)
                meta = {k: (get_sync_meta(conn, k) or "") for k in meta_keys}
            return jsonify(
                {
                    "ok": True,
                    "now": _now_ts(),
                    "is_hub": bool(ctx.sync_upstream and ctx.sync_key),
                    "upstream": ctx.sync_upstream or "",
                    "outbox_pending": len(pending),
                    "outbox_head": [
                        {
                            "id": int(x["id"]),
                            "kind": str(x["kind"] or ""),
                            "created_at": str(x["created_at"] or ""),
                            "attempts": int(x["attempts"] or 0),
                        }
                        for x in (pending[:10] if isinstance(pending, list) else [])
                    ],
                    "meta": meta,
                    "server_accepts_kinds": [
                        "intercepts:item",
                        "intercepts:session",
                        "intercepts:catalog",
                        "intercepts:catalog_delete",
                        "intercepts:callsign",
                        "analysis:assignment",
                        "seanses:batch",
                        "online_search:batch",
                        "online_search:delete",
                        "online_search:meta",
                        "unit:batch",
                        "aviation:frequency",
                        "aviation:intercept",
                        "aviation:callsign",
                        "aviation:frequency_delete",
                        "aviation:callsign_delete",
                        "portal:user",
                        "portal:positions",
                        "portal:position",
                        "targeting",
                    ],
                }
            )
        finally:
            conn.close()
