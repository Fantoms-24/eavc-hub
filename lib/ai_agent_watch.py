from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from web_portal.config import DATA_DIR, DEFAULT_DB_NAME, db_path
from web_portal.lib.auth_db import init_portal_db
from web_portal.lib.db import connect, init_db

log = logging.getLogger("web_portal.ai_agent_watch")

STATE_FILENAME = "ai_agent_watch_state.json"


def _state_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / STATE_FILENAME


def build_watch_snapshot(
    portal_conn: sqlite3.Connection, main_db_path: Path | None
) -> dict[str, Any]:
    init_portal_db(portal_conn)
    since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    by_tool: dict[str, int] = {}
    try:
        rows = portal_conn.execute(
            """
            SELECT tool, COUNT(*) AS c
            FROM ai_agent_actions
            WHERE COALESCE(created_at, '') >= ?
            GROUP BY tool
            """,
            (since,),
        ).fetchall()
        by_tool = {str(r[0] or ""): int(r[1] or 0) for r in rows}
    except Exception as exc:
        log.warning("watch: portal stats: %s", exc)
    total = sum(by_tool.values())

    main_stats: dict[str, Any] = {}
    path = main_db_path if (main_db_path and main_db_path.exists()) else None
    if path:
        mconn: sqlite3.Connection | None = None
        try:
            mconn = connect(path)
            init_db(mconn)
            t0 = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).strftime("%Y-%m-%d %H:%M:%S")
            c = mconn.execute(
                "SELECT COUNT(*) FROM seanses WHERE date_time >= ?",
                (t0,),
            ).fetchone()
            main_stats["seanses_since_midnight"] = int(c[0] or 0)
            u = mconn.execute("SELECT COUNT(*) FROM unit").fetchone()
            main_stats["unit_rows"] = int(u[0] or 0)
            try:
                uman = mconn.execute(
                    "SELECT COUNT(*) FROM unit WHERE COALESCE(manual,0) = 1"
                ).fetchone()
                main_stats["unit_manual_rows"] = int(uman[0] or 0)
            except Exception:
                main_stats["unit_manual_rows"] = None
        except Exception as exc:
            main_stats["error"] = str(exc)
        finally:
            if mconn:
                mconn.close()

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "window_hours": 24,
        "actions_total_24h": total,
        "actions_by_tool_24h": by_tool,
        "main_db": str(path) if path else "",
        "main_db_stats": main_stats,
    }


def save_watch_state(snapshot: dict[str, Any]) -> None:
    payload = {
        "last_run_at": snapshot.get("generated_at"),
        "snapshot": snapshot,
    }
    p = _state_path()
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_watch_state() -> dict[str, Any] | None:
    p = _state_path()
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def default_main_db_path() -> Path:
    return db_path(DEFAULT_DB_NAME)
