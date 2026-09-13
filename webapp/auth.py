"""Авторизация и доступ к вкладкам: PortalUser, require_perm, require_tab.

Вынесено из app.py без изменения поведения.
"""

from __future__ import annotations

from flask import jsonify, redirect, request, url_for
from flask_login import UserMixin, current_user, login_required

from web_portal.lib.auth_db import UserRecord


class PortalUser(UserMixin):
    def __init__(self, record: UserRecord):
        self._r = record

    @property
    def id(self) -> str:  # flask-login
        return str(self._r.id)

    @property
    def username(self) -> str:
        return self._r.username

    @property
    def callsign(self) -> str:
        return self._r.callsign

    @property
    def role(self) -> str:
        return self._r.role

    def has_perm(self, perm: str) -> bool:
        return self._r.has_perm(perm)


def require_perm(perm: str):
    def deco(fn):
        @login_required
        def wrapper(*args, **kwargs):
            if not current_user.has_perm(perm):
                return jsonify({"ok": False, "error": f"Нет прав: {perm}"}), 403
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        return wrapper

    return deco


MOBILE_PRIMARY_TABS = {"tab_audio_intercepts"}


def _request_is_mobile_shell() -> bool:
    """Best-effort mobile detection for page-level navigation guards."""
    ch_mobile = (request.headers.get("Sec-CH-UA-Mobile") or "").strip().lower()
    if ch_mobile in {"?1", "1", "true"}:
        return True
    ua = (request.headers.get("User-Agent") or "").lower()
    if not ua:
        return False
    mobile_tokens = (
        "android",
        "iphone",
        "ipod",
        "mobile",
        "windows phone",
        "blackberry",
        "opera mini",
    )
    return any(t in ua for t in mobile_tokens)


def _request_wants_json() -> bool:
    return (
        request.accept_mimetypes.best_match(["application/json", "text/html"])
        == "application/json"
    )


def _mobile_primary_url() -> str | None:
    if current_user.is_authenticated and current_user.has_perm("tab_audio_intercepts"):
        return url_for("audio_intercepts")
    return None


def require_tab(tab_perm: str):
    """Доступ к разделу по праву вкладки (галочка в роли)."""

    def deco(fn):
        @login_required
        def wrapper(*args, **kwargs):
            if not current_user.has_perm(tab_perm):
                if _request_wants_json():
                    return (
                        jsonify(
                            {"ok": False, "error": f"Нет доступа к разделу: {tab_perm}"}
                        ),
                        403,
                    )
                return redirect(url_for("index"))
            if (
                _request_is_mobile_shell()
                and tab_perm not in MOBILE_PRIMARY_TABS
                and not _request_wants_json()
            ):
                target = _mobile_primary_url()
                if target and request.path != target:
                    return redirect(target)
            return fn(*args, **kwargs)

        wrapper.__name__ = fn.__name__
        return wrapper

    return deco
