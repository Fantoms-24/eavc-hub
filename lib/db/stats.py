"""Статистика БД и документов (физически вынесено из ``_impl``)."""
from __future__ import annotations

from collections import Counter, defaultdict
import sqlite3
from typing import Any

from web_portal.lib.db.seans_schema import (
    _table_exists,
    init_daily_aggregates,
    init_seans_tables,
    refresh_seanses_daily_aggregates,
)


def get_db_stats_legacy(
    conn: sqlite3.Connection, client_name: str | None = None
) -> dict[str, Any]:
    """
    Статистика для загруженной legacy БД (без миграций / init_db()).
    Если есть колонка client_name — можно фильтровать по позиции, иначе фильтр игнорируется.
    """
    from web_portal.lib.db.sql_util import _pick_first, _table_columns
    if not _table_exists(conn, "seanses"):
        return {"total_records": 0, "last_datetime": None}
    cols = _table_columns(conn, "seanses")
    dt_c = _pick_first(cols, ["date_time", "datetime", "dt"])
    if not dt_c:
        return {"total_records": 0, "last_datetime": None}
    has_client = "client_name" in cols
    try:
        if client_name and has_client:
            total = conn.execute(
                "SELECT COUNT(*) FROM seanses WHERE client_name=?",
                (client_name,),
            ).fetchone()[0]
            last_dt = conn.execute(
                f"SELECT MAX({dt_c}) FROM seanses WHERE client_name=?",
                (client_name,),
            ).fetchone()[0]
        else:
            total = conn.execute("SELECT COUNT(*) FROM seanses;").fetchone()[0]
            last_dt = conn.execute(f"SELECT MAX({dt_c}) FROM seanses;").fetchone()[0]
    except Exception:
        return {"total_records": 0, "last_datetime": None}
    return {"total_records": int(total or 0), "last_datetime": last_dt or None}


def get_doc_stats_legacy(
    conn: sqlite3.Connection,
    date_time_1: str,
    date_time_2: str,
    client_name: str | None = None,
) -> list[dict[str, Any]]:
    """
    Как get_doc_stats(), но для legacy БД: без init_db() и с авто-детектом колонок.
    """
    from web_portal.lib.db.sql_util import _pick_first, _table_columns
    from web_portal.lib.db.units import _unit_map_legacy
    if not _table_exists(conn, "seanses"):
        return []
    cols = _table_columns(conn, "seanses")
    dt_c = _pick_first(cols, ["date_time", "datetime", "dt"])
    freq_c = _pick_first(cols, ["frequency", "freq", "f"])
    grp_c = _pick_first(cols, ["group_", "group", "grp", "g"])
    id_c = _pick_first(cols, ["id", "correspondent", "code"])
    if not (dt_c and freq_c and grp_c and id_c):
        return []

    has_client = "client_name" in cols
    if client_name and has_client:
        sql = f"""
            SELECT {freq_c} as frequency, {grp_c} as group_, COUNT(DISTINCT {dt_c}) as cnt,
                   GROUP_CONCAT(DISTINCT {id_c}) as ids
            FROM seanses
            WHERE {dt_c} BETWEEN ? AND ? AND client_name = ?
            GROUP BY {freq_c}, {grp_c}
            ORDER BY {freq_c}, {grp_c};
        """
        params: tuple[Any, ...] = (date_time_1, date_time_2, client_name)
    else:
        sql = f"""
            SELECT {freq_c} as frequency, {grp_c} as group_, COUNT(DISTINCT {dt_c}) as cnt,
                   GROUP_CONCAT(DISTINCT {id_c}) as ids
            FROM seanses
            WHERE {dt_c} BETWEEN ? AND ?
            GROUP BY {freq_c}, {grp_c}
            ORDER BY {freq_c}, {grp_c};
        """
        params = (date_time_1, date_time_2)

    try:
        seanses = conn.execute(sql, params).fetchall()
    except Exception:
        return []

    name_map = _unit_map_legacy(conn)
    res: list[dict[str, Any]] = []
    for row in seanses or []:
        freq = str(row[0] or "")
        group_ = str(row[1] or "")
        count = int(row[2] or 0)
        ids_csv = str(row[3] or "")

        unit_name = name_map.get((freq, group_), "")
        if not unit_name:
            unit_name = name_map.get((freq, "*"), "")
        if not unit_name:
            unit_name = name_map.get(("*", group_), "")
        if not unit_name:
            unit_name = ""

        res.append(
            {
                "frequency": freq,
                "group": group_,
                "name": unit_name,
                "count": count,
                "ids_csv": ids_csv,
                "ids_pretty": format_ids(ids_csv),
            }
        )
    return res


def get_db_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Возвращает статистику по сеансам в БД.
    Аналогично db_stat() из примера.
    """
    init_seans_tables(conn)
    cur = conn.cursor()
    try:
        total_records = cur.execute("SELECT COUNT(*) FROM seanses;").fetchone()[0]
        total_seanses = cur.execute(
            "SELECT COUNT(DISTINCT date_time) FROM seanses;"
        ).fetchone()[0]
        total_days = cur.execute(
            "SELECT COUNT(DISTINCT strftime('%Y-%m-%d', date_time)) FROM seanses;"
        ).fetchone()[0]
        last_dt = cur.execute("SELECT MAX(date_time) FROM seanses;").fetchone()[0]
        return {
            "total_records": int(total_records or 0),
            "total_seanses": int(total_seanses or 0),
            "total_days": int(total_days or 0),
            "last_datetime": last_dt or "2000-01-01",
        }
    except Exception:
        return {
            "total_records": 0,
            "total_seanses": 0,
            "total_days": 0,
            "last_datetime": "2000-01-01",
        }


def format_ids(ids_csv: str) -> str:
    all_ids = [x.strip() for x in (ids_csv or "").split(",") if x.strip()]
    if not all_ids:
        return ""
    counts = Counter(sorted(all_ids))
    # как в desktop: "id (c),id2 (c2)"
    return ",".join(f"{id_} ({c})" for id_, c in counts.most_common())


def get_doc_stats(
    conn: sqlite3.Connection,
    date_time_1: str,
    date_time_2: str,
    client_name: str | None = None,
    *,
    skip_init: bool = False,
    unit_conn: sqlite3.Connection | None = None,
) -> list[dict[str, Any]]:
    """
    Аналог src.database.get_doc_stats, но возвращает список dict для API.
    Оптимизирован для быстрой работы с большими объемами данных.
    Автоматически применяет unit из online_search только для групп из выбранного периода.

    Сеансы агрегируются по (freq_zone, group_): freq_zone = целая часть МГц, чтобы
    151.0000 и 151.0020 с одной группой не дублировались в таблице.

    Списки ID по сетям собираются в Python из CTE id_counts: вложенный
    «FROM (SELECT * FROM id_counts ORDER BY ...) GROUP BY» + GROUP_CONCAT в SQLite
    в ряде версий давал неверную группировку (один и тот же список id во всех строках).
    """
    from web_portal.lib.db.units import _build_unit_name_map_for_pairs, _sql_freq_zone_expr
    if not skip_init:
        init_seans_tables(conn)
    cur = conn.cursor()

    fz = _sql_freq_zone_expr("frequency")
    source_sql = """
        SELECT date_time, frequency, group_, id, client_name FROM seanses
        UNION ALL
        SELECT date_time, frequency, group_, id, client_name FROM seanses_archive
    """
    # Подсчет сеансов: 1 result0.txt = 1 сеанс связи
    # Уникальные date_time на пару (freq_zone, group_).
    # ids: "id (cnt),id2 (cnt2)" — cnt = число сеансов (DISTINCT date_time) на id в зоне.
    if client_name:
        params_base = (date_time_1, date_time_2, client_name)
        cte = f"""
            WITH base AS (
                SELECT TRIM(frequency) AS frequency, TRIM(group_) AS group_,
                       date_time, id,
                       {fz} AS freq_zone
                FROM ({source_sql})
                WHERE date_time BETWEEN ? AND ? AND client_name = ?
            ),
            filtered AS (
                SELECT * FROM base
                WHERE TRIM(COALESCE(frequency, '')) != ''
                  AND TRIM(COALESCE(group_, '')) != ''
            )
        """
    else:
        params_base = (date_time_1, date_time_2)
        cte = f"""
            WITH base AS (
                SELECT TRIM(frequency) AS frequency, TRIM(group_) AS group_,
                       date_time, id,
                       {fz} AS freq_zone
                FROM ({source_sql})
                WHERE date_time BETWEEN ? AND ?
            ),
            filtered AS (
                SELECT * FROM base
                WHERE TRIM(COALESCE(frequency, '')) != ''
                  AND TRIM(COALESCE(group_, '')) != ''
            )
        """

    sql_id_counts = (
        cte
        + """
        , id_counts AS (
            SELECT freq_zone, group_, id, COUNT(DISTINCT date_time) AS id_cnt
            FROM filtered
            GROUP BY freq_zone, group_, id
        )
        SELECT freq_zone, group_, id, id_cnt FROM id_counts
    """
    )
    id_rows = cur.execute(sql_id_counts, params_base).fetchall()

    by_key: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for r in id_rows:
        fz_k = str(r[0] or "")
        g_k = str(r[1] or "")
        iid = str(r[2] or "")
        ic = int(r[3] or 0)
        if iid:
            by_key[(fz_k, g_k)].append((iid, ic))
    ids_map: dict[tuple[str, str], str] = {}
    for k, pairs in by_key.items():
        pairs.sort(key=lambda t: (-t[1], t[0]))
        ids_map[k] = ",".join(f"{pid} ({cnt})" for pid, cnt in pairs)

    sql_main = (
        cte
        + """
        , sessions AS (
            SELECT freq_zone, group_, COUNT(DISTINCT date_time) AS cnt
            FROM filtered
            GROUP BY freq_zone, group_
        ),
        canon AS (
            SELECT freq_zone, group_, MIN(TRIM(frequency)) AS frequency_display
            FROM filtered
            GROUP BY freq_zone, group_
        )
        SELECT c.freq_zone, c.frequency_display, s.group_, s.cnt
        FROM sessions s
        JOIN canon c USING (freq_zone, group_)
        ORDER BY c.frequency_display, s.group_;
    """
    )
    seanses = cur.execute(sql_main, params_base).fetchall()

    # ВАЖНО: в сеансах показываем названия только из unit.
    # Синхронизация unit делается отдельно из online_search (импорт/обновления).
    pair_list = [(str(row[1] or ""), str(row[2] or "")) for row in seanses]
    unit_name_map = _build_unit_name_map_for_pairs(unit_conn or conn, pair_list)

    res: list[dict[str, Any]] = []
    for row in seanses:
        fz_k = str(row[0] or "")
        freq = str(row[1] or "")
        group_ = str(row[2] or "")
        count = int(row[3] or 0)
        ids_csv = ids_map.get((fz_k, group_), "")

        unit_name = unit_name_map.get((freq, group_), "").strip()

        res.append(
            {
                "frequency": freq,
                "group": group_,
                "name": unit_name,
                "count": count,
                "ids_csv": ids_csv,
                # ids_csv уже в компактном виде "id (cnt),id2 (cnt2)"
                "ids_pretty": ids_csv,
            }
        )

    # Сортируем: сначала записи с названием (unit_name не пустое), затем без названия
    # Сортировка: записи с названием идут первыми (not x["name"] = False для записей с названием)
    res.sort(key=lambda x: (not bool(x["name"]), x["frequency"], x["group"]))

    return res


def _seanses_period_has_rows(
    conn: sqlite3.Connection,
    date_time_1: str,
    date_time_2: str,
    client_name: str | None = None,
) -> bool:
    """Быстрая проверка: есть ли хотя бы одна строка сеансов в периоде (seanses + archive)."""
    if client_name:
        row = conn.execute(
            """
            SELECT 1 FROM seanses
            WHERE date_time BETWEEN ? AND ? AND client_name = ?
            LIMIT 1
            """,
            (date_time_1, date_time_2, client_name),
        ).fetchone()
        if row:
            return True
        if _table_exists(conn, "seanses_archive"):
            row = conn.execute(
                """
                SELECT 1 FROM seanses_archive
                WHERE date_time BETWEEN ? AND ? AND client_name = ?
                LIMIT 1
                """,
                (date_time_1, date_time_2, client_name),
            ).fetchone()
            return bool(row)
        return False
    row = conn.execute(
        """
        SELECT 1 FROM seanses
        WHERE date_time BETWEEN ? AND ?
        LIMIT 1
        """,
        (date_time_1, date_time_2),
    ).fetchone()
    if row:
        return True
    if not _table_exists(conn, "seanses_archive"):
        return False
    row = conn.execute(
        """
        SELECT 1 FROM seanses_archive
        WHERE date_time BETWEEN ? AND ?
        LIMIT 1
        """,
        (date_time_1, date_time_2),
    ).fetchone()
    return bool(row)


def _doc_stats_page_ids_from_daily_agg(
    cur: sqlite3.Cursor,
    *,
    page_keys: list[tuple[str, str]],
    day_from: str,
    day_to: str,
    client_name: str | None,
    fz: str,
) -> dict[tuple[str, str], str]:
    """ids_csv для страницы из seanses_daily_agg (без полного скана seanses)."""
    if not page_keys:
        return {}
    chunk_size = 80
    out: dict[tuple[str, str], str] = {}
    for i in range(0, len(page_keys), chunk_size):
        chunk = page_keys[i : i + chunk_size]
        out.update(
            _doc_stats_page_ids_from_daily_agg_chunk(
                cur,
                page_keys=chunk,
                day_from=day_from,
                day_to=day_to,
                client_name=client_name,
                fz=fz,
            )
        )
    return out


def _doc_stats_page_ids_from_daily_agg_chunk(
    cur: sqlite3.Cursor,
    *,
    page_keys: list[tuple[str, str]],
    day_from: str,
    day_to: str,
    client_name: str | None,
    fz: str,
) -> dict[tuple[str, str], str]:
    if not page_keys:
        return {}
    values_sql = ",".join(["(?, ?)"] * len(page_keys))
    key_params: list[Any] = []
    for fz_k, group_k in page_keys:
        key_params.extend([fz_k, group_k])
    if client_name:
        agg_where = "day BETWEEN ? AND ? AND client_name = ?"
        base_params: tuple[Any, ...] = (day_from, day_to, client_name)
    else:
        agg_where = "day BETWEEN ? AND ?"
        base_params = (day_from, day_to)
    sql_ids = f"""
        WITH page_keys(freq_zone, group_) AS (VALUES {values_sql}),
        scoped AS (
            SELECT {fz} AS freq_zone, TRIM(group_) AS group_, ids_csv
            FROM seanses_daily_agg
            WHERE {agg_where}
        )
        SELECT pk.freq_zone, pk.group_, s.ids_csv
        FROM page_keys pk
        INNER JOIN scoped s
          ON s.freq_zone = pk.freq_zone AND s.group_ = pk.group_
        WHERE TRIM(COALESCE(s.ids_csv, '')) != ''
    """
    rows = cur.execute(sql_ids, (*key_params, *base_params)).fetchall()
    merged_by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rows or []:
        fz_k = str(r[0] or "")
        g_k = str(r[1] or "")
        csv = str(r[2] or "").strip()
        if csv:
            merged_by_key[(fz_k, g_k)].append(csv)
    ids_map: dict[tuple[str, str], str] = {}
    for k, parts in merged_by_key.items():
        ids_map[k] = format_ids(",".join(parts))
    return ids_map


def _doc_stats_page_ids_map_chunk(
    cur: sqlite3.Cursor,
    *,
    page_keys: list[tuple[str, str]],
    source_sql: str,
    where: str,
    params_base: tuple[Any, ...],
    fz: str,
) -> dict[tuple[str, str], str]:
    """ids_csv «id (cnt)» для подмножества пар (freq_zone, group_) текущей страницы."""
    if not page_keys:
        return {}
    _ = source_sql
    values_sql = ",".join(["(?, ?)"] * len(page_keys))
    key_params: list[Any] = []
    for fz_k, group_k in page_keys:
        key_params.extend([fz_k, group_k])
    unique_groups = sorted({str(g or "").strip() for _, g in page_keys if str(g or "").strip()})
    group_filter_sql = ""
    group_params: list[Any] = []
    if unique_groups:
        group_ph = ",".join("?" * len(unique_groups))
        group_filter_sql = f" AND TRIM(group_) IN ({group_ph})"
        group_params = list(unique_groups)
    conn = cur.connection
    archive_union = ""
    archive_params: tuple[Any, ...] = ()
    if _table_exists(conn, "seanses_archive"):
        archive_union = f"""
            UNION ALL
            SELECT date_time, id, TRIM(group_) AS group_, {fz} AS freq_zone
            FROM seanses_archive
            WHERE {where}{group_filter_sql}
        """
        archive_params = (*params_base, *group_params)
    sql_ids = f"""
        WITH page_keys(freq_zone, group_) AS (VALUES {values_sql}),
        unioned AS (
            SELECT date_time, id, TRIM(group_) AS group_, {fz} AS freq_zone
            FROM seanses
            WHERE {where}{group_filter_sql}
            {archive_union}
        )
        SELECT u.freq_zone, u.group_, u.id, COUNT(DISTINCT u.date_time) AS id_cnt
        FROM unioned u
        INNER JOIN page_keys pk
          ON pk.freq_zone = u.freq_zone AND pk.group_ = u.group_
        WHERE TRIM(COALESCE(u.id, '')) != ''
        GROUP BY u.freq_zone, u.group_, u.id
    """
    id_rows = cur.execute(
        sql_ids, (*key_params, *params_base, *group_params, *archive_params)
    ).fetchall()
    by_key: dict[tuple[str, str], list[tuple[str, int]]] = defaultdict(list)
    for r in id_rows:
        fz_k = str(r[0] or "")
        g_k = str(r[1] or "")
        iid = str(r[2] or "")
        ic = int(r[3] or 0)
        if iid:
            by_key[(fz_k, g_k)].append((iid, ic))
    ids_map: dict[tuple[str, str], str] = {}
    for k, pairs in by_key.items():
        pairs.sort(key=lambda t: (-t[1], t[0]))
        ids_map[k] = ",".join(f"{pid} ({cnt})" for pid, cnt in pairs)
    return ids_map


def _doc_stats_page_ids_map(
    cur: sqlite3.Cursor,
    *,
    page_keys: list[tuple[str, str]],
    source_sql: str,
    where: str,
    params_base: tuple[Any, ...],
    fz: str,
) -> dict[tuple[str, str], str]:
    """ids_csv «id (cnt)» только для пар (freq_zone, group_) текущей страницы."""
    if not page_keys:
        return {}
    _ = source_sql  # legacy param; запросы идут напрямую в seanses / archive
    chunk_size = 80
    out: dict[tuple[str, str], str] = {}
    for i in range(0, len(page_keys), chunk_size):
        chunk = page_keys[i : i + chunk_size]
        out.update(
            _doc_stats_page_ids_map_chunk(
                cur,
                page_keys=chunk,
                source_sql=source_sql,
                where=where,
                params_base=params_base,
                fz=fz,
            )
        )
    return out


def _doc_stats_page_grouped_sql(*, join_unit: bool) -> str:
    if join_unit:
        unit_expr = "COALESCE(NULLIF(TRIM(u.name), ''), '') AS unit_name"
        unit_join = (
            "LEFT JOIN unit u ON u.frequency = c.frequency_display AND u.group_ = s.group_"
        )
    else:
        unit_expr = "'' AS unit_name"
        unit_join = ""
    return f"""
        grouped AS (
            SELECT c.freq_zone, c.frequency_display, s.group_, s.cnt,
                   {unit_expr}
            FROM sessions s
            JOIN canon c USING (freq_zone, group_)
            {unit_join}
        )
    """


def _doc_stats_page_build_result(
    conn: sqlite3.Connection,
    page_rows: list[Any],
    ids_map: dict[tuple[str, str], str],
    *,
    limit_v: int,
    offset_v: int,
    unit_conn: sqlite3.Connection | None = None,
) -> dict[str, Any]:
    from web_portal.lib.db.units import _build_unit_name_map_for_pairs
    total = int(page_rows[0][5] or 0) if page_rows else 0
    pair_list = [(str(row[1] or ""), str(row[2] or "")) for row in page_rows]
    uc = unit_conn or conn
    unit_name_map = _build_unit_name_map_for_pairs(uc, pair_list)
    data: list[dict[str, Any]] = []
    for row in page_rows:
        fz_k = str(row[0] or "")
        freq = str(row[1] or "")
        group_ = str(row[2] or "")
        ids_csv = ids_map.get((fz_k, group_), "")
        data.append(
            {
                "frequency": freq,
                "group": group_,
                "name": unit_name_map.get((freq, group_), str(row[4] or "")).strip(),
                "count": int(row[3] or 0),
                "ids_csv": ids_csv,
                "ids_pretty": ids_csv,
            }
        )
    return {
        "data": data,
        "total": total,
        "limit": limit_v,
        "offset": offset_v,
        "has_more": offset_v + limit_v < total,
    }


def _seans_sessions_total_for_days(
    conn: sqlite3.Connection,
    day_from: str,
    day_to: str,
    client_name: str | None,
) -> int:
    params: list[Any] = [day_from, day_to]
    where = "substr(date_time, 1, 10) BETWEEN ? AND ?"
    if client_name:
        where += " AND client_name = ?"
        params.append(client_name)
    sql = f"""
        SELECT COUNT(DISTINCT date_time)
        FROM (
            SELECT date_time FROM seanses WHERE {where}
            UNION ALL
            SELECT date_time FROM seanses_archive WHERE {where}
        )
    """
    try:
        return int(conn.execute(sql, tuple(params + params)).fetchone()[0] or 0)
    except Exception:
        return 0


def _seans_network_pairs_for_days(
    conn: sqlite3.Connection,
    day_from: str,
    day_to: str,
    client_name: str | None,
) -> int:
    """Число пар (частота, группа) в seanses + archive за диапазон дней."""
    from web_portal.lib.db.units import _sql_freq_zone_expr
    params: list[Any] = [day_from, day_to]
    where = "substr(date_time, 1, 10) BETWEEN ? AND ?"
    if client_name:
        where += " AND client_name = ?"
        params.append(client_name)
    fz = _sql_freq_zone_expr("frequency")
    sql = f"""
        SELECT COUNT(*) FROM (
            SELECT {fz} AS freq_zone, TRIM(group_) AS group_
            FROM seanses
            WHERE {where}
              AND TRIM(COALESCE(frequency, '')) != ''
              AND TRIM(COALESCE(group_, '')) != ''
            GROUP BY freq_zone, TRIM(group_)
            UNION
            SELECT {fz} AS freq_zone, TRIM(group_) AS group_
            FROM seanses_archive
            WHERE {where}
              AND TRIM(COALESCE(frequency, '')) != ''
              AND TRIM(COALESCE(group_, '')) != ''
            GROUP BY freq_zone, TRIM(group_)
        )
    """
    try:
        return int(conn.execute(sql, tuple(params + params)).fetchone()[0] or 0)
    except Exception:
        return 0


def _daily_agg_network_pairs_for_days(
    conn: sqlite3.Connection,
    day_from: str,
    day_to: str,
    client_name: str | None,
) -> int:
    from web_portal.lib.db.units import _sql_freq_zone_expr
    fz = _sql_freq_zone_expr("frequency")
    if client_name:
        row = conn.execute(
            f"""
            SELECT COUNT(*) FROM (
                SELECT {fz} AS freq_zone, TRIM(group_) AS group_
                FROM seanses_daily_agg
                WHERE day BETWEEN ? AND ? AND client_name = ?
                  AND TRIM(COALESCE(frequency, '')) != ''
                  AND TRIM(COALESCE(group_, '')) != ''
                GROUP BY freq_zone, TRIM(group_)
            )
            """,
            (day_from, day_to, client_name),
        ).fetchone()
    else:
        row = conn.execute(
            f"""
            SELECT COUNT(*) FROM (
                SELECT {fz} AS freq_zone, TRIM(group_) AS group_
                FROM seanses_daily_agg
                WHERE day BETWEEN ? AND ?
                  AND TRIM(COALESCE(frequency, '')) != ''
                  AND TRIM(COALESCE(group_, '')) != ''
                GROUP BY freq_zone, TRIM(group_)
            )
            """,
            (day_from, day_to),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def _daily_agg_sessions_total_for_days(
    conn: sqlite3.Connection,
    day_from: str,
    day_to: str,
    client_name: str | None,
) -> int:
    if client_name:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(sessions_count), 0)
            FROM seanses_daily_agg
            WHERE day BETWEEN ? AND ? AND client_name = ?
            """,
            (day_from, day_to, client_name),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(sessions_count), 0)
            FROM seanses_daily_agg
            WHERE day BETWEEN ? AND ?
            """,
            (day_from, day_to),
        ).fetchone()
    return int(row[0] or 0) if row else 0


def _try_get_doc_stats_page_from_daily_agg(
    conn: sqlite3.Connection,
    date_time_1: str,
    date_time_2: str,
    client_name: str | None = None,
    *,
    limit_v: int,
    offset_v: int,
    unit_conn: sqlite3.Connection | None = None,
) -> dict[str, Any] | None:
    """
    Быстрый путь для календарных суток (00:00–23:59): агрегат seanses_daily_agg
    вместо полного скана seanses + archive.
    """
    from web_portal.lib.db.network_intensity import _date_only_window
    from web_portal.lib.db.units import _sql_freq_zone_expr
    days = _date_only_window(date_time_1, date_time_2)
    if not days:
        return None
    day_from, day_to = days
    init_daily_aggregates(conn)
    from web_portal.lib.seans_db import connection_path_is_seans_storage

    join_unit = not connection_path_is_seans_storage(conn)
    if client_name:
        agg_params: tuple[Any, ...] = (day_from, day_to, client_name)
        agg_where = "day BETWEEN ? AND ? AND client_name = ?"
    else:
        agg_params = (day_from, day_to)
        agg_where = "day BETWEEN ? AND ?"
    agg_count = int(
        conn.execute(
            f"SELECT COUNT(*) FROM seanses_daily_agg WHERE {agg_where}",
            agg_params,
        ).fetchone()[0]
        or 0
    )
    if agg_count == 0:
        if not _seanses_period_has_rows(conn, date_time_1, date_time_2, client_name):
            return {
                "data": [],
                "total": 0,
                "limit": limit_v,
                "offset": offset_v,
                "has_more": False,
            }
        refresh_seanses_daily_aggregates(conn, start_day=day_from, end_day=day_to)
        agg_count = int(
            conn.execute(
                f"SELECT COUNT(*) FROM seanses_daily_agg WHERE {agg_where}",
                agg_params,
            ).fetchone()[0]
            or 0
        )
        if agg_count == 0:
            return None
    else:
        seans_total = _seans_sessions_total_for_days(
            conn, day_from, day_to, client_name
        )
        agg_total = _daily_agg_sessions_total_for_days(
            conn, day_from, day_to, client_name
        )
        seans_pairs = _seans_network_pairs_for_days(
            conn, day_from, day_to, client_name
        )
        agg_pairs = _daily_agg_network_pairs_for_days(
            conn, day_from, day_to, client_name
        )
        if seans_total > agg_total or seans_pairs > agg_pairs:
            refresh_seanses_daily_aggregates(conn, start_day=day_from, end_day=day_to)

    cur = conn.cursor()
    fz = _sql_freq_zone_expr("frequency")
    cte = f"""
        WITH scoped AS (
            SELECT TRIM(frequency) AS frequency,
                   TRIM(group_) AS group_,
                   sessions_count,
                   {fz} AS freq_zone
            FROM seanses_daily_agg
            WHERE {agg_where}
        ),
        filtered AS (
            SELECT * FROM scoped
            WHERE TRIM(COALESCE(frequency, '')) != ''
              AND TRIM(COALESCE(group_, '')) != ''
        ),
        sessions AS (
            SELECT freq_zone, group_, SUM(sessions_count) AS cnt
            FROM filtered
            GROUP BY freq_zone, group_
        ),
        canon AS (
            SELECT freq_zone, group_, MIN(frequency) AS frequency_display
            FROM filtered
            GROUP BY freq_zone, group_
        ),
        {_doc_stats_page_grouped_sql(join_unit=join_unit)}
    """
    sql_page = (
        cte
        + """
        SELECT freq_zone, frequency_display, group_, cnt, unit_name,
               COUNT(*) OVER() AS total_count
        FROM grouped
        ORDER BY CASE WHEN unit_name != '' THEN 0 ELSE 1 END,
                 frequency_display,
                 group_
        LIMIT ? OFFSET ?
        """
    )
    page_rows = cur.execute(sql_page, (*agg_params, limit_v, offset_v)).fetchall()
    page_keys = [(str(r[0] or ""), str(r[2] or "")) for r in page_rows]
    ids_map = _doc_stats_page_ids_from_daily_agg(
        cur,
        page_keys=page_keys,
        day_from=day_from,
        day_to=day_to,
        client_name=client_name,
        fz=fz,
    )
    return _doc_stats_page_build_result(
        conn,
        page_rows,
        ids_map,
        limit_v=limit_v,
        offset_v=offset_v,
        unit_conn=unit_conn,
    )


def get_doc_stats_page(
    conn: sqlite3.Connection,
    date_time_1: str,
    date_time_2: str,
    client_name: str | None = None,
    *,
    limit: int = 500,
    offset: int = 0,
    unit_conn: sqlite3.Connection | None = None,
    exact_period: bool = False,
) -> dict[str, Any]:
    """
    Страничная версия get_doc_stats(): группирует период в SQL и считает ids_csv
    только для возвращаемой страницы, а не для всех сетей периода.
    """
    from web_portal.lib.db.units import _sql_freq_zone_expr
    limit_v = max(1, min(int(limit or 500), 2000))
    offset_v = max(0, int(offset or 0))
    if not _seanses_period_has_rows(conn, date_time_1, date_time_2, client_name):
        return {
            "data": [],
            "total": 0,
            "limit": limit_v,
            "offset": offset_v,
            "has_more": False,
        }

    # Календарные сутки (00:00–23:59): быстрый путь через seanses_daily_agg.
    # exact_period=1 при полных сутках не должен отключать агрегат — иначе ids_map
    # сканирует весь seanses за много месяцев (минуты зависания на table-data).
    daily_page = _try_get_doc_stats_page_from_daily_agg(
        conn,
        date_time_1,
        date_time_2,
        client_name,
        limit_v=limit_v,
        offset_v=offset_v,
        unit_conn=unit_conn,
    )
    if daily_page is not None:
        return daily_page

    from web_portal.lib.seans_db import connection_path_is_seans_storage

    join_unit = not connection_path_is_seans_storage(conn)
    cur = conn.cursor()
    fz = _sql_freq_zone_expr("frequency")
    source_sql = """
        SELECT date_time, frequency, group_, id, client_name FROM seanses
        UNION ALL
        SELECT date_time, frequency, group_, id, client_name FROM seanses_archive
    """
    if client_name:
        params_base: tuple[Any, ...] = (date_time_1, date_time_2, client_name)
        where = "date_time BETWEEN ? AND ? AND client_name = ?"
    else:
        params_base = (date_time_1, date_time_2)
        where = "date_time BETWEEN ? AND ?"

    cte = f"""
        WITH base AS (
            SELECT TRIM(frequency) AS frequency, TRIM(group_) AS group_,
                   date_time, id, {fz} AS freq_zone
            FROM ({source_sql})
            WHERE {where}
        ),
        filtered AS (
            SELECT * FROM base
            WHERE TRIM(COALESCE(frequency, '')) != ''
              AND TRIM(COALESCE(group_, '')) != ''
        ),
        sessions AS (
            SELECT freq_zone, group_, COUNT(DISTINCT date_time) AS cnt
            FROM filtered
            GROUP BY freq_zone, group_
        ),
        canon AS (
            SELECT freq_zone, group_, MIN(TRIM(frequency)) AS frequency_display
            FROM filtered
            GROUP BY freq_zone, group_
        ),
        {_doc_stats_page_grouped_sql(join_unit=join_unit)}
    """
    sql_page = (
        cte
        + """
        SELECT freq_zone, frequency_display, group_, cnt, unit_name,
               COUNT(*) OVER() AS total_count
        FROM grouped
        ORDER BY CASE WHEN unit_name != '' THEN 0 ELSE 1 END,
                 frequency_display,
                 group_
        LIMIT ? OFFSET ?
        """
    )
    page_rows = cur.execute(sql_page, (*params_base, limit_v, offset_v)).fetchall()
    page_keys = [(str(r[0] or ""), str(r[2] or "")) for r in page_rows]
    ids_map = _doc_stats_page_ids_map(
        cur,
        page_keys=page_keys,
        source_sql=source_sql,
        where=where,
        params_base=params_base,
        fz=fz,
    )
    return _doc_stats_page_build_result(
        conn,
        page_rows,
        ids_map,
        limit_v=limit_v,
        offset_v=offset_v,
        unit_conn=unit_conn,
    )


def dump_selected_rows_for_doc(rows: list[dict[str, Any]]) -> list[tuple]:
    """
    Приводит rows (dict) к формату tuple как ожидает DocumentReport.add_row:
    (frequency, group_, unit_name, count, ids_csv)
    """
    out: list[tuple] = []
    for r in rows:
        out.append(
            (
                str(r.get("frequency", "")),
                str(r.get("group", "")),
                str(r.get("name", "")),
                int(r.get("count", 0) or 0),
                str(r.get("ids_csv", "")),
            )
        )
    return out


__all__ = [
    "get_db_stats_legacy",
    "get_doc_stats_legacy",
    "get_db_stats",
    "format_ids",
    "get_doc_stats",
    "get_doc_stats_page",
    "dump_selected_rows_for_doc",
]
