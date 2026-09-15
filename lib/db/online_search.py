"""Поиск онлайн и unit profiles (физически из ``_impl``)."""
from __future__ import annotations

import re
import sqlite3
from typing import Any

from web_portal.lib.db.connection import (
    _commit_if_needed,
    _conn_has_table,
    _schema_ready_for_conn,
    init_db,
)
from web_portal.lib.db.seans_query import list_distinct_seans_frequency_groups
from web_portal.lib.db.units import (
    _extract_gid_tokens,
    _norm_unit_note,
    _normalize_frequency_key,
    _normalize_group_text,
    load_unit_parent_manual_groups,
    parse_note_unit_parent_child,
)


def _ensure_online_search_unit_profile(conn: sqlite3.Connection) -> None:
    """Idempotent: таблица профилей подразделений (миграция старых search_online.sqlite)."""
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS online_search_unit_profile (
            unit_key TEXT NOT NULL PRIMARY KEY,
            history TEXT NOT NULL DEFAULT '',
            avatar_file TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    try:
        cur.execute(
            "ALTER TABLE online_search_unit_profile ADD COLUMN hero_json TEXT;"
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


def init_online_search(conn: sqlite3.Connection) -> None:
    _ensure_online_search_unit_profile(conn)
    # id(conn) переиспользуется после GC, поэтому дополнительно убеждаемся,
    # что таблица реально существует в этом соединении (см. _conn_has_core_schema).
    if _schema_ready_for_conn(conn) and _conn_has_table(conn, "online_search"):
        return
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS online_search (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            col1 TEXT, col2 TEXT, col3 TEXT, col4 TEXT, col5 TEXT,
            col6 TEXT, col7 TEXT, col8 TEXT, col9 TEXT,
            frequency TEXT,
            group_id TEXT,
            note TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS online_search_meta (
            id INTEGER PRIMARY KEY CHECK (id=1),
            h1 TEXT, h2 TEXT, h3 TEXT, h4 TEXT, h5 TEXT, h6 TEXT, h7 TEXT, h8 TEXT, h9 TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    # миграция meta: какие колонки являются частотой/группой/примечанием в Excel
    try:
        cur.execute("ALTER TABLE online_search_meta ADD COLUMN freq_col INTEGER;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE online_search_meta ADD COLUMN gid_col INTEGER;")
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute("ALTER TABLE online_search_meta ADD COLUMN note_col INTEGER;")
    except sqlite3.OperationalError:
        pass
    cur.execute("INSERT OR IGNORE INTO online_search_meta (id) VALUES (1);")
    cur.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_online_search_q
        ON online_search (frequency, group_id, note);
        """
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_online_search_updated_id ON online_search (updated_at, id);"
    )
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_online_search_group_frequency ON online_search (group_id, frequency);"
    )
    # NULL updated_at ломает инкрементальный sync (строковое сравнение с пустой строкой)
    try:
        cur.execute(
            """
            UPDATE online_search
            SET updated_at = COALESCE(created_at, CURRENT_TIMESTAMP)
            WHERE updated_at IS NULL OR TRIM(COALESCE(updated_at, '')) = ''
            """
        )
    except sqlite3.OperationalError:
        pass
    try:
        cur.execute(
            """
            UPDATE online_search_meta
            SET updated_at = CURRENT_TIMESTAMP
            WHERE updated_at IS NULL OR TRIM(COALESCE(updated_at, '')) = ''
            """
        )
    except sqlite3.OperationalError:
        pass
    conn.commit()


def set_online_search_headers(
    conn: sqlite3.Connection,
    headers: list[str],
    *,
    freq_col: int | None = None,
    gid_col: int | None = None,
    note_col: int | None = None,
) -> None:
    init_online_search(conn)
    hs = [(headers[i] if i < len(headers) else "") for i in range(9)]
    # defaults
    freq_col = int(freq_col or 1)
    gid_col = int(gid_col or 2)
    note_col = int(note_col or 9)
    freq_col = min(max(freq_col, 1), 9)
    gid_col = min(max(gid_col, 1), 9)
    note_col = min(max(note_col, 1), 9)
    conn.execute(
        """
        UPDATE online_search_meta
        SET h1=?,h2=?,h3=?,h4=?,h5=?,h6=?,h7=?,h8=?,h9=?,
            freq_col=?, gid_col=?, note_col=?,
            updated_at=CURRENT_TIMESTAMP
        WHERE id=1
        """,
        (
            *tuple(str(x or "") for x in hs),
            freq_col,
            gid_col,
            note_col,
        ),
    )
    conn.commit()


def get_online_search_headers(conn: sqlite3.Connection) -> list[str]:
    init_online_search(conn)
    r = conn.execute(
        "SELECT h1,h2,h3,h4,h5,h6,h7,h8,h9 FROM online_search_meta WHERE id=1"
    ).fetchone()
    if not r:
        return ["" for _ in range(9)]
    return [str(r[i] or "") for i in range(9)]


def get_online_search_meta(conn: sqlite3.Connection) -> dict[str, int]:
    init_online_search(conn)
    r = conn.execute(
        "SELECT freq_col, gid_col, note_col FROM online_search_meta WHERE id=1"
    ).fetchone()
    if not r:
        return {"freq_col": 1, "gid_col": 2, "note_col": 9}

    def _n(v, default):
        try:
            x = int(v) if v is not None else default
        except Exception:
            x = default
        return min(max(x, 1), 9)

    return {
        "freq_col": _n(r["freq_col"] if "freq_col" in r.keys() else None, 1),
        "gid_col": _n(r["gid_col"] if "gid_col" in r.keys() else None, 2),
        "note_col": _n(r["note_col"] if "note_col" in r.keys() else None, 9),
    }


def get_online_search_meta_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    """
    Полный payload meta для синхронизации (заголовки + настройки колонок + updated_at).
    """
    init_online_search(conn)
    r = conn.execute(
        """
        SELECT
          h1,h2,h3,h4,h5,h6,h7,h8,h9,
          freq_col, gid_col, note_col,
          updated_at
        FROM online_search_meta
        WHERE id=1
        """
    ).fetchone()
    if not r:
        return {
            "headers": ["" for _ in range(9)],
            "freq_col": 1,
            "gid_col": 2,
            "note_col": 9,
            "updated_at": "",
        }
    return {
        "headers": [str(r[f"h{i}"] or "") for i in range(1, 10)],
        "freq_col": int(r["freq_col"] or 1),
        "gid_col": int(r["gid_col"] or 2),
        "note_col": int(r["note_col"] or 9),
        "updated_at": str(r["updated_at"] or ""),
    }


def upsert_online_search_meta_from_sync(
    conn: sqlite3.Connection, *, payload: dict[str, Any]
) -> None:
    """
    Применяем meta с сервера на принимающей стороне.
    Конфликт решаем по updated_at (не затирать более новое локальное).
    """
    init_online_search(conn)
    p = payload or {}
    headers = p.get("headers") or []
    if not isinstance(headers, list):
        headers = []
    hs = [(headers[i] if i < len(headers) else "") for i in range(9)]
    freq_col = int(p.get("freq_col") or 1)
    gid_col = int(p.get("gid_col") or 2)
    note_col = int(p.get("note_col") or 9)
    updated_at = str(p.get("updated_at") or "").strip()
    # локальный updated_at
    r0 = conn.execute("SELECT updated_at FROM online_search_meta WHERE id=1").fetchone()
    local_ts = str(r0["updated_at"] or "").strip() if r0 else ""
    if updated_at and local_ts and local_ts >= updated_at:
        return
    conn.execute(
        """
        UPDATE online_search_meta
        SET h1=?,h2=?,h3=?,h4=?,h5=?,h6=?,h7=?,h8=?,h9=?,
            freq_col=?, gid_col=?, note_col=?,
            updated_at=COALESCE(NULLIF(?,''), CURRENT_TIMESTAMP)
        WHERE id=1
        """,
        (
            *tuple(str(x or "") for x in hs),
            freq_col,
            gid_col,
            note_col,
            updated_at,
        ),
    )
    conn.commit()


def sync_units_from_online_search(
    main_conn: sqlite3.Connection,
    search_online_conn: sqlite3.Connection | None = None,
    frequency_groups: list[tuple[str, str]] | None = None,
) -> dict[str, int]:
    """
    Автоматически применяет записи из online_search в unit.
    Читает из search_online_conn (или main_conn если не указан), записывает в main_conn.
    Если передан frequency_groups, применяет только для указанных пар (frequency, group_).
    Иначе применяет для всех записей (медленно для больших таблиц).
    """
    init_db(main_conn)
    read_conn = search_online_conn if search_online_conn else main_conn
    init_online_search(read_conn)

    # 1) Готовим целевые пары из seanses (или из входного списка)
    if frequency_groups:
        scope_pairs = [
            (str(f or "").strip(), str(g or "").strip())
            for f, g in (frequency_groups or [])
            if str(f or "").strip() and str(g or "").strip()
        ]
    else:
        scope_pairs = list_distinct_seans_frequency_groups(main_conn)
    if not scope_pairs:
        return {"inserted": 0, "updated": 0, "matched_pairs": 0, "total_applied": 0}

    pairs_by_fkey: dict[str, list[tuple[str, str, set[str], str]]] = {}
    for freq, grp in scope_pairs:
        fkey = _normalize_frequency_key(freq)
        if not fkey:
            continue
        grp_tokens = set(_extract_gid_tokens(grp))
        grp_text = _normalize_group_text(grp) if not grp_tokens else ""
        pairs_by_fkey.setdefault(fkey, []).append((freq, grp, grp_tokens, grp_text))
    if not pairs_by_fkey:
        return {"inserted": 0, "updated": 0, "matched_pairs": 0, "total_applied": 0}

    # 2) Загружаем online_search с фильтром по частотным префиксам
    prefixes = sorted(pairs_by_fkey.keys())
    like_params = [f"{p}%" for p in prefixes if p]
    read_cur = read_conn.cursor()
    if like_params:
        where_like = " OR ".join(["frequency LIKE ?"] * len(like_params))
        online_rows = read_cur.execute(
            f"""
            SELECT frequency, group_id, note, COALESCE(updated_at, '')
            FROM online_search
            WHERE frequency IS NOT NULL AND frequency != ''
              AND group_id IS NOT NULL AND group_id != ''
              AND note IS NOT NULL AND note != ''
              AND ({where_like})
            ORDER BY updated_at DESC, id DESC
            """,
            tuple(like_params),
        ).fetchall()
    else:
        online_rows = []

    # 3) Определяем желаемое имя для каждой пары (новые записи имеют приоритет)
    desired_by_pair: dict[tuple[str, str], str] = {}
    matched_pairs = 0
    for row in online_rows:
        freq_os = str(row[0] or "").strip()
        gid_os = str(row[1] or "").strip()
        note_os = str(row[2] or "").strip() or "н/у подразделение ВСУ"
        if not freq_os or not gid_os:
            continue
        fkey = _normalize_frequency_key(freq_os)
        cand_pairs = pairs_by_fkey.get(fkey) or []
        if not cand_pairs:
            continue
        gid_tokens = set(_extract_gid_tokens(gid_os))
        gid_text = _normalize_group_text(gid_os) if not gid_tokens else ""
        for freq_pair, grp_pair, grp_tokens, grp_text in cand_pairs:
            pair_key = (freq_pair, grp_pair)
            if pair_key in desired_by_pair:
                continue
            ok = False
            if gid_tokens and grp_tokens:
                ok = any(t in gid_tokens for t in grp_tokens)
            elif gid_text and grp_text and not gid_tokens and not grp_tokens:
                ok = gid_text == grp_text
            elif gid_os == grp_pair:
                ok = True
            if ok:
                desired_by_pair[pair_key] = note_os
                matched_pairs += 1

    if not desired_by_pair:
        return {"inserted": 0, "updated": 0, "matched_pairs": 0, "total_applied": 0}

    # 4) Читаем текущие unit (с manual-флагом), применяем только нужные изменения
    main_cur = main_conn.cursor()
    existing_rows = main_cur.execute(
        """
        SELECT frequency, group_, name, COALESCE(manual, 0)
        FROM unit
        """
    ).fetchall()
    existing_map: dict[tuple[str, str], tuple[str, int]] = {}
    for f, g, n, m in existing_rows:
        key = (str(f or "").strip(), str(g or "").strip())
        if key not in existing_map:
            existing_map[key] = (str(n or ""), int(m or 0))

    to_replace: list[tuple[str, str, str]] = []
    inserted = 0
    updated = 0
    for pair_key, note_val in desired_by_pair.items():
        curr_name, curr_manual = existing_map.get(pair_key, ("", 0))
        if curr_manual == 1:
            continue
        if curr_name == note_val:
            continue
        if curr_name:
            updated += 1
        else:
            inserted += 1
        to_replace.append((pair_key[0], pair_key[1], note_val))

    if not to_replace:
        return {
            "inserted": 0,
            "updated": 0,
            "matched_pairs": matched_pairs,
            "total_applied": 0,
        }

    main_cur.executemany(
        "DELETE FROM unit WHERE frequency=? AND group_=?",
        [(f, g) for f, g, _name in to_replace],
    )
    main_cur.executemany(
        """
        INSERT INTO unit (frequency, group_, name, manual, updated_at)
        VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)
        """,
        [(f, g, name) for f, g, name in to_replace],
    )
    main_conn.commit()
    total_applied = inserted + updated
    return {
        "inserted": inserted,
        "updated": updated,
        "matched_pairs": matched_pairs,
        "total_applied": total_applied,
    }


def list_online_search(
    conn: sqlite3.Connection,
    q: str | None = None,
    sort_by: str = "frequency",
    sort_dir: str = "desc",
    limit: int = 200,
    offset: int = 0,
    filters: dict[str, str] | None = None,
) -> dict[str, Any]:
    init_db(conn)
    init_online_search(conn)
    q = (q or "").strip()
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    params: list[Any] = []
    conditions = []

    # Основной поиск — по всем релевантным полям строки
    if q:
        like = f"%{q}%"
        ors = [
            "frequency LIKE ?",
            "group_id LIKE ?",
            "note LIKE ?",
            "CAST(id AS TEXT) LIKE ?",
        ] + [f"col{i} LIKE ?" for i in range(1, 10)]
        conditions.append("(" + " OR ".join(ors) + ")")
        params.extend([like] * len(ors))

    # Фильтры по столбцам
    filters = filters or {}
    if filters.get("group_id"):
        conditions.append("group_id = ?")
        params.append(filters["group_id"])

    if filters.get("id"):
        conditions.append("col3 LIKE ?")
        params.append(f"%{filters['id']}%")

    if filters.get("corr"):
        conditions.append("col4 LIKE ?")
        params.append(f"%{filters['corr']}%")

    if filters.get("note"):
        conditions.append("note LIKE ?")
        params.append(f"%{filters['note']}%")

    if filters.get("confirm"):
        conditions.append("col6 LIKE ?")
        params.append(f"%{filters['confirm']}%")

    if filters.get("discovery"):
        conditions.append("col7 LIKE ?")
        params.append(f"%{filters['discovery']}%")

    if filters.get("coords"):
        conditions.append("col8 LIKE ?")
        params.append(f"%{filters['coords']}%")

    if filters.get("updated_at") == "today":
        # Новые данные за последние 24 часа
        from datetime import datetime, timedelta

        yesterday = (datetime.utcnow() - timedelta(hours=24)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conditions.append("updated_at >= ?")
        params.append(yesterday)

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    sort_by = (sort_by or "").strip().lower()
    sort_dir = (sort_dir or "").strip().lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "desc"

    if sort_by == "id":
        order_sql = f"ORDER BY id {sort_dir}"
    else:
        order_sql = (
            "ORDER BY CAST(REPLACE(COALESCE(NULLIF(frequency,''), col1), ',', '.') AS REAL) "
            f"{sort_dir}, id DESC"
        )
    total = conn.execute(
        f"SELECT COUNT(*) FROM online_search {where}", params
    ).fetchone()[0]
    rows = conn.execute(
        f"""
        SELECT id, col1,col2,col3,col4,col5,col6,col7,col8,col9, frequency, group_id, note, created_at, updated_at
        FROM online_search
        {where}
        {order_sql}
        LIMIT ? OFFSET ?
        """,
        [*params, limit, offset],
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": int(r["id"]),
                "col1": r["col1"],
                "col2": r["col2"],
                "col3": r["col3"],
                "col4": r["col4"],
                "col5": r["col5"],
                "col6": r["col6"],
                "col7": r["col7"],
                "col8": r["col8"],
                "col9": r["col9"],
                "frequency": r["frequency"] or "",
                "group_id": r["group_id"] or "",
                "note": r["note"] or "",
                "created_at": r["created_at"] or "",
                "updated_at": r["updated_at"] or "",
            }
        )
    return {"total": int(total or 0), "rows": out, "limit": limit, "offset": offset}


def _row_to_online_search_dict(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(r["id"]),
        "col1": r["col1"],
        "col2": r["col2"],
        "col3": r["col3"],
        "col4": r["col4"],
        "col5": r["col5"],
        "col6": r["col6"],
        "col7": r["col7"],
        "col8": r["col8"],
        "col9": r["col9"],
        "frequency": r["frequency"] or "",
        "group_id": r["group_id"] or "",
        "note": r["note"] or "",
        "created_at": r["created_at"] or "",
        "updated_at": r["updated_at"] or "",
    }


def get_online_search_unit_profile(
    conn: sqlite3.Connection, unit_key: str
) -> dict[str, Any]:
    """unit_key: строка note или '__none__' для пустого подразделения."""
    init_online_search(conn)
    u = (unit_key or "").strip() or "__none__"
    try:
        row = conn.execute(
            "SELECT unit_key, history, avatar_file, hero_json, updated_at FROM online_search_unit_profile WHERE unit_key = ?",
            (u,),
        ).fetchone()
    except sqlite3.OperationalError:
        row = conn.execute(
            "SELECT unit_key, history, avatar_file, updated_at FROM online_search_unit_profile WHERE unit_key = ?",
            (u,),
        ).fetchone()
    if not row:
        return {
            "unit_key": u,
            "history": "",
            "avatar_file": None,
            "hero_json": None,
            "updated_at": "",
        }
    rdict = dict(row)
    hjson = str(rdict.get("hero_json") or "").strip() or None
    return {
        "unit_key": str(row["unit_key"] or u),
        "history": str(row["history"] or ""),
        "avatar_file": str(row["avatar_file"] or "") or None,
        "hero_json": hjson,
        "updated_at": str(row["updated_at"] or ""),
    }


def upsert_online_search_unit_profile(
    conn: sqlite3.Connection, unit_key: str, history: str, hero_json: str | None
) -> None:
    """Полная запись history + hero_json (NULL = без кастомной шапки)."""
    init_online_search(conn)
    u = (unit_key or "").strip() or "__none__"
    hj = (hero_json.strip() or None) if isinstance(hero_json, str) else hero_json
    conn.execute(
        """
        INSERT INTO online_search_unit_profile (unit_key, history, hero_json, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(unit_key) DO UPDATE SET
          history=excluded.history,
          hero_json=excluded.hero_json,
          updated_at=CURRENT_TIMESTAMP
        """,
        (u, str(history or ""), hj),
    )
    conn.commit()


def set_online_search_unit_profile(
    conn: sqlite3.Connection,
    unit_key: str,
    *,
    history: str | None = None,
    hero_json: str | None = None,
) -> None:
    init_online_search(conn)
    u = (unit_key or "").strip() or "__none__"
    ex = get_online_search_unit_profile(conn, u)
    new_h = str(history) if history is not None else str(ex.get("history") or "")
    if hero_json is not None:
        hj = (str(hero_json).strip() or None) if str(hero_json).strip() else None
    else:
        hj = ex.get("hero_json")
    upsert_online_search_unit_profile(conn, u, new_h, hj)


def set_online_search_unit_avatar(
    conn: sqlite3.Connection, unit_key: str, avatar_file: str | None
) -> None:
    init_online_search(conn)
    u = (unit_key or "").strip() or "__none__"
    conn.execute(
        """
        INSERT INTO online_search_unit_profile (unit_key, avatar_file, updated_at)
        VALUES (?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(unit_key) DO UPDATE SET
          avatar_file=excluded.avatar_file,
          updated_at=CURRENT_TIMESTAMP
        """,
        (u, avatar_file or ""),
    )
    conn.commit()


def list_online_search_rows_by_unit_key(
    conn: sqlite3.Connection, unit_key: str, *, max_rows: int = 10000
) -> list[dict[str, Any]]:
    """Все строки online_search для подразделения (note), без пагинации отображения."""
    init_db(conn)
    init_online_search(conn)
    max_rows = max(1, min(int(max_rows), 50000))
    u = (unit_key or "").strip()
    if u == "__none__" or u == "":
        rows = conn.execute(
            f"""
            SELECT id, col1,col2,col3,col4,col5,col6,col7,col8,col9,
                   frequency, group_id, note, created_at, updated_at
            FROM online_search
            WHERE note IS NULL OR TRIM(COALESCE(note, '')) = ''
            ORDER BY CAST(REPLACE(COALESCE(NULLIF(frequency,''), col1), ',', '.') AS REAL) DESC, id DESC
            LIMIT {max_rows}
            """
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT id, col1,col2,col3,col4,col5,col6,col7,col8,col9,
                   frequency, group_id, note, created_at, updated_at
            FROM online_search
            WHERE note = ?
            ORDER BY CAST(REPLACE(COALESCE(NULLIF(frequency,''), col1), ',', '.') AS REAL) DESC, id DESC
            LIMIT {max_rows}
            """,
            (u,),
        ).fetchall()
    return [_row_to_online_search_dict(r) for r in (rows or [])]


def count_online_search_by_unit_key(conn: sqlite3.Connection, unit_key: str) -> int:
    init_db(conn)
    init_online_search(conn)
    u = (unit_key or "").strip()
    if u == "__none__" or u == "":
        c = conn.execute(
            "SELECT COUNT(*) AS c FROM online_search WHERE note IS NULL OR TRIM(COALESCE(note, '')) = ''"
        ).fetchone()
    else:
        c = conn.execute(
            "SELECT COUNT(*) AS c FROM online_search WHERE note = ?", (u,)
        ).fetchone()
    return int(c["c"] or 0) if c else 0


def _parent_merge_key(parent_or_full: str) -> str:
    return _norm_unit_note(parent_or_full).casefold()


def _child_label_sort(t: str) -> tuple[int, int, str]:
    """Сортировка плиток: «1 шб», «2 шб», …; «Записи» — в конце."""
    t = (t or "").strip()
    tl = t.lower()
    if tl in ("записи", "без подразделения"):
        return (2, 10**9, tl)
    m = re.match(r"^(\d+)", t)
    n = int(m.group(1)) if m else 10**9
    return (0 if m else 1, n, tl)


def merge_families_by_manual_groups(
    families: list[dict[str, Any]], groups: list[list[str]] | None
) -> list[dict[str, Any]]:
    """Объединяет только подразделения, явно добавленные в ручную группу."""
    if not groups:
        return families
    mkey_to_fam: dict[str, dict[str, Any]] = {}
    # Значения в файле ручных групп проходят _norm_unit_note при сохранении,
    # а исходные note в БД могут отличаться лишними пробелами или регистром.
    # Сопоставляем по одной и той же нормализованной форме, но в словаре
    # храним исходный ключ: он нужен для корректного исключения карточки.
    raw_keys_by_match_key: dict[str, set[str]] = {}
    for f in families:
        k = str(f.get("parent_key") or "").strip()
        if k:
            mkey_to_fam[k] = f
            match_key = _norm_unit_note(k).casefold()
            if match_key:
                raw_keys_by_match_key.setdefault(match_key, set()).add(k)

    for g in groups:
        canon = g[0].strip()
        if not canon or canon == "__none__":
            continue
        if len(g) < 2:
            continue
        # Первая строка — название группы, остальные — выбранные пользователем
        # точные названия подразделений. Никакой эвристики по частям названия.
        canon_mkey = f"__manual_group__:{canon}"
        mkeys: set[str] = {str(x).strip() for x in g[1:] if str(x).strip()}
        # Совместимость со старым файлом: если название группы одновременно было
        # названием подразделения, включаем его в группу.
        if _norm_unit_note(canon).casefold() in raw_keys_by_match_key:
            mkeys.add(canon)
        to_merge: list[dict[str, Any]] = []
        for mk in mkeys:
            match_key = _norm_unit_note(mk).casefold()
            for raw_key in raw_keys_by_match_key.get(match_key, set()):
                f = mkey_to_fam.pop(raw_key, None)
                if f:
                    to_merge.append(f)
        if not to_merge:
            continue
        by_uk: dict[str, dict[str, Any]] = {}
        for f in to_merge:
            for ch in f.get("children") or []:
                uk = str(ch.get("unit_key") or "")
                if not uk:
                    continue
                n = int(ch.get("row_count") or 0)
                if uk in by_uk:
                    by_uk[uk]["row_count"] = int(by_uk[uk].get("row_count") or 0) + n
                else:
                    by_uk[uk] = {
                        "unit_key": uk,
                        "label": (
                            ch.get("label")
                            if ch.get("label") and ch.get("label") != "Записи"
                            else (f.get("parent_label") or uk)
                        ),
                        "row_count": n,
                    }
        all_ch = list(by_uk.values())
        all_ch.sort(
            key=lambda c: _child_label_sort(
                str(c.get("label") or ""),
            )
        )
        new_f: dict[str, Any] = {
            "parent_key": canon_mkey,
            "parent_label": _norm_unit_note(canon),
            "row_count": sum(int(c.get("row_count") or 0) for c in all_ch),
            "children": all_ch,
        }
        mkey_to_fam[canon_mkey] = new_f

    out = list(mkey_to_fam.values())
    out.sort(
        key=lambda x: (
            str(x.get("parent_key") or "") == "__none__",
            (x.get("parent_label") or "").lower(),
        )
    )
    return out


def list_online_search_unit_families(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Каждое точное название из ``note`` — отдельное подразделение. Совпадающие
    названия уже объединяются SQL-группировкой; любые более крупные объединения
    возможны только через ручные группы.
    """
    init_db(conn)
    init_online_search(conn)
    flat = list_distinct_online_search_units(conn)
    out: list[dict[str, Any]] = []
    for row in flat:
        uk = str(row.get("unit_key") or "__none__")
        cnt = int(row.get("row_count") or 0)
        if uk == "__none__":
            label = "Без подразделения"
        else:
            label = uk
        out.append(
            {
                "parent_key": uk,
                "parent_label": label,
                "row_count": cnt,
                "children": [
                    {
                        "unit_key": uk,
                        "label": label if uk != "__none__" else "Без подразделения",
                        "row_count": cnt,
                    }
                ],
            }
        )
    out.sort(
        key=lambda x: (
            str(x.get("parent_key") or "") == "__none__",
            (x.get("parent_label") or "").lower(),
        )
    )
    return merge_families_by_manual_groups(out, load_unit_parent_manual_groups())


def list_online_search_unit_avatar_files(
    conn: sqlite3.Connection, unit_keys: list[str]
) -> dict[str, str]:
    """unit_key (полный note) -> имя файла аватара, только непустые."""
    init_db(conn)
    init_online_search(conn)
    raw = [str(k).strip() for k in (unit_keys or []) if k and str(k).strip() and str(k).strip() != "__none__"]
    if not raw:
        return {}
    out: dict[str, str] = {}
    # убираем дубли, сохраняем порядок
    seen: set[str] = set()
    keys: list[str] = []
    for k in raw:
        if k not in seen:
            seen.add(k)
            keys.append(k)
    chunk = 200
    for i in range(0, len(keys), chunk):
        part = keys[i : i + chunk]
        ph = ",".join("?" * len(part))
        rows = conn.execute(
            f"""
            SELECT unit_key, avatar_file
            FROM online_search_unit_profile
            WHERE unit_key IN ({ph})
              AND TRIM(COALESCE(avatar_file, '')) != ''
            """,
            part,
        ).fetchall()
        for r in rows or []:
            u = str(r["unit_key"] or "").strip()
            fn = str(r["avatar_file"] or "").strip()
            if u and fn:
                out[u] = fn
    return out


def list_archive_freq_by_note(
    search_conn: sqlite3.Connection, unit_key: str
) -> list[dict[str, Any]]:
    """
    Архив из online_search: пары (freq, group) с min/max дат.
    """
    init_online_search(search_conn)
    uk = (unit_key or "").strip()
    if not uk or uk == "__none__":
        return []
    try:
        rows = search_conn.execute(
            """
            SELECT
              TRIM(COALESCE(NULLIF(frequency, ''), col1, '')) AS f,
              TRIM(COALESCE(NULLIF(group_id, ''), col2, '')) AS g,
              COUNT(*) AS n,
              MIN(COALESCE(NULLIF(updated_at, ''), created_at, '')) AS tmin,
              MAX(COALESCE(NULLIF(updated_at, ''), created_at, '')) AS tmax
            FROM online_search
            WHERE note = ?
            GROUP BY
              TRIM(COALESCE(NULLIF(frequency, ''), col1, '')),
              TRIM(COALESCE(NULLIF(group_id, ''), col2, ''))
            HAVING TRIM(COALESCE(NULLIF(frequency, ''), col1, '')) != ''
               AND TRIM(COALESCE(NULLIF(group_id, ''), col2, '')) != ''
            """,
            (uk,),
        ).fetchall()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for r in rows or []:
        out.append(
            {
                "frequency": str(r["f"] or ""),
                "group": str(r["g"] or ""),
                "row_count": int(r["n"] or 0),
                "first_seen": str(r["tmin"] or "") or None,
                "last_seen": str(r["tmax"] or "") or None,
            }
        )
    out.sort(
        key=lambda x: (str(x.get("frequency") or "").lower(), str(x.get("group") or "").lower())
    )
    return out


def list_online_search_ids_for_note_pair(
    search_conn: sqlite3.Connection, unit_key: str, frequency: str, group_id: str
) -> list[str]:
    init_online_search(search_conn)
    uk = (unit_key or "").strip()
    f = (frequency or "").strip()
    g = (group_id or "").strip()
    if not uk or uk == "__none__" or not f or not g:
        return []
    try:
        rows = search_conn.execute(
            """
            SELECT DISTINCT TRIM(COALESCE(col3, '')) AS cid
            FROM online_search
            WHERE note = ?
              AND TRIM(COALESCE(NULLIF(frequency, ''), col1, '')) = ?
              AND TRIM(COALESCE(NULLIF(group_id, ''), col2, '')) = ?
            """,
            (uk, f, g),
        ).fetchall()
    except Exception:
        return []
    return sorted(
        {str(r["cid"] or "") for r in (rows or []) if r and str(r["cid"] or "").strip()}
    )


def list_distinct_online_search_units(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Все подразделения (distinct note) с числом строк — лёгкий список для боковой панели.
    """
    init_db(conn)
    init_online_search(conn)
    rows = conn.execute(
        """
        SELECT
          CASE
            WHEN note IS NULL OR TRIM(COALESCE(note, '')) = '' THEN '__none__'
            ELSE note
          END AS ukey,
          COUNT(*) AS cnt
        FROM online_search
        GROUP BY
          CASE
            WHEN note IS NULL OR TRIM(COALESCE(note, '')) = '' THEN '__none__'
            ELSE note
          END
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if isinstance(r, (tuple, list)):
            uk = str(r[0] or '__none__')
            cnt = int(r[1] or 0)
        else:
            uk = str(r['ukey'] or '__none__')
            cnt = int(r['cnt'] or 0)
        out.append({'unit_key': uk, 'row_count': cnt})
    out.sort(
        key=lambda x: (
            x['unit_key'] == '__none__',
            (x['unit_key'] if x['unit_key'] != '__none__' else '').lower(),
        )
    )
    return out


def upsert_online_search_row(conn: sqlite3.Connection, row: dict[str, Any]) -> int:
    init_db(conn)
    init_online_search(conn)
    meta = get_online_search_meta(conn)
    rid = int(row.get("id") or 0)
    cols = [row.get(f"col{i}") for i in range(1, 10)]
    # freq/gid/note могут быть в разных колонках xlsx
    freq_idx = int(meta.get("freq_col", 1)) - 1
    gid_idx = int(meta.get("gid_col", 2)) - 1
    note_idx = int(meta.get("note_col", 9)) - 1
    frequency = str(
        row.get("frequency") or (cols[freq_idx] if freq_idx < len(cols) else "") or ""
    ).strip()
    group_id = str(
        row.get("group_id") or (cols[gid_idx] if gid_idx < len(cols) else "") or ""
    ).strip()
    note = str(
        row.get("note") or (cols[note_idx] if note_idx < len(cols) else "") or ""
    ).strip()

    # авто-отражение в соответствующие колонки xlsx
    if 0 <= freq_idx < 9 and cols[freq_idx] is None:
        cols[freq_idx] = frequency
    if 0 <= gid_idx < 9 and cols[gid_idx] is None:
        cols[gid_idx] = group_id
    if 0 <= note_idx < 9 and cols[note_idx] is None:
        cols[note_idx] = note

    if rid > 0:
        conn.execute(
            """
            UPDATE online_search SET
              col1=?,col2=?,col3=?,col4=?,col5=?,col6=?,col7=?,col8=?,col9=?,
              frequency=?, group_id=?, note=?,
              updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                *[c if c is None else str(c) for c in cols],
                frequency,
                group_id,
                note,
                rid,
            ),
        )
        conn.commit()
        return rid

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO online_search
          (col1,col2,col3,col4,col5,col6,col7,col8,col9, frequency, group_id, note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (*[c if c is None else str(c) for c in cols], frequency, group_id, note),
    )
    conn.commit()
    return int(cur.lastrowid)


def update_online_search_note(
    conn: sqlite3.Connection, row_id: int, note: str
) -> dict[str, Any]:
    """
    Обновляет примечание (note) БЕЗ синхронизации в col* колонки.
    (Важно: чтобы редактирование примечания не могло затирать, например, координаты из-за неверного note_col.)
    Возвращает {"id":..., "frequency":..., "group_id":..., "note":...}
    """
    init_db(conn)
    init_online_search(conn)
    note = str(note or "").strip()
    conn.execute(
        """
        UPDATE online_search
        SET note=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """,
        (note, int(row_id)),
    )
    conn.commit()
    r = conn.execute(
        "SELECT id, frequency, group_id, note FROM online_search WHERE id=?",
        (int(row_id),),
    ).fetchone()
    if not r:
        return {"id": int(row_id), "frequency": "", "group_id": "", "note": note}
    return {
        "id": int(r["id"]),
        "frequency": r["frequency"] or "",
        "group_id": r["group_id"] or "",
        "note": r["note"] or "",
    }


def delete_online_search_row(conn: sqlite3.Connection, row_id: int) -> None:
    init_db(conn)
    init_online_search(conn)
    conn.execute("DELETE FROM online_search WHERE id=?", (int(row_id),))
    conn.commit()


def list_online_search_rows_after(
    conn: sqlite3.Connection,
    *,
    after_updated_at: str,
    after_id: int,
    limit: int = 500,
    initialize: bool = True,
) -> list[dict[str, Any]]:
    """
    Инкрементальная выборка для синхронизации: идём по (updated_at, id).
    """
    if initialize:
        init_db(conn)
        init_online_search(conn)
    limit = max(1, min(int(limit), 2000))
    ts = str(after_updated_at or "").strip() or "1970-01-01 00:00:00"
    aid = int(after_id or 0)
    rows = conn.execute(
        """
        SELECT
          id, col1,col2,col3,col4,col5,col6,col7,col8,col9,
          frequency, group_id, note,
          created_at, updated_at
        FROM online_search
        WHERE
          (COALESCE(updated_at,'') > ?)
          OR (COALESCE(updated_at,'') = ? AND id > ?)
        ORDER BY COALESCE(updated_at,'') ASC, id ASC
        LIMIT ?
        """,
        (ts, ts, aid, limit),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        out.append(
            {
                "id": int(r["id"]),
                **{
                    f"col{i}": (r[f"col{i}"] if f"col{i}" in r.keys() else None)
                    for i in range(1, 10)
                },
                "frequency": str(r["frequency"] or ""),
                "group_id": str(r["group_id"] or ""),
                "note": str(r["note"] or ""),
                "created_at": str(r["created_at"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
        )
    return out


def upsert_online_search_rows_from_sync(
    conn: sqlite3.Connection, *, rows: list[dict[str, Any]]
) -> dict[str, int]:
    """
    Применение батча online_search на принимающей стороне (сервер).
    Пишем с сохранением id/created_at/updated_at.
    """
    init_db(conn)
    init_online_search(conn)
    if not rows:
        return {"applied": 0}
    params = []
    for r in rows or []:
        rid = int(r.get("id") or 0)
        if not rid:
            continue
        cols = [r.get(f"col{i}") for i in range(1, 10)]
        params.append(
            (
                rid,
                *[("" if c is None else str(c)) for c in cols],
                str(r.get("frequency") or ""),
                str(r.get("group_id") or ""),
                str(r.get("note") or ""),
                str(r.get("created_at") or "") or None,
                str(r.get("updated_at") or "") or None,
            )
        )
    if not params:
        return {"applied": 0}
    conn.executemany(
        """
        INSERT INTO online_search
          (id, col1,col2,col3,col4,col5,col6,col7,col8,col9,
           frequency, group_id, note, created_at, updated_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET
          col1=excluded.col1, col2=excluded.col2, col3=excluded.col3, col4=excluded.col4, col5=excluded.col5,
          col6=excluded.col6, col7=excluded.col7, col8=excluded.col8, col9=excluded.col9,
          frequency=excluded.frequency, group_id=excluded.group_id, note=excluded.note,
          created_at=COALESCE(NULLIF(excluded.created_at,''), online_search.created_at),
          updated_at=COALESCE(NULLIF(excluded.updated_at,''), online_search.updated_at)
        """,
        params,
    )
    _commit_if_needed(conn)
    return {"applied": len(params)}


__all__ = [
    "init_online_search",
    "set_online_search_headers",
    "get_online_search_headers",
    "get_online_search_meta",
    "get_online_search_meta_payload",
    "upsert_online_search_meta_from_sync",
    "sync_units_from_online_search",
    "list_online_search",
    "get_online_search_unit_profile",
    "upsert_online_search_unit_profile",
    "set_online_search_unit_profile",
    "set_online_search_unit_avatar",
    "list_online_search_rows_by_unit_key",
    "count_online_search_by_unit_key",
    "list_online_search_unit_families",
    "list_online_search_unit_avatar_files",
    "list_online_search_ids_for_note_pair",
    "list_distinct_online_search_units",
    "upsert_online_search_row",
    "update_online_search_note",
    "delete_online_search_row",
    "list_online_search_rows_after",
    "upsert_online_search_rows_from_sync",
    "merge_families_by_manual_groups",
    "list_archive_freq_by_note",
]
