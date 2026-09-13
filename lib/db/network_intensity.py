"""Кластеры интенсивности сетей (физически из ``_impl``)."""
from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db
from web_portal.lib.db.units import (
    _build_unit_name_map_for_pairs,
    _is_unknown_intensity_unit_name,
    _sql_freq_zone_expr,
    canonical_intensity_unit_key,
)



def _finalize_intensity_cluster_map(
    clusters: dict[str, dict[str, object]],
) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for _, c in clusters.items():
        ids_set = c.get("ids") if isinstance(c.get("ids"), set) else set()
        disp = str(c.get("unit_name") or "").strip()
        if not disp:
            continue
        out.append(
            {
                "unit_name": disp,
                "sessions": int(c.get("sessions") or 0),
                "correspondents": int(len(ids_set)),
            }
        )
    out.sort(
        key=lambda x: (
            -int(x.get("sessions") or 0),
            str(x.get("unit_name") or "").lower(),
        )
    )
    return out


def _merge_intensity_agg_row(
    clusters: dict[str, dict[str, object]],
    unit_name_map: dict[tuple[str, str], str],
    rep_freq: str,
    group_code: str,
    sess_cnt: int,
    ids_csv: str,
) -> None:
    freq = str(rep_freq or "").strip()
    grp = str(group_code or "").strip()
    if not freq or not grp:
        return
    unit_name = str(unit_name_map.get((freq, grp)) or "").strip()
    if _is_unknown_intensity_unit_name(unit_name):
        return
    ckey = canonical_intensity_unit_key(unit_name)
    if not ckey:
        return
    c = clusters.get(ckey)
    if not c:
        c = {"unit_name": unit_name, "sessions": 0, "ids": set()}
        clusters[ckey] = c
    else:
        prev = str(c.get("unit_name") or "").strip()
        if len(unit_name) > len(prev):
            c["unit_name"] = unit_name
    c["sessions"] = int(c.get("sessions") or 0) + int(sess_cnt or 0)
    if ids_csv:
        for x in str(ids_csv).split(","):
            s = str(x or "").strip()
            if s:
                c["ids"].add(s)


def get_network_intensity_clusters(
    conn: sqlite3.Connection,
    *,
    seans_conn: sqlite3.Connection | None = None,
    start_dt: str,
    end_dt: str,
    position_name: str | None,
) -> list[dict[str, object]]:
    """
    Кластеризация радиосетей по unit_name за период.

    - sessions: сумма COUNT(DISTINCT date_time) по парам (freq_zone, group_) кластера
      (при слиянии сетей в одну колонку один момент времени на разных частотах зоны
      может учитываться дважды — компромисс ради производительности на больших БД).
    - correspondents: уникальные id внутри кластера (из GROUP_CONCAT; лимит снимает PRAGMA group_concat_max_len).

    Используется замкнутый интервал времени [start_dt, end_dt] (включительно с обеих сторон),
    чтобы период совпадал с учётом сеансов (get_doc_stats / api_sessions_table_data).

    Важно: агрегируем в SQL по (freq_zone, group_), без полного сканирования всех строк в Python —
    иначе на больших seans.sqlite / main.sqlite отчёт «Общий анализ» падает по памяти/таймауту (500).
    Seans-данные берутся из seans.sqlite после миграции (resolve_seans_conn_for_queries).
    """
    init_db(conn)
    sc = resolve_seans_conn_for_queries(conn, seans_conn)
    start_dt = str(start_dt or "").strip()
    end_dt = str(end_dt or "").strip()
    if not start_dt or not end_dt:
        return []

    params: list[Any] = [start_dt, end_dt]
    where = "date_time >= ? AND date_time <= ?"
    if position_name:
        where += " AND client_name=?"
        params.append(str(position_name))

    fz = _sql_freq_zone_expr("frequency")
    source_sql = """
        SELECT date_time, frequency, group_, id, client_name FROM seanses
        UNION ALL
        SELECT date_time, frequency, group_, id, client_name FROM seanses_archive
    """
    seans_rows = sc.execute(
        f"""
        WITH scoped AS (
            SELECT TRIM(frequency) AS frequency, TRIM(group_) AS group_,
                   date_time, id,
                   {fz} AS freq_zone
            FROM ({source_sql})
            WHERE {where}
        ),
        filtered AS (
            SELECT * FROM scoped
            WHERE TRIM(COALESCE(frequency, '')) != ''
              AND TRIM(COALESCE(group_, '')) != ''
        )
        SELECT MIN(TRIM(frequency)) AS rep_freq, group_,
               COUNT(DISTINCT date_time) AS sess_cnt,
               GROUP_CONCAT(DISTINCT id) AS ids_csv
        FROM filtered
        GROUP BY freq_zone, group_
        """,
        tuple(params),
    ).fetchall()

    clusters: dict[str, dict[str, object]] = {}
    pair_list = [
        (str(r[0] or "").strip(), str(r[1] or "").strip()) for r in seans_rows
    ]
    unit_name_map = _build_unit_name_map_for_pairs(conn, pair_list)
    for r in seans_rows:
        _merge_intensity_agg_row(
            clusters,
            unit_name_map,
            str(r[0] or "").strip(),
            str(r[1] or "").strip(),
            int(r[2] or 0),
            str(r[3] or "") if r[3] is not None else "",
        )
    return _finalize_intensity_cluster_map(clusters)


def get_network_intensity_clusters_dual(
    conn: sqlite3.Connection,
    *,
    seans_conn: sqlite3.Connection | None = None,
    cur_start_dt: str,
    cur_end_dt: str,
    prev_start_dt: str,
    prev_end_dt: str,
    position_name: str | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """
    Текущий и предыдущий период «Общего анализа» одним проходом по seanses.
    Один запрос к unit для имён подразделений вместо двух полных циклов.
    """
    init_db(conn)
    sc = resolve_seans_conn_for_queries(conn, seans_conn)
    cur_start_dt = str(cur_start_dt or "").strip()
    cur_end_dt = str(cur_end_dt or "").strip()
    prev_start_dt = str(prev_start_dt or "").strip()
    prev_end_dt = str(prev_end_dt or "").strip()
    if not cur_start_dt or not cur_end_dt or not prev_start_dt or not prev_end_dt:
        return [], []

    params: list[Any] = [
        cur_start_dt,
        cur_end_dt,
        prev_start_dt,
        prev_end_dt,
        cur_start_dt,
        cur_end_dt,
        prev_start_dt,
        prev_end_dt,
    ]
    client_filter = ""
    if position_name:
        client_filter = " AND client_name=?"
        params.append(str(position_name))

    fz = _sql_freq_zone_expr("frequency")
    source_sql = """
        SELECT date_time, frequency, group_, id, client_name FROM seanses
        UNION ALL
        SELECT date_time, frequency, group_, id, client_name FROM seanses_archive
    """
    seans_rows = sc.execute(
        f"""
        WITH scoped AS (
            SELECT TRIM(frequency) AS frequency, TRIM(group_) AS group_,
                   date_time, id,
                   {fz} AS freq_zone,
                   CASE
                     WHEN date_time >= ? AND date_time <= ? THEN 'cur'
                     WHEN date_time >= ? AND date_time <= ? THEN 'prev'
                   END AS period
            FROM ({source_sql})
            WHERE (
              (date_time >= ? AND date_time <= ?)
              OR (date_time >= ? AND date_time <= ?)
            ){client_filter}
        ),
        filtered AS (
            SELECT * FROM scoped
            WHERE period IS NOT NULL
              AND TRIM(COALESCE(frequency, '')) != ''
              AND TRIM(COALESCE(group_, '')) != ''
        )
        SELECT period, MIN(TRIM(frequency)) AS rep_freq, group_,
               COUNT(DISTINCT date_time) AS sess_cnt,
               GROUP_CONCAT(DISTINCT id) AS ids_csv
        FROM filtered
        GROUP BY period, freq_zone, group_
        """,
        tuple(params),
    ).fetchall()

    cur_clusters: dict[str, dict[str, object]] = {}
    prev_clusters: dict[str, dict[str, object]] = {}
    pair_list: list[tuple[str, str]] = []
    for r in seans_rows:
        freq = str(r[1] or "").strip()
        grp = str(r[2] or "").strip()
        if freq and grp:
            pair_list.append((freq, grp))

    unit_name_map = _build_unit_name_map_for_pairs(conn, pair_list)
    for r in seans_rows:
        period = str(r[0] or "").strip()
        target = cur_clusters if period == "cur" else prev_clusters if period == "prev" else None
        if target is None:
            continue
        _merge_intensity_agg_row(
            target,
            unit_name_map,
            str(r[1] or "").strip(),
            str(r[2] or "").strip(),
            int(r[3] or 0),
            str(r[4] or "") if r[4] is not None else "",
        )

    return (
        _finalize_intensity_cluster_map(cur_clusters),
        _finalize_intensity_cluster_map(prev_clusters),
    )


def _dt_time_part(dt: str) -> str:
    """HH:MM[:SS] из ISO/SQL datetime или пустая строка, если время не задано."""
    s = str(dt or "").strip()
    if len(s) <= 10:
        return ""
    if s[10] not in (" ", "T"):
        return ""
    if len(s) >= 19:
        return s[11:19]
    if len(s) >= 16:
        return s[11:16]
    return ""


def _is_calendar_day_start(dt: str) -> bool:
    t = _dt_time_part(dt)
    return t in {"", "00:00", "00:00:00"}


def _is_calendar_day_end(dt: str) -> bool:
    t = _dt_time_part(dt)
    return t in {"", "23:59", "23:59:00", "23:59:59"}


def _date_only_window(start_dt: str, end_dt: str) -> tuple[str, str] | None:
    """Календарное окно для seanses_daily_agg — только полные сутки (00:00 … 23:59).

    Субсуточные диапазоны (2 ч., произвольное время) должны идти через точный скан seanses,
    иначе daily agg вернёт данные за весь день.
    """
    start = str(start_dt or "").strip()
    end = str(end_dt or "").strip()
    if len(start) < 10 or len(end) < 10:
        return None
    if not _is_calendar_day_start(start) or not _is_calendar_day_end(end):
        return None
    start_date = start[:10]
    end_date = end[:10]
    if start_date > end_date:
        return None
    return start_date, end_date


def _network_prev_daily_window(
    cur_start_dt: str, prev_start_dt: str
) -> tuple[str, str] | None:
    """Календарные дни предыдущего периода для daily agg (без перекрытия с текущим).

    prev_end_query часто попадает на ту же дату, что и начало текущего периода
    (напр. 2026-06-05 00:00:59) — нельзя брать end[:10] для prev, иначе день
    текущего периода удвоится в агрегате.
    """
    if len(str(cur_start_dt or "")) < 10 or len(str(prev_start_dt or "")) < 10:
        return None
    try:
        from datetime import date, timedelta

        cur_start_date = date.fromisoformat(str(cur_start_dt)[:10])
        prev_start_date = date.fromisoformat(str(prev_start_dt)[:10])
    except ValueError:
        return None
    prev_end_date = cur_start_date - timedelta(days=1)
    if prev_start_date > prev_end_date:
        return None
    return prev_start_date.isoformat(), prev_end_date.isoformat()


def get_network_intensity_clusters_dual_daily(
    conn: sqlite3.Connection,
    *,
    seans_conn: sqlite3.Connection | None = None,
    cur_start_dt: str,
    cur_end_dt: str,
    prev_start_dt: str,
    prev_end_dt: str,
    position_name: str | None,
) -> tuple[list[dict[str, object]], list[dict[str, object]]] | None:
    cur_days = _date_only_window(cur_start_dt, cur_end_dt)
    prev_days = _network_prev_daily_window(cur_start_dt, prev_start_dt)
    if not cur_days or not prev_days:
        return None
    init_db(conn)
    sc = resolve_seans_conn_for_queries(conn, seans_conn)
    init_daily_aggregates(sc)
    has_rows = sc.execute("SELECT 1 FROM seanses_daily_agg LIMIT 1").fetchone()
    if not has_rows:
        refresh_seanses_daily_aggregates(sc)
    params: list[Any] = [cur_days[0], cur_days[1], prev_days[0], prev_days[1], cur_days[0], cur_days[1], prev_days[0], prev_days[1]]
    client_filter = ""
    if position_name:
        client_filter = " AND client_name=?"
        params.append(str(position_name))
    rows = sc.execute(
        f"""
        WITH scoped AS (
            SELECT
                CASE
                  WHEN day BETWEEN ? AND ? THEN 'cur'
                  WHEN day BETWEEN ? AND ? THEN 'prev'
                END AS period,
                frequency,
                group_,
                sessions_count,
                ids_csv
            FROM seanses_daily_agg
            WHERE ((day BETWEEN ? AND ?) OR (day BETWEEN ? AND ?)){client_filter}
        )
        SELECT period, frequency, group_,
               SUM(sessions_count) AS sess_cnt,
               GROUP_CONCAT(ids_csv) AS ids_csv
        FROM scoped
        WHERE period IS NOT NULL
        GROUP BY period, frequency, group_
        """,
        tuple(params),
    ).fetchall()
    cur_clusters: dict[str, dict[str, object]] = {}
    prev_clusters: dict[str, dict[str, object]] = {}
    pair_list = [(str(r[1] or "").strip(), str(r[2] or "").strip()) for r in rows]
    unit_name_map = _build_unit_name_map_for_pairs(conn, pair_list)
    for r in rows:
        period = str(r[0] or "").strip()
        target = cur_clusters if period == "cur" else prev_clusters if period == "prev" else None
        if target is None:
            continue
        _merge_intensity_agg_row(
            target,
            unit_name_map,
            str(r[1] or "").strip(),
            str(r[2] or "").strip(),
            int(r[3] or 0),
            str(r[4] or "") if r[4] is not None else "",
        )
    return (
        _finalize_intensity_cluster_map(cur_clusters),
        _finalize_intensity_cluster_map(prev_clusters),
    )


__all__ = [
    "get_network_intensity_clusters",
    "get_network_intensity_clusters_dual",
    "get_network_intensity_clusters_dual_daily",
]
