"""Запросы / sync-upsert по сеансам (физически из ``_impl``)."""
from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db.connection import _commit_if_needed, init_db
from web_portal.lib.db.seans_archive import resolve_seans_conn_for_queries
from web_portal.lib.db.seans_schema import (
    _table_exists,
    init_seans_tables,
    seanses_union_source_sql,
)


def list_distinct_seans_frequency_groups(
    main_conn: sqlite3.Connection,
    *,
    seans_conn: sqlite3.Connection | None = None,
    since_dt: str | None = None,
    frequency_like: str | None = None,
    frequency_exact: str | None = None,
) -> list[tuple[str, str]]:
    """
    DISTINCT (frequency, group_) из активного хранилища сеансов.
    После migrate_seans_to_separate_db данные в seans.sqlite, не в main.sqlite.
    """
    sc = resolve_seans_conn_for_queries(main_conn, seans_conn)
    params: list[Any] = []
    where_parts = [
        "TRIM(COALESCE(frequency, '')) != ''",
        "TRIM(COALESCE(group_, '')) != ''",
    ]
    if since_dt:
        where_parts.append("date_time >= ?")
        params.append(str(since_dt))
    if frequency_like is not None and frequency_exact is not None:
        where_parts.append(
            "(frequency LIKE ? OR CAST(frequency AS REAL)=CAST(? AS REAL))"
        )
        params.extend([frequency_like, frequency_exact])
    where = " AND ".join(where_parts)
    rows = sc.execute(
        f"""
        SELECT DISTINCT frequency, group_
        FROM seanses
        WHERE {where}
        """,
        tuple(params),
    ).fetchall()
    return [
        (str(r[0] or "").strip(), str(r[1] or "").strip())
        for r in (rows or [])
        if str(r[0] or "").strip() and str(r[1] or "").strip()
    ]


def list_seans_pairs(
    conn: sqlite3.Connection, position_name: str | None = None
) -> list[dict[str, Any]]:
    init_db(conn)
    cur = conn.cursor()
    if position_name:
        rows = cur.execute(
            "SELECT DISTINCT frequency, group_ FROM seanses WHERE client_name=? ORDER BY frequency, group_;",
            (str(position_name),),
        ).fetchall()
    else:
        rows = cur.execute(
            "SELECT DISTINCT frequency, group_ FROM seanses ORDER BY frequency, group_;"
        ).fetchall()
    return [{"frequency": str(r[0] or ""), "group": str(r[1] or "")} for r in rows]


def count_seanses_by_code(
    conn: sqlite3.Connection,
    *,
    position_name: str | None,
    frequency: str,
    group_code: str,
    start_dt: str,
    end_dt: str,
    seans_conn: sqlite3.Connection | None = None,
) -> dict[str, int]:
    sc = resolve_seans_conn_for_queries(conn, seans_conn)
    freq = str(frequency or "").strip()
    grp_raw = str(group_code or "").strip()
    if not freq or not grp_raw:
        return {}

    # Поддержка формата group_ с и без префикса "G"
    variants: list[str] = []
    variants_set: set[str] = set()

    def _add(v: str) -> None:
        v = str(v or "").strip()
        if not v:
            return
        if v in variants_set:
            return
        variants_set.add(v)
        variants.append(v)

    _add(grp_raw)
    digits = "".join(ch for ch in grp_raw if ch.isdigit())
    if digits:
        _add(digits)
        _add(f"G{digits}")
        _add(f"g{digits}")

    if not variants:
        return {}

    params: list[Any] = [start_dt, end_dt, freq]
    if len(variants) == 1:
        where = "date_time BETWEEN ? AND ? AND frequency=? AND group_=?"
        params.append(variants[0])
    else:
        placeholders = ",".join("?" for _ in variants)
        where = (
            f"date_time BETWEEN ? AND ? AND frequency=? AND group_ IN ({placeholders})"
        )
        params.extend(variants)

    if position_name:
        where += " AND client_name=?"
        params.append(str(position_name))
    source_sql = seanses_union_source_sql(sc)
    rows = sc.execute(
        f"""
        SELECT id, COUNT(*) as cnt
        FROM ({source_sql})
        WHERE {where}
        GROUP BY id
        ORDER BY cnt DESC
        """,
        tuple(params),
    ).fetchall()
    out: dict[str, int] = {}
    for rid, cnt in rows:
        out[str(rid or "")] = int(cnt or 0)
    return out


def count_seanses_by_code_for_unit(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    unit_name: str,
    start_dt: str,
    end_dt: str,
    seans_conn: sqlite3.Connection | None = None,
) -> dict[str, int]:
    """
    Аггрегирует сеансы по всем (frequency, group_) которые входят в unit_name
    через intercept_catalog (main.sqlite) + seanses (seans.sqlite).
    """
    init_db(conn)
    pos = str(position_name or "").strip()
    unit = str(unit_name or "").strip()
    pair_rows = conn.execute(
        """
        SELECT DISTINCT frequency, group_code
        FROM intercept_catalog
        WHERE position_name = ? AND unit_name = ?
        """,
        (pos, unit),
    ).fetchall()
    pairs = [
        (str(r[0] or "").strip(), str(r[1] or "").strip())
        for r in (pair_rows or [])
        if str(r[0] or "").strip() and str(r[1] or "").strip()
    ]
    if not pairs:
        return {}

    sc = resolve_seans_conn_for_queries(conn, seans_conn)
    source_sql = seanses_union_source_sql(sc)
    sc.execute(
        "CREATE TEMP TABLE IF NOT EXISTS _tmp_unit_pairs (frequency TEXT, group_ TEXT)"
    )
    sc.execute("DELETE FROM _tmp_unit_pairs")
    sc.executemany(
        "INSERT INTO _tmp_unit_pairs (frequency, group_) VALUES (?, ?)",
        pairs,
    )
    rows = sc.execute(
        f"""
        SELECT s.id, COUNT(*) as cnt
        FROM ({source_sql}) s
        JOIN _tmp_unit_pairs p
          ON p.frequency = s.frequency AND p.group_ = s.group_
        WHERE s.client_name = ?
          AND s.date_time BETWEEN ? AND ?
        GROUP BY s.id
        ORDER BY cnt DESC
        """,
        (pos, start_dt, end_dt),
    ).fetchall()
    out: dict[str, int] = {}
    for rid, cnt in rows:
        out[str(rid or "")] = int(cnt or 0)
    return out


def get_seanses_rows_export(
    conn: sqlite3.Connection,
    date_time_1: str,
    date_time_2: str,
    client_name: str | None = None,
) -> list[dict[str, Any]]:
    """Сырые строки seanses за период для выгрузки в Excel (Время выхода, Частота, ID, Группа, AES ключа, Color Voice, Время сек)."""
    init_seans_tables(conn)
    cur = conn.cursor()
    cur.row_factory = sqlite3.Row
    source_sql = """
        SELECT date_time, frequency, id, group_, aes_key, color_voice, time_seconds, client_name FROM seanses
        UNION ALL
        SELECT date_time, frequency, id, group_, aes_key, color_voice, time_seconds, client_name FROM seanses_archive
    """
    if client_name:
        cur.execute(
            f"""
            SELECT date_time, frequency, id, group_, aes_key, color_voice, time_seconds
            FROM ({source_sql})
            WHERE date_time BETWEEN ? AND ? AND client_name = ?
            ORDER BY date_time, frequency, group_, id
            """,
            (date_time_1, date_time_2, client_name),
        )
    else:
        cur.execute(
            f"""
            SELECT date_time, frequency, id, group_, aes_key, color_voice, time_seconds
            FROM ({source_sql})
            WHERE date_time BETWEEN ? AND ?
            ORDER BY date_time, frequency, group_, id
            """,
            (date_time_1, date_time_2),
        )
    rows = cur.fetchall()
    return [
        {
            "date_time": str(r["date_time"] or ""),
            "frequency": str(r["frequency"] or ""),
            "id": str(r["id"] or ""),
            "group": str(r["group_"] or ""),
            "aes_key": str(r["aes_key"] or "") if r["aes_key"] else "",
            "color_voice": str(r["color_voice"] or "") if r["color_voice"] else "",
            "time_seconds": float(r["time_seconds"]) if r["time_seconds"] is not None else None,
        }
        for r in rows
    ]


def list_active_seans_freq_groups_for_unit_name(
    main_conn: sqlite3.Connection, unit_name: str
) -> list[dict[str, Any]]:
    """
    Активные пары (частота, группа) из seanses, сопоставленные с unit.name = подразделение.
    """
    init_db(main_conn)
    un = (unit_name or "").strip()
    if not un:
        return []
    try:
        rows = main_conn.execute(
            """
            SELECT
              TRIM(s.frequency) AS f,
              TRIM(s.group_) AS g,
              COUNT(*) AS n
            FROM seanses s
            INNER JOIN unit u
              ON TRIM(u.frequency) = TRIM(s.frequency)
             AND TRIM(u.group_) = TRIM(s.group_)
             AND TRIM(COALESCE(u.name, '')) = ?
            GROUP BY TRIM(s.frequency), TRIM(s.group_)
            """,
            (un,),
        ).fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows or []:
        f = str(r["f"] or "")
        g = str(r["g"] or "")
        if not f or not g:
            continue
        out.append(
            {
                "frequency": f,
                "group": g,
                "session_count": int(r["n"] or 0),
            }
        )
    out.sort(key=lambda x: (str(x["frequency"]).lower(), str(x["group"]).lower()))
    return out


def seanses_datetime_extremes_for_unit_pair(
    main_conn: sqlite3.Connection,
    unit_name: str,
    frequency: str,
    group_code: str,
) -> dict[str, str | None]:
    init_db(main_conn)
    un = (unit_name or "").strip()
    f = (frequency or "").strip()
    g = (group_code or "").strip()
    if not un or not f or not g:
        return {"first": None, "last": None}
    tmins: list[str] = []
    tmaxs: list[str] = []
    for table in ("seanses", "seanses_archive"):
        try:
            row = main_conn.execute(
                f"""
                SELECT MIN(s.date_time) AS tmin, MAX(s.date_time) AS tmax
                FROM {table} s
                INNER JOIN unit u
                  ON TRIM(u.frequency) = TRIM(s.frequency)
                 AND TRIM(u.group_) = TRIM(s.group_)
                 AND TRIM(COALESCE(u.name, '')) = ?
                WHERE TRIM(s.frequency) = ? AND TRIM(s.group_) = ?
                """,
                (un, f, g),
            ).fetchone()
        except Exception:
            continue
        if row and (row["tmin"] or row["tmax"]):
            if row["tmin"]:
                tmins.append(str(row["tmin"]))
            if row["tmax"]:
                tmaxs.append(str(row["tmax"]))
    first = min(tmins) if tmins else None
    last = max(tmaxs) if tmaxs else None
    return {"first": first, "last": last}


def list_seanses_ids_for_unit_pair(
    main_conn: sqlite3.Connection,
    unit_name: str,
    frequency: str,
    group_code: str,
) -> list[str]:
    from web_portal.lib.seans_db import connect_seans_storage, use_separate_seans_db

    init_db(main_conn)
    un = (unit_name or "").strip()
    f = (frequency or "").strip()
    g = (group_code or "").strip()
    if not un or not f or not g:
        return []
    seans_conn = main_conn
    close_seans = False
    if use_separate_seans_db():
        seans_conn = connect_seans_storage()
        close_seans = True
    try:
        init_seans_tables(seans_conn)
        if seans_conn is main_conn:
            rows = main_conn.execute(
                """
                SELECT DISTINCT TRIM(s.id) AS iid
                FROM seanses s
                INNER JOIN unit u
                  ON TRIM(u.frequency) = TRIM(s.frequency)
                 AND TRIM(u.group_) = TRIM(s.group_)
                 AND TRIM(COALESCE(u.name, '')) = ?
                WHERE TRIM(s.frequency) = ? AND TRIM(s.group_) = ?
                """,
                (un, f, g),
            ).fetchall()
        else:
            urow = main_conn.execute(
                """
                SELECT 1 FROM unit
                WHERE TRIM(COALESCE(name, '')) = ?
                  AND TRIM(frequency) = ? AND TRIM(group_) = ?
                LIMIT 1
                """,
                (un, f, g),
            ).fetchone()
            if not urow:
                return []
            rows = seans_conn.execute(
                """
                SELECT DISTINCT TRIM(id) AS iid
                FROM seanses
                WHERE TRIM(frequency) = ? AND TRIM(group_) = ?
                """,
                (f, g),
            ).fetchall()
    except Exception:
        return []
    finally:
        if close_seans:
            try:
                seans_conn.close()
            except Exception:
                _log.debug("list_seanses_ids_for_unit_pair: suppressed error", exc_info=True)
    return sorted({str(r["iid"] or "") for r in (rows or []) if r and r["iid"]})


def list_seanses_rows_after_rowid(
    conn: sqlite3.Connection, *, after_rowid: int, limit: int = 5000,
    initialize: bool = True,
) -> list[dict[str, Any]]:
    """
    Инкрементальная выборка seanses через rowid (быстро и удобно для больших импортов).
    """
    if initialize:
        init_seans_tables(conn)
    limit = max(1, min(int(limit), 20000))
    ar = int(after_rowid or 0)
    rows = conn.execute(
        """
        SELECT
          rowid as rowid,
          created_at, date_time, frequency, group_, id, aes_key, client_name
        FROM seanses
        WHERE rowid > ?
        ORDER BY rowid ASC
        LIMIT ?
        """,
        (ar, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        out.append(
            {
                "rowid": int(r["rowid"]),
                "created_at": str(r["created_at"] or ""),
                "date_time": str(r["date_time"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group_": str(r["group_"] or ""),
                "id": str(r["id"] or ""),
                "aes_key": str(r["aes_key"] or ""),
                "client_name": str(r["client_name"] or ""),
            }
        )
    return out


def upsert_seanses_rows_from_sync(
    conn: sqlite3.Connection, *, rows: list[dict[str, Any]]
) -> dict[str, int]:
    """
    Применение батча seanses на принимающей стороне (сервер).
    Используем PK(date_time, frequency, group_, id).
    """
    init_seans_tables(conn)
    if not rows:
        return {"applied": 0}
    params = []
    for r in rows or []:
        dt = str(r.get("date_time") or "")
        fr = str(r.get("frequency") or "")
        gr = str(r.get("group_") or "")
        cid = str(r.get("id") or "")
        if not dt or not fr or not gr or not cid:
            continue
        params.append(
            (
                str(r.get("created_at") or "") or None,
                dt,
                fr,
                gr,
                cid,
                str(r.get("aes_key") or "") or None,
                str(r.get("client_name") or "").strip(),
            )
        )
    if not params:
        return {"applied": 0}
    conn.executemany(
        """
        INSERT INTO seanses (created_at, date_time, frequency, group_, id, aes_key, client_name)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(date_time, frequency, group_, id, client_name) DO UPDATE SET
          aes_key=COALESCE(NULLIF(excluded.aes_key,''), seanses.aes_key),
          created_at=COALESCE(NULLIF(excluded.created_at,''), seanses.created_at)
        """,
        params,
    )
    _commit_if_needed(conn)
    return {"applied": len(params)}


def list_seanses_since(
    conn: sqlite3.Connection,
    *,
    since_ts: str,
    limit: int = 5000,
    position_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Выборка seanses по created_at для синхронизации "сервер -> HUB" (pull).
    Таблица большая — поэтому лимитируем.
    """
    from web_portal.lib.db.sql_util import _in_clause
    init_seans_tables(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    limit = max(1, min(int(limit), 5000))
    where_pos, params_pos = _in_clause("client_name", position_names or [])
    rows = conn.execute(
        """
        SELECT created_at, date_time, frequency, group_, id, aes_key, client_name
        FROM seanses
        WHERE created_at >= ?{where_pos}
        ORDER BY created_at ASC
        LIMIT ?
        """.format(where_pos=where_pos),
        [since] + params_pos + [limit],
    ).fetchall()
    return [
        {
            "created_at": str(r["created_at"] or ""),
            "date_time": str(r["date_time"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_": str(r["group_"] or ""),
            "id": str(r["id"] or ""),
            "aes_key": str(r["aes_key"] or ""),
            "client_name": str(r["client_name"] or ""),
        }
        for r in rows
    ]


def _get_last_recorded_by_freq_group(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str], str]:
    """
    Возвращает последнюю дату записи (date_time) по каждой паре (frequency, group_)
    из таблицы seanses. Ключ — (frequency, group_), значение — строка date_time.
    """
    init_db(conn)
    if not _table_exists(conn, "seanses"):
        return {}
    cols = _table_columns(conn, "seanses")
    dt_c = _pick_first(cols, ["date_time", "datetime", "dt"])
    if not dt_c:
        return {}
    rows = conn.execute(
        f"""
        SELECT frequency, group_, MAX({dt_c}) as last_recorded
        FROM seanses
        GROUP BY frequency, group_
        """
    ).fetchall()
    out: dict[tuple[str, str], str] = {}
    for r in rows or []:
        key = (str(r["frequency"] or ""), str(r["group_"] or ""))
        out[key] = str(r["last_recorded"] or "")
    return out

__all__ = [
    "_get_last_recorded_by_freq_group",
    "list_distinct_seans_frequency_groups",
    "list_seans_pairs",
    "count_seanses_by_code",
    "count_seanses_by_code_for_unit",
    "get_seanses_rows_export",
    "list_active_seans_freq_groups_for_unit_name",
    "seanses_datetime_extremes_for_unit_pair",
    "list_seanses_ids_for_unit_pair",
    "list_seanses_rows_after_rowid",
    "upsert_seanses_rows_from_sync",
    "list_seanses_since",
]
