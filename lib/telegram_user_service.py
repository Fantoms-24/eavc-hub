"""
Отправка перехватов с личного Telegram-аккаунта (Telethon) внутри HUB.

Конфиг: DATA_DIR/telegram_user_config.json
Сессия:  DATA_DIR/<session_name>.session
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Any

_log = logging.getLogger("web_portal.lib.telegram_user_service")

logger = logging.getLogger("web_portal.telegram_user")

_DEFAULT_CFG: dict[str, Any] = {
    "enabled": False,
    "api_id": 0,
    "api_hash": "",
    "session_name": "tg_user",
    "target": "",
}


def _data_dir() -> Path:
    from web_portal.config import DATA_DIR

    p = Path(DATA_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    return _data_dir() / "telegram_user_config.json"


def load_config() -> dict[str, Any]:
    path = config_path()
    cfg = dict(_DEFAULT_CFG)
    try:
        if path.is_file():
            raw = json.loads(path.read_text(encoding="utf-8") or "{}") or {}
            if isinstance(raw, dict):
                cfg.update({k: v for k, v in raw.items() if v is not None})
    except Exception as exc:
        logger.warning("telegram config read failed: %s", exc)
    try:
        cfg["api_id"] = int(cfg.get("api_id") or 0)
    except Exception:
        cfg["api_id"] = 0
    cfg["api_hash"] = str(cfg.get("api_hash") or "").strip()
    cfg["session_name"] = str(cfg.get("session_name") or "tg_user").strip() or "tg_user"
    cfg["target"] = str(cfg.get("target") or "").strip()
    cfg["enabled"] = bool(cfg.get("enabled"))
    return cfg


def save_config(updates: dict[str, Any]) -> dict[str, Any]:
    cfg = load_config()
    if "enabled" in updates:
        cfg["enabled"] = bool(updates.get("enabled"))
    if "api_id" in updates:
        try:
            cfg["api_id"] = int(updates.get("api_id") or 0)
        except Exception:
            cfg["api_id"] = 0
    if "api_hash" in updates:
        cfg["api_hash"] = str(updates.get("api_hash") or "").strip()
    if "session_name" in updates:
        name = str(updates.get("session_name") or "tg_user").strip() or "tg_user"
        cfg["session_name"] = "".join(c for c in name if c.isalnum() or c in ("_", "-"))[
            :64
        ] or "tg_user"
    if "target" in updates:
        cfg["target"] = str(updates.get("target") or "").strip()
    path = config_path()
    path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def session_file_path(session_name: str | None = None) -> Path:
    cfg = load_config()
    name = str(session_name or cfg.get("session_name") or "tg_user").strip() or "tg_user"
    return _data_dir() / f"{name}.session"


def is_telegram_user_send_enabled() -> bool:
    cfg = load_config()
    if not cfg.get("enabled"):
        return False
    if int(cfg.get("api_id") or 0) <= 0 or not cfg.get("api_hash"):
        return False
    if not cfg.get("target"):
        return False
    return session_file_path(cfg.get("session_name")).is_file()


class _TelethonSender:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client = None
        self._ready = threading.Event()
        self._start_error = ""
        self._target = ""
        self._session_key = ""

    def stop(self) -> None:
        with self._lock:
            loop = self._loop
            client = self._client
            self._client = None
            self._loop = None
            self._ready.clear()
            self._start_error = ""
            self._session_key = ""
        if not loop:
            return

        async def _shutdown() -> None:
            if client:
                try:
                    await client.disconnect()
                except Exception:
                    _log.debug("_shutdown: suppressed error", exc_info=True)

        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), loop)
            fut.result(timeout=5)
        except Exception:
            _log.debug("stop: suppressed error", exc_info=True)
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            _log.debug("stop: suppressed error", exc_info=True)

    def ensure_started(self, *, wait: bool = True, timeout: float = 45.0) -> tuple[bool, str]:
        cfg = load_config()
        if not cfg.get("enabled"):
            self.stop()
            return (False, "отправка выключена")
        api_id = int(cfg.get("api_id") or 0)
        api_hash = str(cfg.get("api_hash") or "")
        session_name = str(cfg.get("session_name") or "tg_user")
        target = str(cfg.get("target") or "").strip()
        if api_id <= 0 or not api_hash:
            return (False, "укажите api_id и api_hash (my.telegram.org)")
        if not target:
            return (False, "укажите target (@username или телефон)")
        sess = session_file_path(session_name)
        if not sess.is_file():
            return (
                False,
                "нет сессии — выполните вход во вкладке Telegram (телефон + код)",
            )
        key = f"{sess}|{api_id}|{api_hash}|{target}"
        with self._lock:
            if self._client and self._session_key == key and self._ready.is_set():
                if self._start_error:
                    return (False, self._start_error)
                return (True, "")
            # Уже стартуем в фоне — не дёргаем повторно.
            if (
                self._thread
                and self._thread.is_alive()
                and self._session_key == key
                and not self._ready.is_set()
            ):
                if not wait:
                    return (False, "подключение к Telegram…")
                if not self._ready.wait(timeout=float(timeout or 45)):
                    return (False, "Telethon не успел запуститься")
                if self._start_error:
                    return (False, self._start_error)
                return (True, "")
        self.stop()
        self._target = target
        self._session_key = key
        self._ready.clear()
        self._start_error = ""
        self._thread = threading.Thread(
            target=self._thread_main,
            args=(str(sess.with_suffix("")), api_id, api_hash),
            name="telegram-user-loop",
            daemon=True,
        )
        self._thread.start()
        if not wait:
            return (False, "подключение к Telegram…")
        if not self._ready.wait(timeout=float(timeout or 45)):
            return (False, "Telethon не успел запуститься")
        if self._start_error:
            return (False, self._start_error)
        return (True, "")

    def _thread_main(self, session_path: str, api_id: int, api_hash: str) -> None:
        try:
            from telethon import TelegramClient
        except ImportError:
            self._start_error = "не установлен telethon (pip install telethon)"
            self._ready.set()
            return
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop

        async def _boot() -> None:
            client = TelegramClient(session_path, api_id, api_hash)
            # Не висим бесконечно, если Telegram недоступен (прокси/фаервол).
            await asyncio.wait_for(client.connect(), timeout=20.0)
            if not await client.is_user_authorized():
                await client.disconnect()
                raise RuntimeError("сессия не авторизована — войдите заново")
            self._client = client

        try:
            loop.run_until_complete(_boot())
        except Exception as exc:
            self._start_error = str(exc)
            self._ready.set()
            try:
                loop.close()
            except Exception:
                _log.debug("_boot: suppressed error", exc_info=True)
            self._loop = None
            return
        self._ready.set()
        logger.info("Telegram user client connected")
        loop.run_forever()

    def send_text(self, text: str, timeout_sec: float = 15.0) -> tuple[bool, str]:
        ok, err = self.ensure_started()
        if not ok:
            return (False, err)
        body = str(text or "").strip()
        if not body:
            return (False, "пустой текст")
        loop = self._loop
        client = self._client
        target = self._target
        if not loop or not client:
            return (False, "клиент не готов")

        async def _send():
            await client.send_message(
                target, body, parse_mode="html", link_preview=False
            )

        try:
            fut = asyncio.run_coroutine_threadsafe(_send(), loop)
            fut.result(timeout=float(timeout_sec or 15))
            return (True, "")
        except Exception as exc:
            return (False, str(exc))


_SENDER = _TelethonSender()
_LOGIN_LOCK = threading.Lock()
_LOGIN: dict[str, Any] = {
    "loop": None,
    "thread": None,
    "client": None,
    "phone": "",
    "phone_code_hash": "",
    "ready": threading.Event(),
}


def _login_run(coro, timeout: float = 60.0):
    loop = _LOGIN.get("loop")
    if not loop:
        return False, "login loop not ready", None
    try:
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return True, "", fut.result(timeout=timeout)
    except Exception as exc:
        return False, str(exc), None


def _login_ensure_loop() -> None:
    if _LOGIN.get("loop") and _LOGIN.get("thread") and _LOGIN["thread"].is_alive():
        return
    ready = threading.Event()

    def _main() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        _LOGIN["loop"] = loop
        ready.set()
        loop.run_forever()

    t = threading.Thread(target=_main, name="telegram-login-loop", daemon=True)
    _LOGIN["thread"] = t
    t.start()
    ready.wait(timeout=10)


async def _login_disconnect_client() -> None:
    client = _LOGIN.get("client")
    _LOGIN["client"] = None
    if client is not None:
        try:
            await client.disconnect()
        except Exception:
            _log.debug("_login_disconnect_client: suppressed error", exc_info=True)


def get_status() -> dict[str, Any]:
    cfg = load_config()
    sess = session_file_path(cfg.get("session_name"))
    authorized = sess.is_file()
    sender_ok = False
    sender_err = ""
    if cfg.get("enabled") and authorized:
        # Не блокируем HTTP: только статус / фоновый старт.
        sender_ok, sender_err = _SENDER.ensure_started(wait=False)
        if _SENDER._ready.is_set() and not _SENDER._start_error and _SENDER._client:
            sender_ok = True
            sender_err = ""
        elif _SENDER._ready.is_set() and _SENDER._start_error:
            sender_ok = False
            sender_err = _SENDER._start_error
    return {
        "ok": True,
        "config": {
            "enabled": bool(cfg.get("enabled")),
            "api_id": int(cfg.get("api_id") or 0),
            "api_hash": str(cfg.get("api_hash") or ""),
            "session_name": str(cfg.get("session_name") or "tg_user"),
            "target": str(cfg.get("target") or ""),
        },
        "session_exists": authorized,
        "session_path": str(sess),
        "sender_ready": bool(sender_ok),
        "sender_error": sender_err,
        "login_phone": str(_LOGIN.get("phone") or ""),
        "login_pending": bool(_LOGIN.get("phone_code_hash")),
    }


def apply_settings_and_maybe_start(updates: dict[str, Any]) -> dict[str, Any]:
    cfg = save_config(updates)
    _SENDER.stop()
    if cfg.get("enabled") and session_file_path(cfg.get("session_name")).is_file():
        _SENDER.ensure_started(wait=False)
    return get_status()


def login_send_code(phone: str) -> dict[str, Any]:
    phone = str(phone or "").strip()
    if not phone:
        return {"ok": False, "error": "укажите телефон (+7…)"}
    cfg = load_config()
    api_id = int(cfg.get("api_id") or 0)
    api_hash = str(cfg.get("api_hash") or "")
    if api_id <= 0 or not api_hash:
        return {"ok": False, "error": "сначала сохраните api_id и api_hash"}
    session_path = str(session_file_path(cfg.get("session_name")).with_suffix(""))
    with _LOGIN_LOCK:
        _login_ensure_loop()
        _login_run(_login_disconnect_client(), timeout=15)
        _LOGIN["phone"] = phone
        _LOGIN["phone_code_hash"] = ""

        async def _do():
            from telethon import TelegramClient

            client = TelegramClient(session_path, api_id, api_hash)
            await client.connect()
            result = await client.send_code_request(phone)
            _LOGIN["client"] = client
            return str(result.phone_code_hash or "")

        ok, err, phone_code_hash = _login_run(_do(), timeout=60)
        if not ok:
            _LOGIN["client"] = None
            return {"ok": False, "error": err or "не удалось отправить код"}
        _LOGIN["phone_code_hash"] = str(phone_code_hash or "")
        return {"ok": True, "phone": phone, "message": "код отправлен в Telegram"}


def login_confirm(code: str, password: str = "") -> dict[str, Any]:
    code = str(code or "").strip()
    password = str(password or "").strip()
    if not code and not password:
        return {"ok": False, "error": "укажите код из Telegram"}
    with _LOGIN_LOCK:
        client = _LOGIN.get("client")
        phone = str(_LOGIN.get("phone") or "")
        phone_code_hash = str(_LOGIN.get("phone_code_hash") or "")
        if client is None or not phone or not phone_code_hash:
            return {"ok": False, "error": "сначала нажмите «Отправить код»"}

        async def _sign_in():
            from telethon.errors import SessionPasswordNeededError

            try:
                if code:
                    await client.sign_in(
                        phone=phone, code=code, phone_code_hash=phone_code_hash
                    )
            except SessionPasswordNeededError:
                if not password:
                    raise RuntimeError("нужен пароль 2FA — введите и подтвердите снова")
                await client.sign_in(password=password)
            else:
                if password:
                    try:
                        await client.sign_in(password=password)
                    except Exception:
                        _log.debug("_sign_in: suppressed error", exc_info=True)
            me = await client.get_me()
            await client.disconnect()
            _LOGIN["client"] = None
            return me

        ok, err, me = _login_run(_sign_in(), timeout=60)
        _LOGIN["phone"] = ""
        _LOGIN["phone_code_hash"] = ""
        if not ok:
            return {"ok": False, "error": err or "вход не удался"}
        _SENDER.stop()
        uname = getattr(me, "username", None) or ""
        return {
            "ok": True,
            "message": f"вход выполнен (id={getattr(me, 'id', '')} @{uname})".strip(),
            "status": get_status(),
        }


def logout_session() -> dict[str, Any]:
    cfg = load_config()
    _SENDER.stop()
    with _LOGIN_LOCK:
        if _LOGIN.get("loop"):
            _login_run(_login_disconnect_client(), timeout=15)
        _LOGIN["phone"] = ""
        _LOGIN["phone_code_hash"] = ""
    sess = session_file_path(cfg.get("session_name"))
    for p in (sess, Path(str(sess) + "-journal")):
        try:
            if p.is_file():
                p.unlink()
        except Exception:
            _log.debug("logout_session: suppressed error", exc_info=True)
    return {"ok": True, "status": get_status()}


def render_intercept_html(payload: dict[str, Any]) -> str:
    from html import escape
    import re

    freq = escape(str(payload.get("frequency") or "").strip())
    group = escape(str(payload.get("group_code") or "").strip())
    body = str(payload.get("delta_text") or payload.get("full_content") or "").strip()
    body_escaped = escape(body)
    raw_cs = payload.get("callsigns")
    callsigns: list[tuple[str, str]] = []
    if isinstance(raw_cs, list):
        for item in raw_cs:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            label = str(item.get("label") or "").strip() or "н/у"
            if code:
                callsigns.append((label, code))
    if not callsigns:
        seen: set[str] = set()
        for m in re.finditer(r"\((\d{1,10})\)", body):
            code = str(m.group(1) or "").strip()
            if code and code not in seen:
                seen.add(code)
                callsigns.append(("н/у", code))
    lines: list[str] = []
    if freq:
        lines.append(f"Частота: {freq}")
    if group:
        lines.append(f"Групповой ID: {group}")
    if callsigns:
        if lines:
            lines.append("")
        for label, code in callsigns:
            lines.append(f"{escape(label)} - {escape(code)}")
    if body_escaped:
        if lines:
            lines.append("")
        lines.append(body_escaped)
    return "\n".join(lines)


def try_send_intercept_telegram(payload: dict[str, Any]) -> tuple[bool, str]:
    """Отправить сформированный payload. False если выключено / ошибка."""
    if not is_telegram_user_send_enabled():
        return (False, "disabled")
    text = render_intercept_html(payload or {})
    if not text.strip():
        return (False, "empty")
    ok, err = _SENDER.send_text(text)
    if ok:
        logger.info(
            "telegram user send ok item=%s target=%s",
            str((payload or {}).get("item_uuid") or ""),
            load_config().get("target"),
        )
    else:
        logger.warning("telegram user send failed: %s", err)
    return (ok, err)


def start_telegram_user_service_if_enabled() -> None:
    """Вызов при старте create_app / HUB — только фон, без блокировки Flask."""
    try:
        if not load_config().get("enabled"):
            return
        ok, err = _SENDER.ensure_started(wait=False)
        if ok:
            logger.info("Telegram user sender ready → %s", load_config().get("target"))
        else:
            logger.info("Telegram user sender starting in background: %s", err)
    except Exception as exc:
        logger.warning("Telegram user service start skipped: %s", exc)


def send_test_message() -> dict[str, Any]:
    cfg = load_config()
    text = (
        f"Тест EAVC HUB\n"
        f"Частота: 151.0000\n"
        f"Групповой ID: 870200\n\n"
        f"Цель: {cfg.get('target') or '—'}"
    )
    ok, err = _SENDER.send_text(text)
    return {"ok": ok, "error": err or "", "target": cfg.get("target") or ""}
