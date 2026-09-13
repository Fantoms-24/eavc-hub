from __future__ import annotations

import asyncio
import json
import sys
import threading
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import request as urlrequest
import logging

_log = logging.getLogger("web_portal.telegram_receiver_main")


def _root_dir() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_or_create_config(cfg_path: Path) -> dict:
    default_cfg = {
        "bind_host": "0.0.0.0",
        "port": 8787,
        "listen_path": "/api/intercepts/telegram",
        "secret_key": "",
        "request_timeout_sec": 10,
        # "user" — личный аккаунт (Telethon); "bot" — Bot API
        "send_mode": "user",
        "api_id": 0,
        "api_hash": "",
        "session_name": "tg_user",
        "target": "",
        "bot_token": "",
        "chat_id": "",
        # Форум-супергруппа (только режим bot)
        "default_message_thread_id": None,
        "topic_by_unit": {},
    }
    try:
        if not cfg_path.exists():
            cfg_path.write_text(
                json.dumps(default_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return dict(default_cfg)
        data = json.loads(cfg_path.read_text(encoding="utf-8") or "{}") or {}
        if not isinstance(data, dict):
            return dict(default_cfg)
        merged = dict(default_cfg)
        merged.update({k: v for k, v in data.items() if v is not None})
        return merged
    except Exception:
        return dict(default_cfg)


def _parse_thread_id(v) -> int | None:
    if v is None:
        return None
    if isinstance(v, int):
        return v if v > 0 else None
    try:
        n = int(str(v).strip())
        return n if n > 0 else None
    except Exception:
        return None


def _resolve_message_thread_id(payload: dict, cfg: dict) -> int | None:
    """
    Ищем topic (message_thread_id) по полю unit_name из перехвата.
    Сопоставление — по точному совпадению строки (после strip) с ключом в topic_by_unit.
    """
    u = str(payload.get("unit_name") or "").strip()
    raw_map = cfg.get("topic_by_unit") or {}
    if isinstance(raw_map, dict) and u:
        tid = raw_map.get(u)
        if tid is None:
            tid = raw_map.get(u.replace("ё", "е"))
        tt = _parse_thread_id(tid)
        if tt is not None:
            return tt
    return _parse_thread_id(cfg.get("default_message_thread_id"))


def _send_telegram_bot_message(
    bot_token: str,
    chat_id: str,
    text: str,
    timeout_sec: float,
    *,
    message_thread_id: int | None = None,
) -> tuple[bool, str]:
    token = str(bot_token or "").strip()
    chat = str(chat_id or "").strip()
    if not token:
        return (False, "bot_token is empty")
    if not chat:
        return (False, "chat_id is empty")
    payload = {
        "chat_id": chat,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if message_thread_id is not None and message_thread_id > 0:
        payload["message_thread_id"] = int(message_thread_id)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(
        url=url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlrequest.urlopen(req, timeout=float(timeout_sec or 10)) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            if 200 <= int(resp.status) < 300:
                try:
                    parsed = json.loads(body or "{}")
                    if parsed.get("ok") is True:
                        return (True, "")
                    return (False, f"telegram api error: {body[:300]}")
                except Exception:
                    return (True, "")
            return (False, f"http {int(resp.status)}: {body[:300]}")
    except Exception as exc:
        return (False, str(exc))


class TelethonUserSender:
    """Фоновый asyncio-loop + Telethon client для отправки с личного аккаунта."""

    def __init__(
        self,
        *,
        root: Path,
        api_id: int,
        api_hash: str,
        session_name: str,
        target: str,
    ) -> None:
        self.root = root
        self.api_id = int(api_id)
        self.api_hash = str(api_hash or "").strip()
        self.session_name = str(session_name or "tg_user").strip() or "tg_user"
        self.target = str(target or "").strip()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._client = None
        self._ready = threading.Event()
        self._start_error = ""

    def start(self) -> None:
        if not self.target:
            raise RuntimeError("target пуст — укажите @username или телефон контакта в конфиге")
        if self.api_id <= 0 or not self.api_hash:
            raise RuntimeError("api_id/api_hash пусты — возьмите на https://my.telegram.org")
        session_file = self.root / f"{self.session_name}.session"
        if not session_file.exists():
            raise RuntimeError(
                f"Нет файла сессии {session_file.name}. "
                "Сначала запустите telegram_user_login.py (или TG_USER_LOGIN.exe)."
            )
        self._thread = threading.Thread(
            target=self._thread_main, name="telethon-loop", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(timeout=45):
            raise RuntimeError("Telethon не успел запуститься (timeout)")
        if self._start_error:
            raise RuntimeError(self._start_error)

    def _thread_main(self) -> None:
        try:
            from telethon import TelegramClient
        except ImportError:
            self._start_error = "Не установлен telethon (pip install telethon)"
            self._ready.set()
            return
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        async def _boot() -> None:
            session_path = str((self.root / self.session_name).resolve())
            client = TelegramClient(session_path, self.api_id, self.api_hash)
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                raise RuntimeError(
                    "Сессия не авторизована. Запустите telegram_user_login.py заново."
                )
            self._client = client

        try:
            self._loop.run_until_complete(_boot())
        except Exception as exc:
            self._start_error = str(exc)
            self._ready.set()
            try:
                self._loop.close()
            except Exception:
                _log.debug("_boot: suppressed error", exc_info=True)
            return
        self._ready.set()
        self._loop.run_forever()

    def send(self, text: str, timeout_sec: float = 10.0) -> tuple[bool, str]:
        if not self._loop or not self._client:
            return (False, self._start_error or "Telethon client not ready")
        body = str(text or "")
        if not body.strip():
            return (False, "empty message")

        async def _send():
            await self._client.send_message(
                self.target,
                body,
                parse_mode="html",
                link_preview=False,
            )

        try:
            fut = asyncio.run_coroutine_threadsafe(_send(), self._loop)
            fut.result(timeout=float(timeout_sec or 10))
            return (True, "")
        except Exception as exc:
            return (False, str(exc))

    def stop(self) -> None:
        if not self._loop:
            return

        async def _shutdown() -> None:
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception:
                    _log.debug("_shutdown: suppressed error", exc_info=True)

        try:
            fut = asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
            fut.result(timeout=5)
        except Exception:
            _log.debug("stop: suppressed error", exc_info=True)
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            _log.debug("stop: suppressed error", exc_info=True)


def _codes_from_text(text: str) -> list[str]:
    import re

    out: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(r"\((\d{1,10})\)", str(text or "")):
        code = str(m.group(1) or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def _render_intercept_message(payload: dict) -> str:
    """
    Формат в чат:

    Частота: 151.0000
    Групповой ID: 870200

    Альтаир - 15500000
    Грач - 131130

    20.15
    -Перехват. (15500000)
    """
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
        for code in _codes_from_text(body):
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


def main() -> None:
    root = _root_dir()
    cfg_path = (root / "telegram_receiver_config.json").resolve()
    cfg = _load_or_create_config(cfg_path)

    bind_host = str(cfg.get("bind_host") or "0.0.0.0").strip() or "0.0.0.0"
    port = int(cfg.get("port") or 8787)
    listen_path = str(cfg.get("listen_path") or "/api/intercepts/telegram").strip()
    if not listen_path.startswith("/"):
        listen_path = "/" + listen_path
    secret_key = str(cfg.get("secret_key") or "").strip()
    bot_token = str(cfg.get("bot_token") or "").strip()
    chat_id = str(cfg.get("chat_id") or "").strip()
    timeout_sec = float(cfg.get("request_timeout_sec") or 10)
    send_mode = str(cfg.get("send_mode") or "user").strip().lower()
    if send_mode not in {"user", "bot"}:
        send_mode = "user"

    user_sender: TelethonUserSender | None = None
    if send_mode == "user":
        try:
            api_id = int(cfg.get("api_id") or 0)
        except Exception:
            api_id = 0
        user_sender = TelethonUserSender(
            root=root,
            api_id=api_id,
            api_hash=str(cfg.get("api_hash") or ""),
            session_name=str(cfg.get("session_name") or "tg_user"),
            target=str(cfg.get("target") or ""),
        )
        try:
            user_sender.start()
        except Exception as exc:
            print(f"[ERROR] Не удалось запустить user-режим: {exc}")
            sys.exit(1)
        print(f"Send mode: user → {cfg.get('target')}")
    else:
        print("Send mode: bot")

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path != listen_path:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b'{"ok":false,"error":"not found"}')
                return
            if secret_key:
                got = str(self.headers.get("X-Intercept-Key") or "").strip()
                if got != secret_key:
                    self.send_response(403)
                    self.end_headers()
                    self.wfile.write(b'{"ok":false,"error":"forbidden"}')
                    return
            try:
                content_len = int(self.headers.get("Content-Length") or "0")
            except Exception:
                content_len = 0
            raw = self.rfile.read(max(0, content_len))
            try:
                payload = json.loads(raw.decode("utf-8") or "{}") or {}
            except Exception:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"ok":false,"error":"invalid json"}')
                return
            text = _render_intercept_message(payload)
            if send_mode == "user" and user_sender is not None:
                ok, err = user_sender.send(text, timeout_sec=timeout_sec)
                dest = str(cfg.get("target") or "")
            else:
                thread_id = _resolve_message_thread_id(payload, cfg)
                ok, err = _send_telegram_bot_message(
                    bot_token,
                    chat_id,
                    text,
                    timeout_sec,
                    message_thread_id=thread_id,
                )
                dest = f"chat={chat_id} thread={thread_id or '-'}"
            if not ok:
                msg = str(err or "send failed")
                print(f"[{datetime.now().isoformat()}] send error: {msg}")
                self.send_response(502)
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {"ok": False, "error": msg},
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
                return
            print(
                f"[{datetime.now().isoformat()}] forwarded intercept "
                f"{str(payload.get('item_uuid') or '')} → {dest}"
            )
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer((bind_host, port), Handler)
    print(f"Telegram receiver started: http://{bind_host}:{port}{listen_path}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if user_sender is not None:
            user_sender.stop()


if __name__ == "__main__":
    main()
