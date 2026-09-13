from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger("web_portal.lib.wsgi_server")

logger = logging.getLogger(__name__)


def _wsgi_threads(default: int = 24) -> int:
    raw = (os.environ.get("WEB_PORTAL_WSGI_THREADS") or "").strip()
    if raw:
        try:
            return max(2, min(64, int(raw)))
        except ValueError:
            pass
    return max(2, min(64, int(default or 16)))


def _lan_ip_addresses() -> list[str]:
    """IP-адреса машины в локальной сети (для подключения с других устройств)."""
    import socket

    ips: list[str] = []
    # UDP-connect не шлёт пакеты, но заставляет ОС выбрать исходящий интерфейс
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            primary = str(s.getsockname()[0] or "").strip()
            if primary and not primary.startswith("127."):
                ips.append(primary)
        finally:
            s.close()
    except Exception:
        _log.debug("_lan_ip_addresses: suppressed error", exc_info=True)
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            addr = str(info[4][0] or "").strip()
            if addr and not addr.startswith("127.") and addr not in ips:
                ips.append(addr)
    except Exception:
        _log.debug("_lan_ip_addresses: suppressed error", exc_info=True)
    return ips


def _print_connect_banner(bind_host: str, bind_port: int) -> None:
    """Печатает адреса подключения (в т.ч. для мобильного телефона) в консоль."""
    lines = [
        "",
        "=" * 58,
        "  EAVC-HUB запущен",
        f"  Локально:        http://127.0.0.1:{bind_port}",
    ]
    if bind_host in ("0.0.0.0", "::", ""):
        ips = _lan_ip_addresses()
        if ips:
            for ip in ips:
                lines.append(f"  По сети / телефон: http://{ip}:{bind_port}")
            lines.append(
                "  Телефон должен быть в той же Wi-Fi/локальной сети."
            )
        else:
            lines.append("  Не удалось определить IP в локальной сети.")
    else:
        lines.append(f"  Адрес:           http://{bind_host}:{bind_port}")
    lines.append("=" * 58)
    banner = "\n".join(lines)
    try:
        print(banner, flush=True)
    except Exception:
        _log.debug("_print_connect_banner: suppressed error", exc_info=True)


def run_wsgi_server(
    app: Any,
    *,
    host: str = "0.0.0.0",
    port: int = 5000,
    debug: bool = False,
    threads: int = 16,
) -> None:
    """
    Production-like server for LAN/EXE deployments.
    Waitress serves concurrent operators; Flask dev server is kept only for debug.
    """
    bind_host = str(host or "0.0.0.0").strip() or "0.0.0.0"
    bind_port = int(port or 5000)
    thread_count = _wsgi_threads(threads)
    queue_log_level = (os.environ.get("WEB_PORTAL_WAITRESS_QUEUE_LOG_LEVEL") or "ERROR").strip().upper()
    try:
        logging.getLogger("waitress.queue").setLevel(getattr(logging, queue_log_level, logging.ERROR))
    except Exception:
        logging.getLogger("waitress.queue").setLevel(logging.ERROR)

    _print_connect_banner(bind_host, bind_port)

    if debug:
        logger.info(
            "Starting Flask dev server on %s:%s (debug=1, single-threaded)",
            bind_host,
            bind_port,
        )
        app.run(host=bind_host, port=bind_port, debug=True)
        return

    try:
        from waitress import serve
    except ImportError:
        logger.warning(
            "waitress not installed — falling back to Flask dev server "
            "(concurrency will be limited). pip install waitress"
        )
        app.run(host=bind_host, port=bind_port, debug=False)
        return

    logger.info(
        "Starting Waitress on %s:%s (threads=%s)",
        bind_host,
        bind_port,
        thread_count,
    )
    channel_timeout = max(
        30,
        min(int(os.environ.get("WEB_PORTAL_WAITRESS_CHANNEL_TIMEOUT") or 120), 600),
    )
    serve(
        app,
        host=bind_host,
        port=bind_port,
        threads=thread_count,
        channel_timeout=channel_timeout,
    )
