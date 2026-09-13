from __future__ import annotations

from typing import Any, Callable

from flask import Flask, jsonify, request
from flask_login import current_user


def register_admin_event_log_routes(
    app: Flask,
    *,
    require_perm: Callable[[str], Callable],
    connect_portal: Callable,
    portal_db_path: Callable,
    log_portal_event: Callable[..., None],
) -> None:
    """Регистрирует API журнала админ-панели (вызывать один раз из create_app)."""

    @app.get("/api/admin/event-log/status")
    def api_admin_event_log_status():
        """Проверка, что сервер поднят с поддержкой журнала (без авторизации)."""
        return jsonify({"ok": True, "feature": "event-log", "version": 1})

    @app.get("/api/admin/event-log")
    @require_perm("tab_admin")
    def api_admin_event_log():
        from web_portal.lib.portal_event_log import list_portal_events

        try:
            limit = int(request.args.get("limit") or 200)
        except ValueError:
            limit = 200
        try:
            offset = int(request.args.get("offset") or 0)
        except ValueError:
            offset = 0
        conn = connect_portal(portal_db_path())
        try:
            data = list_portal_events(
                conn,
                limit=limit,
                offset=offset,
                level=str(request.args.get("level") or "").strip(),
                category=str(request.args.get("category") or "").strip(),
                q=str(request.args.get("q") or "").strip(),
                since=str(request.args.get("since") or "").strip(),
                until=str(request.args.get("until") or "").strip(),
            )
            return jsonify({"ok": True, **data})
        finally:
            conn.close()

    @app.get("/api/admin/event-log/file-tail")
    @require_perm("tab_admin")
    def api_admin_event_log_file_tail():
        from web_portal.lib.portal_event_log import tail_log_file

        try:
            lines = int(request.args.get("lines") or 300)
        except ValueError:
            lines = 300
        payload = tail_log_file(max_lines=lines)
        return jsonify({"ok": True, **payload})

    @app.post("/api/admin/event-log/purge")
    @require_perm("tab_admin")
    def api_admin_event_log_purge():
        from web_portal.lib.portal_event_log import purge_portal_events

        data = request.get_json(silent=True) or {}
        try:
            days = int(data.get("days") or request.args.get("days") or 30)
        except ValueError:
            days = 30
        conn = connect_portal(portal_db_path())
        try:
            deleted = purge_portal_events(conn, days=days)
            log_portal_event(
                level="INFO",
                category="admin",
                action="event_log_purge",
                message=f"Очистка журнала: удалено {deleted}, старше {days} дн.",
                user_id=int(current_user.id),
                username=str(current_user.username or ""),
                ip=str(request.remote_addr or ""),
                path="/api/admin/event-log/purge",
                method="POST",
            )
            return jsonify({"ok": True, "deleted": deleted, "days": days})
        finally:
            conn.close()
