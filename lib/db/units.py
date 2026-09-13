"""Подразделения, избранное, частоты (физически из ``_impl``)."""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

from web_portal.lib.db.connection import init_db

# --- Иерархия подразделений в online_search (note): «425 ошп "Скала"» + «1 шб», «2 шб» и т.п. ---

_OSN_CHILD_SUFFIX: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"[\s,;|/\\–\-\(\)]+(?P<child>\d+\s*ш[б6b8])\s*$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"[\s,;|/\\–\-\(\)]+(?P<child>\d+\s*мс[б6b8])\s*$",
        re.IGNORECASE | re.UNICODE,
    ),
)

# Префикс батальона/взвода в начале: «1 шб 425 ошп …» (часто), а не только «… 1 шб» в конце
_OSN_CHILD_PREFIX: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"^(?P<child>\d+\s*ш[б6b8])\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"^(?P<child>\d+\s*мс[б6b8])\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"^(?P<child>взвод\s+связи)\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"^(?P<child>тр)\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    # «1 бат 12 обр…», «1 ббпс 9 ошбр…», «1 бмп 35…», «1 бон 14…» — короткое соединение + родитель
    re.compile(
        r"^(?P<child>\d+\s*бат)\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"^(?P<child>\d+\s*ббп[сcс])\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"^(?P<child>\d+\s*бмп)\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"^(?P<child>\d+\s*бон)\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"^(?P<child>\d+\s*дш[б6b8мm]?)\s+(?P<parent>.+)$",
        re.IGNORECASE | re.UNICODE,
    ),
)

_OSN_CHILD_SUFFIX_EXTRA: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"[\s,;|/\\–\-\(\)]+(?P<child>\d+\s*бат)\s*$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"[\s,;|/\\–\-\(\)]+(?P<child>\d+\s*ббп[сc])\s*$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"[\s,;|/\\–\-\(\)]+(?P<child>\d+\s*бмп)\s*$",
        re.IGNORECASE | re.UNICODE,
    ),
    re.compile(
        r"[\s,;|/\\–\-\(\)]+(?P<child>\d+\s*бон)\s*$",
        re.IGNORECASE | re.UNICODE,
    ),
)

_OSN_CHILD_SUFFIX = _OSN_CHILD_SUFFIX + _OSN_CHILD_SUFFIX_EXTRA

_OSN_BANNED_ABBR = frozenset(
    {
        "год",
        "сут",
        "час",
        "мин",
        "сек",
        "мес",
        "ден",
        "янв",
        "фев",
        "мар",
        "апр",
        "мая",
        "июн",
        "июл",
        "авг",
        "сен",
        "окт",
        "ноя",
        "дек",
    }
)



def _normalize_frequency_key(freq: str) -> str:
    """
    Совместимость с desktop update_units_from_search:
    берём первые 3 цифры до точки.
    """
    s = str(freq or "").strip().replace(",", ".")
    if not s:
        return ""
    # берём только leading digits до точки
    import re

    m = re.match(r"^\s*(\d{1,10})(?:\.\d+)?\s*$", s)
    if not m:
        # fallback: ищем в строке
        m2 = re.search(r"(\d{1,10})\.", s)
        if not m2:
            m3 = re.search(r"(\d{3})", s)
            return m3.group(1) if m3 else ""
        return m2.group(1)[:3]
    return m.group(1)[:3]


def _extract_gid_tokens(s: str) -> list[str]:
    import re

    return [t for t in re.findall(r"\d+", str(s or "")) if t]


def _normalize_group_text(s: str) -> str:
    import re

    t = str(s or "").upper()
    t = t.replace("Т", "T")
    t = re.sub(r"[^A-Z0-9]+", "", t)
    return t


def _sql_freq_zone_expr(column: str = "frequency") -> str:
    """
    Выражение SQLite: «зона» частоты = целая часть МГц (151.0000, 151.0020 → одна зона «151»).
    Так в таблице сеансов не плодятся строки из-за разного формата записи одной сети.
    """
    col = column.strip() or "frequency"
    return (
        f"CASE WHEN TRIM(COALESCE({col}, '')) = '' THEN '' "
        f"ELSE printf('%d', CAST(REPLACE(TRIM({col}), ',', '.') AS REAL)) END"
    )


def freq_zone_for_sessions_merge(freq: str) -> str:
    """
    Python-аналог зоны частоты (целые МГц) — для сопоставления с избранным сеансов
    после слияния строк в get_doc_stats.
    """
    s = str(freq or "").strip().replace(",", ".")
    if not s:
        return ""
    try:
        return str(int(float(s)))
    except (ValueError, TypeError, OverflowError):
        return ""


def sessions_favorite_matches_row(
    row_frequency: str, row_group: str, fav: dict[str, Any]
) -> bool:
    """Совпадение строки таблицы сеансов с записью избранного с учётом зоны частоты."""
    ff = str(fav.get("frequency") or "").strip()
    fg = str(fav.get("group") or "").strip()
    if ff == "__unit__":
        return False
    if str(row_group or "").strip() != fg:
        return False
    zr = freq_zone_for_sessions_merge(row_frequency)
    zf = freq_zone_for_sessions_merge(ff)
    if zr and zf:
        return zr == zf
    return str(row_frequency or "").strip() == str(ff or "").strip()


def build_sessions_favorite_match_set(
    favorites: list[dict[str, Any]] | None,
) -> set[tuple[str, str]]:
    """O(1)-ключи избранного для разметки строк таблицы сеансов."""
    out: set[tuple[str, str]] = set()
    for fav in favorites or []:
        ff = str(fav.get("frequency") or "").strip()
        if not ff or ff == "__unit__":
            continue
        fg = str(fav.get("group") or "").strip()
        zf = freq_zone_for_sessions_merge(ff)
        out.add((zf or ff, fg))
    return out


def sessions_row_is_favorite(
    row_frequency: str,
    row_group: str,
    favorite_keys: set[tuple[str, str]],
) -> bool:
    if not favorite_keys:
        return False
    zr = freq_zone_for_sessions_merge(row_frequency)
    key = (zr or str(row_frequency or "").strip(), str(row_group or "").strip())
    return key in favorite_keys


def apply_search_note_to_unit(
    conn: sqlite3.Connection, frequency: str, group_id: str, note: str
) -> dict[str, int]:
    """
    Применяет одно значение (frequency, group_id, note) к unit, аналогично логике update_units_from_search.
    Возвращает {'inserted': X, 'updated': Y, 'matched_pairs': Z}.
    """
    init_db(conn)
    fkey = _normalize_frequency_key(frequency)
    gid_raw = str(group_id or "").strip()
    note_val = (note or "").strip() or "н/у подразделение ВСУ"
    if not fkey or not gid_raw:
        return {"inserted": 0, "updated": 0, "matched_pairs": 0}

    gid_tokens = _extract_gid_tokens(gid_raw)
    gid_text = _normalize_group_text(gid_raw) if not gid_tokens else ""

    cur = conn.cursor()
    like_prefix = f"{fkey}%"
    # Текущее состояние unit только для релевантного диапазона частот.
    existing_rows = cur.execute(
        """
        SELECT frequency, group_, name, COALESCE(manual, 0)
        FROM unit
        WHERE frequency LIKE ? OR CAST(frequency AS REAL)=CAST(? AS REAL)
        """,
        (like_prefix, fkey),
    ).fetchall()
    existing_map: dict[tuple[str, str], tuple[str, int]] = {}
    for f, g, n, m in existing_rows:
        key = (str(f), str(g))
        if key not in existing_map:
            existing_map[key] = (str(n or ""), int(m or 0))

    pairs = list_distinct_seans_frequency_groups(
        conn,
        frequency_like=like_prefix,
        frequency_exact=fkey,
    )
    to_update: list[tuple[str, str, str]] = []
    to_insert: list[tuple[str, str, str]] = []
    matched = 0

    for f, g in pairs:
        if _normalize_frequency_key(f) != fkey:
            continue

        ok = False
        toks = _extract_gid_tokens(g)
        if gid_tokens and toks:
            ok = any(t in gid_tokens for t in toks)
        elif gid_text and not toks:
            ok = _normalize_group_text(g) == gid_text
        if not ok:
            continue

        matched += 1
        key = (f, g)
        curr_name, curr_manual = existing_map.get(key, ("", 0))

        # Если имя помечено как ручное — не перезатираем синком из online_search
        if curr_manual == 1:
            continue

        if not curr_name:
            to_insert.append((f, g, note_val))
            existing_map[key] = (note_val, 0)
        elif curr_name != note_val:
            to_update.append((note_val, f, g))
            existing_map[key] = (note_val, 0)

    # Применяем
    if to_update:
        cur.executemany(
            "DELETE FROM unit WHERE frequency=? AND group_=?",
            [(f, g) for _new_name, f, g in to_update],
        )
        cur.executemany(
            "INSERT INTO unit (frequency, group_, name, manual, updated_at) VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)",
            [(f, g, new_name) for new_name, f, g in to_update],
        )
    if to_insert:
        cur.executemany(
            "DELETE FROM unit WHERE frequency=? AND group_=?",
            [(f, g) for f, g, _new_name in to_insert],
        )
        cur.executemany(
            "INSERT INTO unit (frequency, group_, name, manual, updated_at) VALUES (?, ?, ?, 0, CURRENT_TIMESTAMP)",
            [(f, g, new_name) for f, g, new_name in to_insert],
        )
    conn.commit()
    return {
        "inserted": len(to_insert),
        "updated": len(to_update),
        "matched_pairs": matched,
    }


def update_unit_name(
    conn: sqlite3.Connection, frequency: str, group_: str, name: str
) -> dict[str, int]:
    """
    Прямое обновление названия подразделения для конкретной пары (frequency, group_).
    Возвращает {'updated': 1} если обновлено, {'inserted': 1} если вставлено.
    """
    init_db(conn)
    frequency = str(frequency or "").strip()
    group_ = str(group_ or "").strip()
    name = str(name or "").strip()

    if not frequency or not group_:
        return {"updated": 0, "inserted": 0}

    cur = conn.cursor()
    # Держим ровно 1 строку на пару (frequency, group_) и помечаем как manual=1,
    # чтобы синк из online_search не перезаписывал ручные названия.
    existing = cur.execute(
        "SELECT 1 FROM unit WHERE frequency=? AND group_=? LIMIT 1",
        (frequency, group_),
    ).fetchone()
    cur.execute("DELETE FROM unit WHERE frequency=? AND group_=?", (frequency, group_))
    cur.execute(
        "INSERT INTO unit (frequency, group_, name, manual, updated_at) VALUES (?, ?, ?, 1, CURRENT_TIMESTAMP)",
        (frequency, group_, name),
    )
    conn.commit()
    return {"updated": 1 if existing else 0, "inserted": 0 if existing else 1}


def _unit_map_legacy(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    from web_portal.lib.db.sql_util import _pick_first, _table_columns
    if not _table_exists(conn, "unit"):
        return {}
    cols = _table_columns(conn, "unit")
    freq_c = _pick_first(cols, ["frequency", "freq", "f"])
    grp_c = _pick_first(cols, ["group_", "group", "grp", "g"])
    name_c = _pick_first(cols, ["name", "unit", "unit_name"])
    if not (freq_c and grp_c and name_c):
        return {}
    try:
        rows = conn.execute(
            f"SELECT {freq_c} as frequency, {grp_c} as group_, {name_c} as name FROM unit;"
        ).fetchall()
    except Exception:
        return {}
    m: dict[tuple[str, str], str] = {}
    for r in rows or []:
        freq = r[0] if isinstance(r, (tuple, list)) else r["frequency"]
        group = r[1] if isinstance(r, (tuple, list)) else r["group_"]
        name = r[2] if isinstance(r, (tuple, list)) else r["name"]
        m[(str(freq or "*"), str(group or "*"))] = str(name or "")
    return m


def _unit_row_score(manual: object, updated_at: object) -> tuple[int, str]:
    return (int(manual or 0), str(updated_at or ""))


def _build_unit_name_map_for_pairs(
    conn: sqlite3.Connection, pairs: list[tuple[str, str]]
) -> dict[tuple[str, str], str]:
    """
    Пакетное разрешение имён unit для списка пар (frequency, group_).
    Логика совпадает с `_get_unit_name_for_pair`.
    """
    init_db(conn)
    wanted: list[tuple[str, str]] = []
    groups: set[str] = set()
    for freq_raw, grp_raw in pairs or []:
        freq = str(freq_raw or "").strip()
        grp = str(grp_raw or "").strip()
        if not freq or not grp:
            continue
        wanted.append((freq, grp))
        groups.add(grp)
    if not wanted or not groups:
        return {}

    rows = []
    group_list = sorted(groups)
    for i in range(0, len(group_list), 400):
        chunk = group_list[i : i + 400]
        placeholders = ",".join("?" * len(chunk))
        rows.extend(
            conn.execute(
                f"""
                SELECT frequency, group_, name, COALESCE(manual, 0) AS manual,
                       COALESCE(updated_at, '') AS updated_at
                FROM unit
                WHERE group_ IN ({placeholders})
                """,
                tuple(chunk),
            ).fetchall()
        )

    exact_best: dict[tuple[str, str], tuple[tuple[int, str], str]] = {}
    norm_best: dict[tuple[str, str], tuple[tuple[int, str], str]] = {}
    for row in rows or []:
        freq = str(row["frequency"] or "").strip()
        grp = str(row["group_"] or "").strip()
        name = str(row["name"] or "").strip()
        if not freq or not grp or not name:
            continue
        sc = _unit_row_score(row["manual"], row["updated_at"])
        ek = (freq, grp)
        if ek not in exact_best or sc > exact_best[ek][0]:
            exact_best[ek] = (sc, name)
        nk = (_normalize_frequency_key(freq), grp)
        if nk[0] and (nk not in norm_best or sc > norm_best[nk][0]):
            norm_best[nk] = (sc, name)

    out: dict[tuple[str, str], str] = {}
    for freq, grp in wanted:
        if (freq, grp) in exact_best:
            out[(freq, grp)] = exact_best[(freq, grp)][1]
            continue
        nk = (_normalize_frequency_key(freq), grp)
        out[(freq, grp)] = norm_best[nk][1] if nk in norm_best else ""
    return out


def _get_unit_name_for_pair(
    conn: sqlite3.Connection, frequency: str, group_: str
) -> str:
    """
    Возвращает "лучшее" имя подразделения для пары (frequency, group_).
    Приоритет: manual=1, затем updated_at.
    """
    init_db(conn)
    freq = str(frequency or "").strip()
    grp = str(group_ or "").strip()
    if not freq or not grp:
        return ""
    freq_norm = _normalize_frequency_key(freq)
    try:
        r = conn.execute(
            """
            SELECT name
            FROM unit
            WHERE frequency=? AND group_=?
            ORDER BY COALESCE(manual, 0) DESC, COALESCE(updated_at, '') DESC
            LIMIT 1
            """,
            (freq, grp),
        ).fetchone()
        if r:
            return str(r["name"] or "")
        if freq_norm:
            rows = conn.execute(
                """
                SELECT frequency, name
                FROM unit
                WHERE group_=?
                ORDER BY COALESCE(manual, 0) DESC, COALESCE(updated_at, '') DESC
                """,
                (grp,),
            ).fetchall()
            for row in rows or []:
                row_freq = str(row["frequency"] or "").strip()
                if _normalize_frequency_key(row_freq) == freq_norm:
                    return str(row["name"] or "")
        return ""
    except Exception:
        try:
            r2 = conn.execute(
                "SELECT name FROM unit WHERE frequency=? AND group_=? LIMIT 1",
                (freq, grp),
            ).fetchone()
            if r2:
                return str(r2[0] or "")
            if freq_norm:
                rows2 = conn.execute(
                    "SELECT frequency, name FROM unit WHERE group_=?",
                    (grp,),
                ).fetchall()
                for row in rows2 or []:
                    row_freq = str(row[0] or "").strip()
                    if _normalize_frequency_key(row_freq) == freq_norm:
                        return str(row[1] or "")
            return ""
        except Exception:
            return ""


def get_pairs_for_unit_name(
    conn: sqlite3.Connection, unit_name: str
) -> list[dict[str, str]]:
    """
    Возвращает список пар (frequency, group_) из таблицы unit с заданным именем подразделения.
    Используется для add/remove избранного по unit_name в учёте интенсивности.
    """
    init_db(conn)
    name = str(unit_name or "").strip()
    if not name:
        return []
    try:
        cur = conn.execute(
            """
            SELECT DISTINCT frequency, group_
            FROM unit
            WHERE LOWER(TRIM(name)) = LOWER(?)
            """,
            (name,),
        )
        return [{"frequency": row[0], "group": row[1]} for row in cur.fetchall()]
    except Exception:
        try:
            cur = conn.execute(
                "SELECT DISTINCT frequency, group_ FROM unit WHERE TRIM(name) = ?",
                (name,),
            )
            return [{"frequency": row[0], "group": row[1]} for row in cur.fetchall()]
        except Exception:
            return []


def canonical_intensity_unit_key(name: str) -> str:
    """
    Ключ группировки подразделений в учёте интенсивности / общем анализе сети.

    Одно и то же подразделение часто вводят по-разному (пробелы, регистр; иногда с хвостом
    «N АК» / «N ak»). Без нормализации такие варианты попадали в разные «колонки».
    """
    import re

    n = " ".join(str(name or "").split())
    n = n.casefold()
    # Хвост « 2 АК », « 1 ак » (номер армейского корпуса) — объединяем с базовым названием.
    n = re.sub(r"\s+\d+\s*(?:ак|ak)\.?\s*$", "", n, flags=re.IGNORECASE)
    return n.strip()


def _is_unknown_intensity_unit_name(name: str) -> bool:
    n = str(name or "").strip().lower()
    if not n:
        return True
    if n.startswith("н/у") or "н/у подразделение" in n:
        return True
    if n in {"n/a", "na", "unknown", "без привязки", "не определено"}:
        return True
    return False


def list_units_tree(
    conn: sqlite3.Connection, *, position_name: str
) -> list[dict[str, Any]]:
    """
    Возвращает дерево подразделение -> список пар (frequency, group_code)
    на основе intercept_catalog.
    """
    init_db(conn)
    pos = str(position_name or "").strip()
    rows = conn.execute(
        """
        SELECT unit_name, frequency, group_code
        FROM intercept_catalog
        WHERE position_name=?
        ORDER BY unit_name, CAST(REPLACE(frequency, ',', '.') AS REAL) DESC, group_code
        """,
        (pos,),
    ).fetchall()
    m: dict[str, list[dict[str, str]]] = {}
    for r in rows:
        unit = str(r["unit_name"] or "")
        m.setdefault(unit, []).append(
            {
                "frequency": str(r["frequency"] or ""),
                "group": str(r["group_code"] or ""),
            }
        )
    out = []
    for unit, pairs in m.items():
        # unique pairs
        seen = set()
        uniq = []
        for p in pairs:
            key = (p["frequency"], p["group"])
            if key in seen:
                continue
            seen.add(key)
            uniq.append(p)
        out.append({"unit_name": unit, "pairs": uniq})
    # stable order
    out.sort(key=lambda x: x["unit_name"].lower())
    return out


def _unit_map(conn: sqlite3.Connection) -> dict[tuple[str, str], str]:
    cur = conn.cursor()
    units = cur.execute("SELECT frequency, group_, name FROM unit;").fetchall()
    m: dict[tuple[str, str], str] = {}
    for row in units:
        freq = row[0] or "*"
        group = row[1] or "*"
        # нормализуем частоту для сопоставления (141.0000 -> 141.0)
        freq_norm = _normalize_frequency_key(str(freq))
        group_str = str(group).strip()
        m[(freq_norm, group_str)] = str(row[2] or "")
        # также сохраняем оригинальный ключ для обратной совместимости
        m[(str(freq), group_str)] = str(row[2] or "")
    return m


def get_sessions_favorites(
    conn: sqlite3.Connection, user_id: int
) -> list[dict[str, Any]]:
    """Получает избранное пользователя для сеансов"""
    init_db(conn)
    cur = conn.cursor()
    cur.execute(
        "SELECT frequency, group_ FROM sessions_favorites WHERE user_id = ? ORDER BY created_at DESC",
        (user_id,),
    )
    return [{"frequency": row[0], "group": row[1]} for row in cur.fetchall()]


def add_sessions_favorite(
    conn: sqlite3.Connection, user_id: int, frequency: str, group: str
) -> bool:
    """Добавляет запись в избранное пользователя"""
    init_db(conn)
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT OR IGNORE INTO sessions_favorites (user_id, frequency, group_) VALUES (?, ?, ?)",
            (user_id, frequency, group),
        )
        conn.commit()
        return True
    except Exception:
        return False


def remove_sessions_favorite(
    conn: sqlite3.Connection, user_id: int, frequency: str, group: str
) -> bool:
    """Удаляет запись из избранного пользователя"""
    init_db(conn)
    cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM sessions_favorites WHERE user_id = ? AND frequency = ? AND group_ = ?",
            (user_id, frequency, group),
        )
        conn.commit()
        return cur.rowcount > 0
    except Exception:
        return False


def _norm_unit_note(s: str) -> str:
    t = (s or "").strip()
    t = t.replace("«", '"').replace("»", '"')
    for ch in ("\u2018", "\u2019", "\u02bc"):
        t = t.replace(ch, "'")
    return " ".join(t.split())


def parse_note_unit_parent_child(note: str) -> tuple[str, str | None]:
    """
    Делит note на (родитель, дочерняя метка), если:
    - в начале: «1 шб …», «1 бат 12 обр…», «1 ббпс…», другое «N аббр …»; «взвод связи…», «тр …»;
    - в конце: «… 1 шб», «… 1 бат»;
    - запасной разбор: «N краткое_сокр длинная_сводка_родителя».
    Иначе (исходная строка, None).
    """
    raw = (note or "").strip()
    if not raw or raw == "__none__":
        return (raw, None)
    for rx in _OSN_CHILD_PREFIX:
        m = rx.match(raw)
        if not m:
            continue
        parent = str(m.group("parent") or "").strip().rstrip(" \t,;|/\\–-()")
        child = str(m.group("child") or "").strip()
        if not parent or not child:
            continue
        return (parent, child)
    loose = _try_loose_child_prefix(raw)
    if loose:
        return loose
    for rx in _OSN_CHILD_SUFFIX:
        m = rx.search(raw)
        if not m:
            continue
        parent = raw[: m.start()].rstrip(" \t,;|/\\–-()")
        child = str(m.group("child") or "").strip()
        if not parent or not child:
            return (raw, None)
        return (parent, child)
    return (raw, None)


def _try_loose_child_prefix(raw: str) -> tuple[str, str] | None:
    """
    «N <краткое_сокращение> <длинное_название_родителя>» — если явные шаблоны не сработали.
    Родитель как правило многословный; токен — 2–9 букв/цифр (ббпс, омсбр, тд).
    """
    s = (raw or "").strip()
    if len(s) < 12:
        return None
    m = re.match(
        r"^(\d{1,3})\s+([0-9A-Za-zА-Яа-яЁё/]+)\s+(.+)$",
        s,
    )
    if not m:
        return None
    num, abbr, parent = m.group(1), m.group(2).strip(), m.group(3).strip()
    if not abbr or not parent:
        return None
    if not re.fullmatch(r"[0-9A-Za-zА-Яа-яЁё/]+", abbr):
        return None
    al = len(abbr)
    if al < 2 or al > 10:
        return None
    low3 = abbr[:3].lower()
    if low3 in _OSN_BANNED_ABBR or abbr.lower() in _OSN_BANNED_ABBR:
        return None
    if abbr.isdigit():
        return None
    if len(parent) < 6:
        return None
    if " " not in parent and len(parent) < 14:
        return None
    child = f"{num} {abbr}"
    return (parent, child)


def _unit_parent_groups_file() -> Path:
    return Path(__file__).resolve().parent.parent / "data" / "unit_parent_groups.txt"


def load_unit_parent_manual_groups() -> list[list[str]]:
    """
    data/unit_parent_groups.txt — группы подряд идущих непустых строк (разделитель — пустая строка).
    В каждой группе: первая строка = каноническое имя «родителя» на карточке, остальные — варианты note,
    которые должны сливаться в ту же карточку (краткое/полное имя, другое написание кавычек).
    """
    p = _unit_parent_groups_file()
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    groups: list[list[str]] = []
    cur: list[str] = []
    for line in text.splitlines():
        raw = line.rstrip()
        if not raw.strip():
            if cur:
                groups.append(cur)
                cur = []
            continue
        if raw.lstrip().startswith("#"):
            continue
        cur.append(_norm_unit_note(" ".join(raw.split())))
    if cur:
        groups.append(cur)
    return [g for g in groups if len(g) >= 2]


def get_unit_family_by_parent_key(
    conn: sqlite3.Connection, parent_key: str
) -> dict[str, Any] | None:
    """Одна семья из list_online_search_unit_families по parent_key."""
    from web_portal.lib.db.online_search import list_online_search_unit_families
    pk = (parent_key or "").strip()
    if not pk:
        return None
    for fam in list_online_search_unit_families(conn):
        if str(fam.get("parent_key") or "") == pk:
            return fam
    return None


def match_callsign_for_corr(
    main_conn: sqlite3.Connection,
    *,
    unit_note: str,
    frequency: str,
    group_id: str,
    corr: str,
) -> dict[str, Any] | None:
    """
    Сопоставить ID корреспондента (col4) с записью в intercept_callsigns.
    Учитываем пару частота/группа и при необходимости имя подразделения.
    """
    code = str(corr or "").strip()
    if not code:
        return None
    init_db(main_conn)
    un = (unit_note or "").strip()
    f = (frequency or "").strip().replace(",", ".")
    g = (group_id or "").strip()
    f_alt = f.replace(".", ",") if f else ""
    alts: list[str] = [code]
    if code.lstrip("0") and code.lstrip("0") != code:
        alts.append(code.lstrip("0"))
    if code.isdigit() and int(code) >= 0:
        alts.append(str(int(code)))

    rows_raw: list[sqlite3.Row] = []
    seen: set[str] = set()
    for c in alts:
        c = c.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        cur = main_conn.execute(
            """
            SELECT id, label, code, tag, tag_desc, unit_name, frequency, group_code, position_name
            FROM intercept_callsigns
            WHERE code = ?
            """,
            (c,),
        )
        rows_raw.extend(cur.fetchall())
    seen_ids: set[int] = set()
    rows: list[sqlite3.Row] = []
    for r in rows_raw:
        i = int(r["id"])
        if i in seen_ids:
            continue
        seen_ids.add(i)
        rows.append(r)

    if not rows:
        return None

    def _norm_freq(x: str) -> str:
        return (x or "").replace(",", ".").strip()

    def score(r: sqlite3.Row) -> int:
        s = 0
        rf = _norm_freq(str(r["frequency"] or ""))
        gcf = str(r["group_code"] or "").strip()
        if f and (rf in (f, f_alt) or f_alt and rf in (f, f_alt)) and g and gcf == g:
            s += 20
        elif f and rf in (f, f_alt) and (not gcf or gcf == g):
            s += 10
        if un and str(r["unit_name"] or "").strip() == un:
            s += 8
        if s == 0 and f and (rf in (f, f_alt) or not rf):
            s += 2
        return s

    best = max(rows, key=score)
    if score(best) == 0:
        best = rows[0]
    return {
        "label": str(best["label"] or ""),
        "code": str(best["code"] or ""),
        "tag": str(best["tag"] or ""),
        "unit_name": str(best["unit_name"] or ""),
        "frequency": str(best["frequency"] or ""),
        "group_code": str(best["group_code"] or ""),
    }


def list_unit_rows_after_rowid(
    conn: sqlite3.Connection, *, after_rowid: int, limit: int = 5000
) -> list[dict[str, Any]]:
    """
    Инкрементальная выборка unit через rowid.
    """
    init_db(conn)
    limit = max(1, min(int(limit), 20000))
    ar = int(after_rowid or 0)
    rows = conn.execute(
        """
        SELECT rowid as rowid, frequency, group_, name, manual, updated_at
        FROM unit
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
                "frequency": str(r["frequency"] or ""),
                "group_": str(r["group_"] or ""),
                "name": str(r["name"] or ""),
                "manual": int(r["manual"] or 0),
                "updated_at": str(r["updated_at"] or ""),
            }
        )
    return out


def list_unit_rows_since(
    conn: sqlite3.Connection, *, since_ts: str, limit: int = 5000
) -> list[dict[str, Any]]:
    """
    Выборка unit по updated_at для синхронизации "сервер -> HUB" (pull).
    """
    init_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    limit = max(1, min(int(limit), 20000))
    rows = conn.execute(
        """
        SELECT frequency, group_, name, manual, updated_at
        FROM unit
        WHERE COALESCE(updated_at,'') >= ?
        ORDER BY COALESCE(updated_at,'') ASC
        LIMIT ?
        """,
        (since, limit),
    ).fetchall()
    return [
        {
            "frequency": str(r["frequency"] or ""),
            "group_": str(r["group_"] or ""),
            "name": str(r["name"] or ""),
            "manual": int(r["manual"] or 0),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def list_dict_frequencies(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Справочник частот/групп только из перехватов (intercept_catalog + intercept_items).
    last_recorded — когда в последний раз была запись в бланке перехвата по этой паре.
    """
    from web_portal.lib.db.intercepts import _get_last_recorded_intercept_by_freq_group
    init_db(conn)
    last_map = _get_last_recorded_intercept_by_freq_group(conn)
    # Все уникальные пары (frequency, group_code, unit_name) из каталога и из записей смен
    rows = conn.execute(
        """
        SELECT DISTINCT frequency, group_code, unit_name
        FROM (
            SELECT frequency, group_code, unit_name FROM intercept_catalog
            UNION
            SELECT frequency, group_code, unit_name FROM intercept_items
        )
        WHERE NOT (
            TRIM(COALESCE(frequency, '')) = ''
            AND TRIM(COALESCE(group_code, '')) = ''
            AND TRIM(COALESCE(unit_name, '')) = ''
        )
        ORDER BY unit_name, frequency, group_code
        """
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows or []:
        freq = str(r["frequency"] or "")
        grp = str(r["group_code"] or "")
        last_recorded = last_map.get((freq, grp), "")
        out.append(
            {
                "frequency": freq,
                "group": grp,
                "unit_name": str(r["unit_name"] or "").strip(),
                "manual": 0,
                "updated_at": "",
                "last_recorded": last_recorded,
            }
        )
    return out


def list_dict_units(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Справочник подразделений только из перехватов (которые были или находятся в перехватах).
    Группирует по unit_name из intercept_catalog и intercept_items, с датой последней записи.
    """
    freq_rows = list_dict_frequencies(conn)
    units: dict[str, dict[str, Any]] = {}
    for row in freq_rows:
        name = str(row.get("unit_name") or "").strip()
        key = name if name else "(не указано)"
        if key not in units:
            units[key] = {
                "unit_name": key,
                "frequencies": [],
                "last_recorded": "",
            }
        units[key]["frequencies"].append(
            {
                "frequency": row.get("frequency") or "",
                "group": row.get("group") or "",
                "manual": 0,
                "last_recorded": str(row.get("last_recorded") or ""),
            }
        )
        lr = str(row.get("last_recorded") or "")
        if lr and (not units[key]["last_recorded"] or lr > units[key]["last_recorded"]):
            units[key]["last_recorded"] = lr
    out = list(units.values())
    out.sort(key=lambda x: str(x.get("unit_name") or "").lower())
    return out


def list_dict_callsigns(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """
    Справочник позывных (перехваты + авиация).

    Для перехватов берёт intercept_callsigns, для авиации — aviation_callsigns.
    """
    init_db(conn)
    out: list[dict[str, Any]] = []

    # Перехваты
    rows = conn.execute(
        """
        SELECT id, position_name, label, code, tag, tag_desc, tag_color,
               unit_name, frequency, group_code, created_at, updated_at
        FROM intercept_callsigns
        ORDER BY position_name, label
        """
    ).fetchall()
    for r in rows or []:
        out.append(
            {
                "id": int(r["id"]),
                "source": "intercepts",
                "position_name": str(r["position_name"] or ""),
                "label": str(r["label"] or ""),
                "code": str(r["code"] or ""),
                "tag": str(r["tag"] or ""),
                "tag_desc": str(r["tag_desc"] or ""),
                "tag_color": str(r["tag_color"] or ""),
                "unit_name": str(r["unit_name"] or ""),
                "frequency": str(r["frequency"] or ""),
                "group": str(r["group_code"] or ""),
                "created_at": str(r["created_at"] or ""),
                "updated_at": str(r["updated_at"] or ""),
            }
        )

    # Авиация: позывные авиации храним без unit_name, но включаем в справочник
    from web_portal.lib.aviation_db import get_aviation_callsigns

    avi_rows = get_aviation_callsigns(conn)
    for r in avi_rows or []:
        out.append(
            {
                "id": int(r.get("id") or 0),
                "source": "aviation",
                "position_name": "",
                "label": str(r.get("label") or ""),
                "code": "",
                "tag": "",
                "tag_desc": "",
                "tag_color": "",
                "unit_name": "",
                "frequency": str(r.get("frequency") or ""),
                "group": "",
                "created_at": str(r.get("created_at") or ""),
                "updated_at": str(r.get("updated_at") or ""),
            }
        )

    return out


__all__ = [
    "freq_zone_for_sessions_merge",
    "sessions_favorite_matches_row",
    "build_sessions_favorite_match_set",
    "sessions_row_is_favorite",
    "apply_search_note_to_unit",
    "update_unit_name",
    "get_pairs_for_unit_name",
    "canonical_intensity_unit_key",
    "list_units_tree",
    "get_sessions_favorites",
    "add_sessions_favorite",
    "remove_sessions_favorite",
    "parse_note_unit_parent_child",
    "load_unit_parent_manual_groups",
    "get_unit_family_by_parent_key",
    "match_callsign_for_corr",
    "list_unit_rows_after_rowid",
    "list_unit_rows_since",
    "list_dict_frequencies",
    "list_dict_units",
    "list_dict_callsigns",
]
