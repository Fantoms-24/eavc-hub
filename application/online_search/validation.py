"""Общая валидация входных параметров поиска онлайн."""

from __future__ import annotations

from web_portal.application.online_search.errors import OnlineSearchUseCaseHTTP


def validate_unit_key(unit_key: str) -> None:
    if not unit_key:
        raise OnlineSearchUseCaseHTTP(400, {"ok": False, "error": "key обязателен"})
    if len(unit_key) > 4000:
        raise OnlineSearchUseCaseHTTP(400, {"ok": False, "error": "key слишком длинный"})


def validate_parent_key(parent_key: str) -> None:
    if not parent_key:
        raise OnlineSearchUseCaseHTTP(400, {"ok": False, "error": "p обязателен"})


def validate_battalion_key(unit_key: str) -> None:
    if not unit_key:
        raise OnlineSearchUseCaseHTTP(400, {"ok": False, "error": "k обязателен"})
