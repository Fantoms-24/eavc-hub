"""Служебные маршруты: health, базы данных, целеуказания. Извлечено из app.py дословно."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import jsonify, request
from flask_login import current_user, login_required

from web_portal.config import (
    DATA_DIR,
    DEFAULT_DB_NAME,
    db_path,
    portal_db_path,
    safe_db_name,
)
from web_portal.lib.auth_db import (
    connect_portal,
    get_user_positions,
    list_targeting,
    mark_targeting_read,
)
from web_portal.lib.db import (
    connect,
    ensure_db,
    get_db_stats,
    get_db_stats_legacy,
    list_db_files,
    scan_seanses_once,
)
from web_portal.positions import get_selected_position
from web_portal.webapp.context import AppContext

_log = logging.getLogger("web_portal.webapp.routes.misc")


def register_misc_routes(app, ctx: AppContext):
    """Регистрирует служебные маршруты через AppContext. Код перенесён из create_app дословно."""

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/databases")
    @login_required
    def api_list_databases():
        dbs = list_db_files(DATA_DIR)
        if DEFAULT_DB_NAME not in dbs:
            dbs = [DEFAULT_DB_NAME] + dbs
        return jsonify({"databases": dbs, "default": DEFAULT_DB_NAME})

    @app.post("/api/databases")
    @login_required
    def api_create_database():
        if not (
            current_user.has_perm("manage_users")
            or current_user.has_perm("import_folder")
        ):
            return jsonify({"ok": False, "error": "Нет прав на создание БД"}), 403
        data = request.get_json(silent=True) or {}
        name_raw = data.get("name", "")
        try:
            name = safe_db_name(name_raw)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        if ctx.is_sync_hub():
            if name != DEFAULT_DB_NAME:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "В режиме HUB синхронизируется только main.sqlite",
                        }
                    ),
                    400,
                )

        p = db_path(name)
        ensure_db(p)
        return jsonify({"ok": True, "name": p.name})

    @app.get("/api/db-stats")
    @login_required
    def api_db_stats():
        source = (request.args.get("source") or "main").strip().lower()
        source = "legacy" if source == "legacy" else "main"
        if source == "legacy":
            legacy = (DATA_DIR / "database.sqlite").resolve()
            if not legacy.exists():
                return (
                    jsonify({"ok": False, "error": "Не загружен database.sqlite"}),
                    400,
                )
            conn = connect(legacy)
            try:
                pos = get_selected_position()
                stats = get_db_stats_legacy(conn, client_name=pos)
                return jsonify(
                    {
                        "ok": True,
                        "db": legacy.name,
                        "source": "legacy",
                        "stats": stats,
                        "position": pos,
                    }
                )
            finally:
                conn.close()

        name = request.args.get("db", DEFAULT_DB_NAME)
        p = db_path(name)
        ensure_db(p)
        conn = connect(p)
        try:
            pos = get_selected_position()
            # статистика под выбранную позицию (если выбрана)
            if pos:
                cur = conn.cursor()
                total = cur.execute(
                    "SELECT COUNT(*) FROM seanses WHERE client_name=?",
                    (pos,),
                ).fetchone()[0]
                last_dt = cur.execute(
                    "SELECT MAX(date_time) FROM seanses WHERE client_name=?",
                    (pos,),
                ).fetchone()[0]
                unit_last = cur.execute("SELECT MAX(updated_at) FROM unit;").fetchone()[
                    0
                ]
                stats = {
                    "total_records": int(total or 0),
                    "last_datetime": last_dt or None,
                    "unit_last_updated_at": unit_last or None,
                }
            else:
                stats = get_db_stats(conn)
            return jsonify(
                {
                    "ok": True,
                    "db": p.name,
                    "source": "main",
                    "stats": stats,
                    "position": pos,
                }
            )
        finally:
            conn.close()

        # API endpoints для импорта папок и сканирования сеансов удалены
        """
        Сканирует папки и собирает данные из result0.txt с отслеживанием обработанных файлов.
        Аналогично scan_once() из основного проекта agent/agent.py.
        """
        data = request.get_json(silent=True) or {}
        name = data.get("db", DEFAULT_DB_NAME)
        if ctx.is_sync_hub():
            try:
                if safe_db_name(str(name)) != DEFAULT_DB_NAME:
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": "В режиме HUB синхронизируется только main.sqlite",
                            }
                        ),
                        400,
                    )
            except Exception:
                return jsonify({"ok": False, "error": "Недопустимое имя БД"}), 400

        scan_paths_raw = data.get("scan_paths", "")
        if not scan_paths_raw:
            return (
                jsonify({"ok": False, "error": "Не указаны папки для сканирования"}),
                400,
            )

        scan_paths = [
            Path(p.strip()) for p in str(scan_paths_raw).split(";") if p.strip()
        ]
        if not scan_paths:
            return (
                jsonify({"ok": False, "error": "Нет валидных путей для сканирования"}),
                400,
            )

        p = db_path(name)
        ensure_db(p)
        conn = connect(p)
        try:
            pos = get_selected_position()
            stats = scan_seanses_once(conn, scan_paths, client_name=pos or None)
            return jsonify({"ok": True, "db": p.name, "scan": stats, "position": pos})
        finally:
            conn.close()

    @app.get("/api/targeting")
    @login_required
    def api_targeting_list():
        """Получить список активных нацеливаний для текущего пользователя."""
        conn = connect_portal(portal_db_path())
        try:
            pos = get_selected_position()
            targeting = list_targeting(
                conn,
                user_id=int(current_user.id),
                position_name=pos,
                include_read=False,
            )
            return jsonify({"ok": True, "targeting": targeting})
        finally:
            conn.close()

    @app.get("/api/targeting/all")
    @login_required
    def api_targeting_list_all():
        """Получить все нацеливания для текущего пользователя (включая прочитанные)."""
        conn = connect_portal(portal_db_path())
        try:
            pos = get_selected_position()
            # Получаем все позиции пользователя для проверки нацеливаний по позициям
            user_positions = get_user_positions(conn, int(current_user.id))
            targeting = list_targeting(
                conn,
                user_id=int(current_user.id),
                position_name=pos,
                include_read=True,
            )
            # Дополнительно получаем нацеливания для всех позиций пользователя (если позиция не выбрана)
            if user_positions:
                for user_pos in user_positions:
                    if user_pos != pos:  # Не дублируем уже полученные
                        additional = list_targeting(
                            conn,
                            user_id=int(current_user.id),
                            position_name=user_pos,
                            include_read=True,
                        )
                        # Объединяем, избегая дубликатов по ID
                        existing_ids = {t["id"] for t in targeting}
                        for t in additional:
                            if t["id"] not in existing_ids:
                                targeting.append(t)
                                existing_ids.add(t["id"])
            return jsonify({"ok": True, "targeting": targeting})
        finally:
            conn.close()

    @app.post("/api/targeting/read")
    @login_required
    def api_targeting_mark_read():
        """Отметить нацеливание как прочитанное."""
        data = request.get_json(silent=True) or {}
        targeting_id = int(data.get("targeting_id") or 0)
        if not targeting_id:
            return jsonify({"ok": False, "error": "targeting_id обязателен"}), 400
        conn = connect_portal(portal_db_path())
        try:
            mark_targeting_read(
                conn, targeting_id=targeting_id, user_id=int(current_user.id)
            )
            return jsonify({"ok": True})
        finally:
            conn.close()
