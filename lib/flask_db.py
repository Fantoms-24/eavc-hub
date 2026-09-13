"""Переиспользование SQLite-соединений в рамках одного HTTP-запроса (Flask g)."""

from __future__ import annotations

from flask import g

from web_portal.config import DEFAULT_DB_NAME, db_path, portal_db_path
from web_portal.lib.auth_db import connect_portal
from web_portal.lib.db import connect, ensure_db, unregister_connection
import logging

_log = logging.getLogger("web_portal.lib.flask_db")


def get_request_main_db():
    conn = g.get("_wp_main_db_conn")
    if conn is not None:
        return conn
    p = db_path(DEFAULT_DB_NAME)
    ensure_db(p)
    conn = connect(p)
    g._wp_main_db_conn = conn
    return conn


def get_request_seans_db():
    """БД сеансов (seans.sqlite после миграции или legacy main.sqlite)."""
    conn = g.get("_wp_seans_db_conn")
    if conn is not None:
        return conn
    from web_portal.lib.seans_db import connect_seans_storage

    conn = connect_seans_storage()
    g._wp_seans_db_conn = conn
    return conn


def get_request_portal_db():
    conn = g.get("_wp_portal_db_conn")
    if conn is not None:
        return conn
    conn = connect_portal(portal_db_path())
    g._wp_portal_db_conn = conn
    return conn


def close_request_dbs(_exc: BaseException | None = None) -> None:
    for key in ("_wp_main_db_conn", "_wp_seans_db_conn", "_wp_portal_db_conn"):
        conn = g.pop(key, None)
        if conn is None:
            continue
        try:
            unregister_connection(conn)
            conn.close()
        except Exception:
            _log.debug("close_request_dbs: suppressed error", exc_info=True)
