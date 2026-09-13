"""Хелперы безопасности: секретный ключ приложения и rate-limit логина.

Вынесено из app.py (изначально ключ имел небезопасный fallback
"change-me-in-prod", а /login не ограничивал перебор паролей).
"""

from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from pathlib import Path

_log = logging.getLogger("web_portal.webapp.security")

_SECRET_FILE_NAME = ".secret_key"


def resolve_secret_key(data_dir: Path) -> str:
    """Секретный ключ Flask-сессий.

    Приоритет:
    1) WEB_PORTAL_SECRET из окружения;
    2) персистентный файл ``<data_dir>/.secret_key`` (генерируется один раз,
       чтобы сессии переживали рестарт сервера).

    Небезопасного константного fallback больше нет: подделать cookie сессии
    зная дефолт из исходников — полный обход авторизации.
    """
    env = (os.environ.get("WEB_PORTAL_SECRET") or "").strip()
    if env:
        return env

    key_file = Path(data_dir) / _SECRET_FILE_NAME
    try:
        if key_file.is_file():
            stored = key_file.read_text(encoding="utf-8").strip()
            if len(stored) >= 32:
                return stored
    except Exception:
        _log.debug("resolve_secret_key: не удалось прочитать %s", key_file, exc_info=True)

    key = secrets.token_hex(32)
    try:
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass  # Windows/FAT — chmod может быть недоступен
        _log.warning(
            "WEB_PORTAL_SECRET не задан — сгенерирован персистентный ключ в %s",
            key_file,
        )
    except Exception:
        # не смогли сохранить — работаем с эфемерным ключом (сессии до рестарта)
        _log.warning(
            "WEB_PORTAL_SECRET не задан и не удалось записать %s — "
            "используется эфемерный ключ (сессии не переживут рестарт)",
            key_file,
            exc_info=True,
        )
    return key


CSRF_SESSION_KEY = "_csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


def ensure_csrf_token(session) -> str:
    """Возвращает CSRF-токен сессии, создавая его при первом обращении."""
    token = session.get(CSRF_SESSION_KEY)
    if not token or not isinstance(token, str) or len(token) < 32:
        token = secrets.token_hex(32)
        session[CSRF_SESSION_KEY] = token
    return token


def csrf_request_valid(session, request) -> bool:
    """Проверяет CSRF-токен запроса (заголовок или поле формы).

    Сравнение через ``secrets.compare_digest`` — без timing-утечек.
    """
    expected = session.get(CSRF_SESSION_KEY)
    if not expected:
        return False
    got = (request.headers.get(CSRF_HEADER) or "").strip()
    if not got:
        got = (request.form.get(CSRF_FORM_FIELD) or "").strip()
    return bool(got) and secrets.compare_digest(got, expected)


class LoginRateLimiter:
    """Простой in-memory rate-limit по ключу (IP или IP+username).

    После ``max_attempts`` неудачных попыток за ``window_sec`` секунд ключ
    блокируется на ``lockout_sec`` секунд. Успешный вход сбрасывает счётчик.
    Память процесса: подходит для одного экземпляра waitress (наш случай).
    """

    def __init__(
        self,
        max_attempts: int = 8,
        window_sec: float = 300.0,
        lockout_sec: float = 120.0,
    ):
        self.max_attempts = max_attempts
        self.window_sec = window_sec
        self.lockout_sec = lockout_sec
        self._lock = threading.Lock()
        # key -> (список ts неудач, ts конца блокировки | 0)
        self._state: dict[str, tuple[list[float], float]] = {}

    def _prune(self, now: float) -> None:
        if len(self._state) < 4096:
            return
        dead = [
            k
            for k, (fails, until) in self._state.items()
            if until < now and (not fails or fails[-1] < now - self.window_sec)
        ]
        for k in dead:
            self._state.pop(k, None)

    def blocked_for(self, key: str) -> float:
        """Сколько секунд осталось до разблокировки (0 — не заблокирован)."""
        now = time.monotonic()
        with self._lock:
            fails, until = self._state.get(key, ([], 0.0))
            return max(0.0, until - now)

    def register_failure(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._prune(now)
            fails, until = self._state.get(key, ([], 0.0))
            fails = [t for t in fails if t >= now - self.window_sec]
            fails.append(now)
            if len(fails) >= self.max_attempts:
                until = now + self.lockout_sec
                fails = []
                _log.warning("login rate-limit: ключ %r заблокирован на %.0f c", key, self.lockout_sec)
            self._state[key] = (fails, until)

    def register_success(self, key: str) -> None:
        with self._lock:
            self._state.pop(key, None)
