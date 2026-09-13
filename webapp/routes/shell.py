"""Оболочка UI: главная, вкладки, set-position и прочие «страничные» маршруты. Извлечено из app.py дословно."""

from __future__ import annotations

import logging
import os
import string
from pathlib import Path

from flask import jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required

from web_portal.app_perf import perf_route as _perf_route
from web_portal.config import DATA_DIR, deploy_announce_path, portal_db_path
from web_portal.lib.auth_db import (
    TAB_CATEGORIES,
    connect_portal,
    delete_custom_role,
    update_custom_role,
)
from web_portal.lib.db import connect
from web_portal.lib.deploy_announce import read_announce
from web_portal.positions import allowed_positions_for_current_user, get_selected_position
from web_portal.webapp.auth import (
    _mobile_primary_url,
    _request_is_mobile_shell,
    require_perm,
    require_tab,
)
from web_portal.webapp.context import AppContext

_log = logging.getLogger("web_portal.webapp.routes.shell")


def register_shell_routes(app, ctx: AppContext):
    """Регистрирует маршруты оболочки UI. Код перенесён из create_app дословно."""

    def _first_allowed_tab_route():
        """Первый раздел, к которому у пользователя есть доступ (по вкладкам)."""
        if _request_is_mobile_shell():
            mobile_url = _mobile_primary_url()
            if mobile_url:
                return mobile_url
        for tab_id, _ in TAB_CATEGORIES:
            if current_user.has_perm(tab_id):
                route_map = {
                    "tab_intercepts": "intercepts",
                    "tab_audio_intercepts": "audio_intercepts",
                    "tab_aviation": "aviation",
                    "tab_sessions": "sessions",
                    "tab_analysis": "analysis",
                    "tab_search_online": "search_online",
                    "tab_instructions": "instruction",
                    "tab_admin": "admin_users",
                }
                name = route_map.get(tab_id)
                if name:
                    return url_for(name)
        return url_for("intercepts")

    @app.get("/set-position/<pos>")
    @login_required
    def set_position(pos: str):
        allowed = allowed_positions_for_current_user()
        pos = (pos or "").strip()
        if current_user.role == "admin":
            # спец-токен для "все позиции"
            session["position"] = "" if pos == "__all__" else pos
        else:
            if pos in allowed:
                session["position"] = pos
        # Возвращаем на страницу, откуда пришли (sessions/intercepts/и т.д.)
        referer = request.headers.get("Referer") or ""
        try:
            # простой safe-check: редиректим только на наш хост
            if referer and referer.startswith(request.host_url):
                return redirect(referer)
        except Exception:
            _log.debug("set_position: suppressed error", exc_info=True)
        # fallback
        return redirect(url_for("sessions"))

    @app.get("/")
    @login_required
    def index():
        return redirect(_first_allowed_tab_route())

    @app.get("/audio-intercepts")
    @login_required
    @require_tab("tab_audio_intercepts")
    def audio_intercepts():
        return render_template("intercepts.html", page_mode="audio", show_audio=True)

    @app.get("/search-online")
    @login_required
    @require_tab("tab_search_online")
    def search_online():
        # смотреть могут все, редактировать — по праву edit_search (в UI и API)
        return render_template("search_online.html")

    @app.get("/search-online/unit")
    @login_required
    @require_tab("tab_search_online")
    def search_online_unit_parent_page():
        return render_template("search_online_unit_parent.html")

    @app.get("/search-online/battalion")
    @login_required
    @require_tab("tab_search_online")
    def search_online_battalion_page():
        return render_template("search_online_battalion.html")

    @app.get("/instruction")
    @login_required
    @require_tab("tab_instructions")
    def instruction():
        """Пошаговая инструкция по работе с порталом."""
        return render_template("instruction.html")

    @app.get("/api/pick-folder")
    @require_perm("import_folder")
    def api_pick_folder():
        """
        Возвращает список доступных дисков и часто используемых папок.
        Вместо tkinter используем простой список для выбора.
        """
        try:
            # Диски Windows: GetDriveType, без os.path.exists — иначе зависание
            # на недоступных/сетевых буквах (см. hang на GET /api/pick-folder).
            drives: list[str] = []
            if os.name == "nt":
                import ctypes

                get_drive_type = ctypes.windll.kernel32.GetDriveTypeW
                # 2=REMOVABLE, 3=FIXED, 5=CDROM, 6=RAMDISK — не трогаем REMOTE(4)
                ready = {2, 3, 5, 6}
                for letter in string.ascii_uppercase:
                    root = f"{letter}:\\"
                    if int(get_drive_type(root)) in ready:
                        drives.append(root)

            home = Path.home()
            common_paths = [
                str(home),
                str(home / "Desktop"),
                str(home / "Documents"),
                str(home / "Downloads"),
            ]
            valid_paths = [p for p in common_paths if os.path.exists(p)]

            return jsonify(
                {
                    "ok": True,
                    "drives": drives,
                    "common_paths": valid_paths,
                    "current_dir": str(Path.cwd()),
                    "message": "Введите путь к папке вручную или используйте предложенные варианты",
                }
            )
        except Exception as e:
            return (
                jsonify({"ok": False, "error": f"Ошибка получения путей: {e}"}),
                400,
            )

    @app.post("/api/legacy-db/upload")
    @login_required
    def api_upload_legacy_db():
        # только модератор/админ (используем существующие пермишены)
        if not (
            current_user.has_perm("import_folder")
            or current_user.has_perm("manage_users")
        ):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        f = request.files.get("file")
        if not f:
            return jsonify({"ok": False, "error": "Файл не передан"}), 400
        filename = (f.filename or "").lower()
        if not (filename.endswith(".sqlite") or filename.endswith(".db")):
            return jsonify({"ok": False, "error": "Нужен файл .sqlite/.db"}), 400

        target = (DATA_DIR / "database.sqlite").resolve()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            f.save(str(target))
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)}), 500

        # проверка: показываем только seanses + unit (как в основной программе)
        try:
            conn = connect(target)
            try:
                cur = conn.cursor()
                tables = cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name LIMIT 50"
                ).fetchall()
                table_names = [str(r[0]) for r in tables] if tables else []
                wanted = [t for t in ["seanses", "unit"] if t in table_names]
                stats = {}
                for t in wanted:
                    try:
                        stats[t] = int(
                            cur.execute(f"SELECT COUNT(*) FROM {t};").fetchone()[0]
                        )
                    except Exception:
                        stats[t] = None
            finally:
                conn.close()
        except Exception as e:
            return jsonify(
                {
                    "ok": True,
                    "saved_as": target.name,
                    "warning": f"SQLite check failed: {e}",
                }
            )

        return jsonify(
            {
                "ok": True,
                "saved_as": target.name,
                "tables": wanted,
                "stats": stats,
                "missing": [t for t in ["seanses", "unit"] if t not in table_names],
            }
        )

    @app.get("/api/client/deploy-announce")
    @_perf_route("api/client/deploy-announce")
    @login_required
    def api_client_deploy_announce():
        """Штамп «есть новая версия веб-интерфейса» — поллинг открытых вкладок в ЛВС."""
        ann = read_announce(deploy_announce_path())
        return jsonify({"ok": True, **ann})

    @app.put("/api/admin/roles/<int:role_id>")
    @require_perm("tab_admin")
    def api_admin_update_custom_role(role_id: int):
        """Обновить кастомную роль."""
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        permissions = data.get("permissions") or []
        if not name:
            return jsonify({"ok": False, "error": "Имя роли обязательно"}), 400
        conn = connect_portal(portal_db_path())
        try:
            update_custom_role(conn, role_id, name, permissions)
            return jsonify({"ok": True})
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            conn.close()

    @app.delete("/api/admin/roles/<int:role_id>")
    @require_perm("tab_admin")
    def api_admin_delete_custom_role(role_id: int):
        """Удалить кастомную роль."""
        conn = connect_portal(portal_db_path())
        try:
            delete_custom_role(conn, role_id)
            return jsonify({"ok": True})
        finally:
            conn.close()
