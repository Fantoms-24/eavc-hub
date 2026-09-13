from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from web_portal.config import DATA_DIR, portal_db_path
from web_portal.lib.auth_db import connect_portal

_log = logging.getLogger("web_portal.lib.portal_event_log")

_LOG = logging.getLogger("web_portal.event_log")
_WRITE_LOCK = threading.Lock()
_INSERT_COUNT = 0

_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

_SENSITIVE_RE = re.compile(
    r"(password|passwd|sync[_-]?key|secret|token|authorization)",
    re.I,
)


def portal_logs_dir() -> Path:
    raw = (os.environ.get("WEB_PORTAL_LOG_DIR") or "").strip()
    base = Path(raw).resolve() if raw else (DATA_DIR / "logs")
    base.mkdir(parents=True, exist_ok=True)
    return base


def portal_log_file_path() -> Path:
    name = (os.environ.get("WEB_PORTAL_LOG_FILE") or "web_portal.log").strip()
    return portal_logs_dir() / name


def init_portal_event_log(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS portal_event_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            level TEXT NOT NULL DEFAULT 'INFO',
            category TEXT NOT NULL DEFAULT 'system',
            action TEXT NOT NULL DEFAULT '',
            user_id INTEGER NOT NULL DEFAULT 0,
            username TEXT NOT NULL DEFAULT '',
            ip TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            method TEXT NOT NULL DEFAULT '',
            status_code INTEGER NOT NULL DEFAULT 0,
            duration_ms INTEGER NOT NULL DEFAULT 0,
            message TEXT NOT NULL DEFAULT '',
            details_json TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_event_log_created
        ON portal_event_log(created_at DESC);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_event_log_cat_created
        ON portal_event_log(category, created_at DESC);
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_portal_event_log_level_created
        ON portal_event_log(level, created_at DESC);
        """
    )
    conn.commit()


def _redact_details(data: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    out: dict[str, Any] = {}
    for key, val in data.items():
        ks = str(key)
        if _SENSITIVE_RE.search(ks):
            out[ks] = "***"
        elif isinstance(val, dict):
            out[ks] = _redact_details(val)
        else:
            out[ks] = val
    return out


def _truncate(text: str, limit: int = 4000) -> str:
    s = str(text or "")
    if len(s) <= limit:
        return s
    return s[: limit - 3] + "..."


def _maybe_cleanup(conn) -> None:
    global _INSERT_COUNT
    _INSERT_COUNT += 1
    if _INSERT_COUNT % 200 != 0:
        return
    try:
        max_rows = max(5000, min(int(os.environ.get("WEB_PORTAL_EVENT_LOG_MAX_ROWS") or 80000), 500000))
    except ValueError:
        max_rows = 80000
    try:
        days = max(7, min(int(os.environ.get("WEB_PORTAL_EVENT_LOG_RETENTION_DAYS") or 45), 365))
    except ValueError:
        days = 45
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("DELETE FROM portal_event_log WHERE created_at < ?", (cutoff,))
    row = conn.execute("SELECT COUNT(*) FROM portal_event_log").fetchone()
    total = int(row[0] if row else 0)
    if total > max_rows:
        excess = total - max_rows
        conn.execute(
            """
            DELETE FROM portal_event_log
            WHERE id IN (
                SELECT id FROM portal_event_log
                ORDER BY id ASC
                LIMIT ?
            )
            """,
            (excess,),
        )


def log_portal_event(
    *,
    level: str = "INFO",
    category: str = "system",
    action: str = "",
    message: str = "",
    user_id: int = 0,
    username: str = "",
    ip: str = "",
    path: str = "",
    method: str = "",
    status_code: int = 0,
    duration_ms: int = 0,
    details: dict[str, Any] | None = None,
) -> None:
    if (os.environ.get("WEB_PORTAL_EVENT_LOG") or "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return
    lvl = str(level or "INFO").upper()
    if lvl not in _LEVELS:
        lvl = "INFO"
    try:
        details_json = json.dumps(_redact_details(details), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        details_json = "{}"
    if len(details_json) > 12000:
        details_json = details_json[:12000] + "…"

    row = (
        _utc_now_str(),
        lvl,
        _truncate(str(category or "system"), 64),
        _truncate(str(action or ""), 128),
        int(user_id or 0),
        _truncate(str(username or ""), 128),
        _truncate(str(ip or ""), 64),
        _truncate(str(path or ""), 512),
        _truncate(str(method or ""), 16),
        int(status_code or 0),
        max(0, int(duration_ms or 0)),
        _truncate(str(message or ""), 2000),
        details_json,
    )
    with _WRITE_LOCK:
        try:
            conn = connect_portal(portal_db_path())
            try:
                init_portal_event_log(conn)
                conn.execute(
                    """
                    INSERT INTO portal_event_log (
                        created_at, level, category, action,
                        user_id, username, ip, path, method,
                        status_code, duration_ms, message, details_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    row,
                )
                conn.commit()
                _maybe_cleanup(conn)
            finally:
                conn.close()
        except Exception:
            _LOG.debug("portal_event_log write failed", exc_info=True)


class PortalEventLogHandler(logging.Handler):
    """Дублирует WARNING+ из Python-логов в portal_event_log."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if record.levelno < logging.WARNING:
                return
            msg = self.format(record)
            log_portal_event(
                level=record.levelname,
                category="python",
                action=str(record.name or "")[:128],
                message=msg,
                details={
                    "lineno": record.lineno,
                    "pathname": record.pathname,
                    "funcName": record.funcName,
                },
            )
        except Exception:
            self.handleError(record)


def setup_portal_file_logging() -> Path:
    """Rotating file + DB handler для корневого логгера web_portal."""
    log_path = portal_log_file_path()
    try:
        max_mb = max(1, min(int(os.environ.get("WEB_PORTAL_LOG_MAX_MB") or 20), 200))
    except ValueError:
        max_mb = 20
    try:
        backups = max(1, min(int(os.environ.get("WEB_PORTAL_LOG_BACKUPS") or 8), 30))
    except ValueError:
        backups = 8

    root = logging.getLogger("web_portal")
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        fh = RotatingFileHandler(
            str(log_path),
            maxBytes=max_mb * 1024 * 1024,
            backupCount=backups,
            encoding="utf-8",
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)

    if not any(isinstance(h, PortalEventLogHandler) for h in root.handlers):
        dbh = PortalEventLogHandler()
        dbh.setLevel(logging.WARNING)
        dbh.setFormatter(fmt)
        root.addHandler(dbh)

    return log_path


_POLL_SKIP_PATHS = (
    "/api/intercepts/state",
    "/api/sessions/process-folder/progress",
    "/api/online-search/import-progress",
    "/api/export-jobs/",
    "/api/analysis/ai/jobs/",
)


def _should_log_http(*, path: str, method: str, status: int, duration_ms: int) -> bool:
    p = str(path or "")
    if p.startswith("/static/") or p in ("/favicon.ico", "/health"):
        return False
    if status >= 400 or duration_ms >= 2000:
        return True
    m = str(method or "").upper()
    if m in ("POST", "PUT", "PATCH", "DELETE"):
        return p.startswith("/api/")
    if p.startswith("/api/sync/"):
        return True
    if p.startswith("/api/admin/"):
        return True
    for skip in _POLL_SKIP_PATHS:
        if skip in p and duration_ms < 1500 and status < 400:
            return False
    if p.startswith("/api/") and duration_ms >= 800:
        return True
    return False


def install_request_event_logging(app) -> None:
    from flask import g, request

    try:
        from flask_login import current_user
    except Exception:
        current_user = None  # type: ignore

    @app.before_request
    def _event_log_before() -> None:
        g._portal_req_t0 = time.perf_counter()

    @app.after_request
    def _event_log_after(response):
        try:
            t0 = getattr(g, "_portal_req_t0", None)
            duration_ms = int((time.perf_counter() - t0) * 1000) if t0 else 0
            path = str(getattr(request, "path", "") or "")
            method = str(getattr(request, "method", "") or "")
            status = int(getattr(response, "status_code", 0) or 0)
            if not _should_log_http(
                path=path, method=method, status=status, duration_ms=duration_ms
            ):
                return response

            uid = 0
            uname = ""
            try:
                if current_user and getattr(current_user, "is_authenticated", False):
                    uid = int(getattr(current_user, "id", 0) or 0)
                    uname = str(
                        getattr(current_user, "username", "")
                        or getattr(current_user, "callsign", "")
                        or ""
                    )
            except Exception:
                _log.debug("_event_log_after: suppressed error", exc_info=True)

            log_portal_event(
                level="WARNING" if status >= 500 else ("ERROR" if status >= 400 else "INFO"),
                category="http",
                action=f"{method} {path}"[:128],
                message=f"{method} {path} → {status} ({duration_ms} ms)",
                user_id=uid,
                username=uname,
                ip=str(getattr(request, "remote_addr", "") or ""),
                path=path,
                method=method,
                status_code=status,
                duration_ms=duration_ms,
                details={
                    "query": (request.query_string.decode("utf-8", errors="replace")[:500]
                    if request.query_string
                    else ""),
                },
            )
        except Exception:
            _log.debug("_event_log_after: suppressed error", exc_info=True)
        return response


def list_portal_events(
    conn,
    *,
    limit: int = 200,
    offset: int = 0,
    level: str = "",
    category: str = "",
    q: str = "",
    since: str = "",
    until: str = "",
) -> dict[str, Any]:
    init_portal_event_log(conn)
    lim = max(1, min(int(limit or 200), 500))
    off = max(0, int(offset or 0))
    where: list[str] = []
    params: list[Any] = []
    if level:
        where.append("level = ?")
        params.append(str(level).upper())
    if category:
        where.append("category = ?")
        params.append(str(category).strip())
    if since:
        where.append("created_at >= ?")
        params.append(str(since).strip())
    if until:
        where.append("created_at <= ?")
        params.append(str(until).strip())
    if q:
        qq = f"%{str(q).strip()}%"
        where.append(
            "(message LIKE ? OR path LIKE ? OR username LIKE ? OR action LIKE ? OR details_json LIKE ?)"
        )
        params.extend([qq, qq, qq, qq, qq])
    wsql = (" WHERE " + " AND ".join(where)) if where else ""
    total = int(
        conn.execute(f"SELECT COUNT(*) FROM portal_event_log{wsql}", tuple(params)).fetchone()[0]
        or 0
    )
    rows = conn.execute(
        f"""
        SELECT id, created_at, level, category, action,
               user_id, username, ip, path, method,
               status_code, duration_ms, message, details_json
        FROM portal_event_log{wsql}
        ORDER BY id DESC
        LIMIT ? OFFSET ?
        """,
        tuple(params) + (lim, off),
    ).fetchall()
    items: list[dict[str, Any]] = []
    for r in rows or []:
        try:
            details = json.loads(str(r["details_json"] or "{}") or "{}")
        except Exception:
            details = {}
        items.append(
            {
                "id": int(r["id"]),
                "created_at": str(r["created_at"] or ""),
                "level": str(r["level"] or ""),
                "category": str(r["category"] or ""),
                "action": str(r["action"] or ""),
                "user_id": int(r["user_id"] or 0),
                "username": str(r["username"] or ""),
                "ip": str(r["ip"] or ""),
                "path": str(r["path"] or ""),
                "method": str(r["method"] or ""),
                "status_code": int(r["status_code"] or 0),
                "duration_ms": int(r["duration_ms"] or 0),
                "message": str(r["message"] or ""),
                "details": details if isinstance(details, dict) else {},
            }
        )
    return {"total": total, "items": items, "limit": lim, "offset": off}


def tail_log_file(*, max_lines: int = 400, max_bytes: int = 512_000) -> dict[str, Any]:
    path = portal_log_file_path()
    if not path.is_file():
        return {"path": str(path), "lines": [], "exists": False}
    lim = max(50, min(int(max_lines or 400), 2000))
    cap = max(4096, min(int(max_bytes or 512_000), 2_000_000))
    try:
        size = path.stat().st_size
        with path.open("rb") as f:
            if size > cap:
                f.seek(-cap, os.SEEK_END)
            chunk = f.read()
        text = chunk.decode("utf-8", errors="replace")
        lines = text.splitlines()[-lim:]
        return {
            "path": str(path),
            "exists": True,
            "size_bytes": size,
            "lines": lines,
        }
    except Exception as e:
        return {"path": str(path), "exists": True, "lines": [], "error": str(e)}


def purge_portal_events(conn, *, days: int = 30) -> int:
    init_portal_event_log(conn)
    d = max(1, min(int(days or 30), 3650))
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=d)
    ).strftime("%Y-%m-%d %H:%M:%S")
    cur = conn.execute("DELETE FROM portal_event_log WHERE created_at < ?", (cutoff,))
    conn.commit()
    return int(cur.rowcount or 0)
