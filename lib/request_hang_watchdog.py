"""
Фоновый контроль «залипших» HTTP-запросов.

Если обработка запроса занимает дольше порога (по умолчанию 60 с), пишется
критическое сообщение в лог и (по возможности) дамп стеков всех потоков через faulthandler.

Отключить: WEB_PORTAL_HANG_WATCH=0

Параметры:
  WEB_PORTAL_HANG_WARN_SEC   — порог, секунд (default 60)
  WEB_PORTAL_HANG_POLL_SEC   — интервал проверки, секунд (default 10)
  WEB_PORTAL_HANG_LOG_PATH   — необязательно: дополнительный файл для полного дампа

Повторные записи для того же потока — не чаще одного раза за порог секунд, пока запрос висит.
"""
from __future__ import annotations

import io
import logging
import os
import threading
import time
import traceback
from typing import Any

_log = logging.getLogger("web_portal.lib.request_hang_watchdog")

log = logging.getLogger("web_portal.hang_watch")

try:
    import faulthandler
except ImportError:
    faulthandler = None  # type: ignore[assignment]

_lock = threading.Lock()
_emit_lock = threading.Lock()
_active: dict[int, dict[str, Any]] = {}
_last_emit: dict[int, float] = {}
_installed = False


def _env_float(name: str, default: float) -> float:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def _dump_stacks_text() -> str:
    import sys

    parts: list[str] = []
    if faulthandler is not None:
        try:
            buf = io.StringIO()
            faulthandler.dump_traceback(file=buf, all_threads=True)
            text = buf.getvalue()
            if text.strip():
                return text
        except Exception as e:
            parts.append(f"(faulthandler failed: {e})\n")
    try:
        for th_id, frame in sys._current_frames().items():
            parts.append(f"--- Thread {th_id} ---\n")
            parts.append("".join(traceback.format_stack(frame)))
    except Exception as e:
        parts.append(f"(stack walk failed: {e})\n")
    return "".join(parts) or "(no stack frames)\n"


def install_request_hang_watchdog(app: Any) -> None:
    global _installed
    if _installed:
        return

    raw_en = (os.environ.get("WEB_PORTAL_HANG_WATCH") or "1").strip().lower()
    if raw_en in {"0", "false", "no", "off"}:
        return

    threshold = max(5.0, _env_float("WEB_PORTAL_HANG_WARN_SEC", 60.0))
    poll = max(1.0, min(_env_float("WEB_PORTAL_HANG_POLL_SEC", 10.0), threshold / 2.0 or 10.0))
    extra_path = (os.environ.get("WEB_PORTAL_HANG_LOG_PATH") or "").strip()

    from flask import request

    @app.before_request
    def _hang_watch_before() -> None:
        try:
            qs = request.query_string
            if isinstance(qs, bytes):
                qss = qs.decode("utf-8", errors="replace")[:800]
            else:
                qss = str(qs or "")[:800]
        except Exception:
            qss = ""
        rec = {
            "path": getattr(request, "path", "") or "",
            "method": getattr(request, "method", "") or "",
            "t0": time.monotonic(),
            "remote": (getattr(request, "remote_addr", None) or "") or "",
            "endpoint": (getattr(request, "endpoint", None) or "") or "",
            "qs": qss,
        }
        with _lock:
            _active[threading.get_ident()] = rec

    @app.teardown_request
    def _hang_watch_teardown(_exc: BaseException | None) -> None:
        tid = threading.get_ident()
        with _lock:
            _active.pop(tid, None)
        with _emit_lock:
            _last_emit.pop(tid, None)

    def _emit(tid: int, info: dict[str, Any], elapsed: float) -> None:
        now_m = time.monotonic()
        with _emit_lock:
            last = _last_emit.get(tid, 0.0)
            if now_m - last < threshold and last > 0:
                return
            _last_emit[tid] = now_m

        msg = (
            f"Подвисание запроса: {elapsed:.1f}s ≥ порог {threshold:.0f}s | "
            f"{info.get('method')} {info.get('path')} | "
            f"endpoint={info.get('endpoint')} | remote={info.get('remote')} | "
            f"thread={tid} | query={info.get('qs')}"
        )
        stacks = _dump_stacks_text()
        log.critical(msg)
        log.critical("Стеки потоков при срабатывании hang-watchdog:\n%s", stacks.rstrip())
        try:
            from web_portal.lib.portal_event_log import log_portal_event

            log_portal_event(
                level="CRITICAL",
                category="hang",
                action="request_hang",
                message=msg,
                ip=str(info.get("remote") or ""),
                path=str(info.get("path") or ""),
                method=str(info.get("method") or ""),
                duration_ms=int(elapsed * 1000),
                details={
                    "endpoint": info.get("endpoint"),
                    "query": info.get("qs"),
                    "thread_id": tid,
                },
            )
        except Exception:
            _log.debug("_emit: suppressed error", exc_info=True)

        if extra_path:
            try:
                p = os.path.abspath(extra_path)
                d = os.path.dirname(p)
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(p, "a", encoding="utf-8") as f:
                    f.write("\n" + "=" * 72 + "\n")
                    f.write(time.strftime("%Y-%m-%d %H:%M:%S "))
                    f.write(msg + "\n")
                    if faulthandler is not None:
                        try:
                            faulthandler.dump_traceback(file=f, all_threads=True)
                        except Exception as fe:
                            f.write(f"(dump_traceback file failed: {fe})\n")
                    else:
                        f.write(stacks or "(no stacks)\n")
            except Exception as fe:
                log.warning("WEB_PORTAL_HANG_LOG_PATH write failed: %s", fe)

    def _watch_loop() -> None:
        while True:
            time.sleep(poll)
            now = time.monotonic()
            with _lock:
                snap = [
                    (tid, dict(rec))
                    for tid, rec in _active.items()
                    if now - float(rec.get("t0", now)) >= threshold
                ]
            for tid, info in snap:
                try:
                    dt = now - float(info.get("t0", now))
                    _emit(tid, info, dt)
                except Exception as e:
                    log.warning("hang watchdog emit: %s", e)

    threading.Thread(target=_watch_loop, daemon=True, name="wp-hang-watchdog").start()
    _installed = True
    log.info(
        "Hang watchdog включён: порог %.0fs, опрос %.1fs, лог-файл=%s",
        threshold,
        poll,
        extra_path or "(только logger)",
    )
