"""Страницы входа/выхода и принудительной смены пароля. Извлечено из app.py дословно."""

from __future__ import annotations

import logging

from flask import jsonify, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from web_portal.config import DEFAULT_DB_NAME, db_path, portal_db_path
from web_portal.lib.auth_db import (
    connect_portal,
    get_user_sync_payload_by_id,
    update_user_password,
    verify_login,
)
from web_portal.lib.db import connect, enqueue_sync_outbox
from web_portal.webapp.auth import PortalUser, _request_wants_json
from web_portal.webapp.context import AppContext

_log = logging.getLogger("web_portal.webapp.routes.auth_pages")


def register_auth_pages_routes(app, ctx: AppContext):
    """Регистрирует маршруты аутентификации. Код перенесён из create_app дословно."""

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return render_template("login.html", message="", error=False)
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        rl_key = f"{request.remote_addr or '?'}|{username[:64].lower()}"
        wait = ctx.login_rate_limiter.blocked_for(rl_key)
        if wait > 0:
            ctx.log_portal_event(
                level="WARNING",
                category="auth",
                action="login_rate_limited",
                message=f"Блокировка перебора: {username[:64]} (ещё {wait:.0f} c)",
                username=username,
                ip=str(request.remote_addr or ""),
                path="/login",
                method="POST",
            )
            return (
                render_template(
                    "login.html",
                    message=f"Слишком много попыток. Повторите через {int(wait) + 1} с",
                    error=True,
                ),
                429,
            )
        conn = connect_portal(portal_db_path())
        try:
            u = verify_login(conn, username, password)
        finally:
            conn.close()
        if not u:
            ctx.login_rate_limiter.register_failure(rl_key)
            ctx.log_portal_event(
                level="WARNING",
                category="auth",
                action="login_failed",
                message=f"Неудачный вход: {username[:64]}",
                username=username,
                ip=str(request.remote_addr or ""),
                path="/login",
                method="POST",
            )
            return render_template(
                "login.html", message="Неверный логин/пароль", error=True
            )
        ctx.login_rate_limiter.register_success(rl_key)
        login_user(PortalUser(u))
        if password == "admin":
            # вход со стандартным паролем — принудительная смена
            session["force_pw_change"] = True
            ctx.log_portal_event(
                level="WARNING",
                category="auth",
                action="default_password_login",
                message=f"Вход со стандартным паролем: {u.username}",
                user_id=int(u.id),
                username=str(u.username or ""),
                ip=str(request.remote_addr or ""),
                path="/login",
                method="POST",
            )
            return redirect(url_for("force_password_change"))
        ctx.log_portal_event(
            level="INFO",
            category="auth",
            action="login_ok",
            message=f"Вход: {u.username}",
            user_id=int(u.id),
            username=str(u.username or ""),
            ip=str(request.remote_addr or ""),
            path="/login",
            method="POST",
        )
        # Временно перенаправляем на перехваты вместо сеансов
        return redirect(url_for("intercepts"))

    @app.before_request
    def _enforce_password_change():
        """Пока не сменён стандартный пароль — пускаем только на смену/выход."""
        if not session.get("force_pw_change"):
            return None
        allowed = {"force_password_change", "logout", "static", "login"}
        if request.endpoint in allowed:
            return None
        if _request_wants_json():
            return (
                jsonify({"ok": False, "error": "Требуется смена стандартного пароля"}),
                403,
            )
        return redirect(url_for("force_password_change"))

    @app.route("/force-password-change", methods=["GET", "POST"])
    @login_required
    def force_password_change():
        if request.method == "GET":
            return render_template("force_password_change.html", message="")
        new_pw = request.form.get("new_password") or ""
        confirm = request.form.get("confirm_password") or ""
        if len(new_pw) < 8:
            return render_template(
                "force_password_change.html", message="Пароль короче 8 символов"
            )
        if new_pw != confirm:
            return render_template(
                "force_password_change.html", message="Пароли не совпадают"
            )
        if new_pw == "admin" or new_pw.lower() in {"password", "12345678", "admin123"}:
            return render_template(
                "force_password_change.html", message="Этот пароль слишком простой"
            )
        user_id = int(current_user.id)
        conn = connect_portal(portal_db_path())
        try:
            update_user_password(conn, user_id, new_pw)
            if ctx.sync_upstream and ctx.sync_key:
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
                    _log.debug(
                        "force_password_change: suppressed error", exc_info=True
                    )
        finally:
            conn.close()
        session.pop("force_pw_change", None)
        ctx.log_portal_event(
            level="INFO",
            category="auth",
            action="password_changed",
            message=f"Смена стандартного пароля: {current_user.username}",
            user_id=user_id,
            username=str(current_user.username or ""),
            ip=str(request.remote_addr or ""),
            path="/force-password-change",
            method="POST",
        )
        return redirect(url_for("intercepts"))

    @app.get("/logout")
    @login_required
    def logout():
        ctx.log_portal_event(
            level="INFO",
            category="auth",
            action="logout",
            message=f"Выход: {current_user.username}",
            user_id=int(current_user.id),
            username=str(current_user.username or ""),
            ip=str(request.remote_addr or ""),
            path="/logout",
            method="GET",
        )
        logout_user()
        return redirect(url_for("login"))
