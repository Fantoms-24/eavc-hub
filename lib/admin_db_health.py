"""
Диагностика основной БД сеансов (seanses + unit) для админ-панели.
Проверяет типичные причины «лишних» корреспондентов в аналитике по радиосетям.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from typing import Any


def _norm_aes_display(ak: str | None) -> str:
    s = str(ak or "").strip()
    return s if s else "(нет ключа)"


def _parse_db_datetime(s: str | None) -> datetime | None:
    if s is None:
        return None
    raw = str(s).strip()[:19]
    if len(raw) < 10:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H-%M-%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _fmt_db_datetime(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _filter_followup_rows_after_anchor_cap(
    win_rows: list[Any],
    *,
    anchor_dt: datetime,
    mode: str,
    day_end_excl: datetime | None,
    rolling_end_dt: datetime | None,
    after_id_hours: int,
) -> list[Any]:
    """
    Оставляет все строки **до** якоря (первый выход ID) и только те **с якоря и позже**,
    у которых date_time не позже min(конец основного окна, якорь + after_id_hours).
    Строки с неразобранным date_time не отбрасываются.
    """
    ah = max(0, min(int(after_id_hours), 168))
    if ah <= 0 or not win_rows:
        return list(win_rows)
    post_end = anchor_dt + timedelta(hours=ah)
    out: list[Any] = []
    for wr in win_rows:
        dts = str(
            wr["date_time"] if hasattr(wr, "keys") else wr[0] or ""
        ).strip()
        dtp = _parse_db_datetime(dts)
        if dtp is None:
            out.append(wr)
            continue
        if dtp < anchor_dt:
            out.append(wr)
            continue
        if mode == "calendar_day":
            if day_end_excl is None:
                out.append(wr)
                continue
            if dtp >= day_end_excl:
                continue
            if dtp <= post_end:
                out.append(wr)
        else:
            if rolling_end_dt is None:
                out.append(wr)
                continue
            eff_end = min(rolling_end_dt, post_end)
            if dtp <= eff_end:
                out.append(wr)
    return out


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    r = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (str(table),),
    ).fetchone()
    return r is not None


def _resolve_seanses_table(conn: sqlite3.Connection) -> str | None:
    for t in ("seanses", "Seanses"):
        if _table_exists(conn, t):
            return t
    return None


def _resolve_unit_table(conn: sqlite3.Connection) -> str | None:
    for t in ("unit", "Unit"):
        if _table_exists(conn, t):
            return t
    return None


def _rows_as_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows or []:
        if hasattr(r, "keys"):
            out.append({k: r[k] for k in r.keys()})
        else:
            out.append(dict(r))
    return out


def _fetch_correspondent_aes_stats(
    conn: sqlite3.Connection,
    seans_q: str,
    cid: str,
    *,
    max_pairs: int,
    max_aes_detail_rows: int,
) -> dict[str, Any]:
    """
    По ID корреспондента: сколько разных AES key id на каждой паре частота/группа,
    детализация первый/последний сеанс на каждом ключе, каналы с явной сменой ключа.
    """
    out: dict[str, Any] = {
        "pairs": [],
        "aes_keys_detail": [],
        "aes_key_rotations": [],
    }
    pairs = conn.execute(
        f"""
        SELECT frequency, group_, COUNT(*) AS sessions,
               MIN(date_time) AS first_dt, MAX(date_time) AS last_dt,
               COUNT(DISTINCT TRIM(COALESCE(aes_key, ''))) AS aes_key_variants
        FROM {seans_q}
        WHERE id = ?
        GROUP BY frequency, group_
        ORDER BY sessions DESC
        LIMIT ?
        """,
        (cid, max_pairs),
    ).fetchall()
    out["pairs"] = _rows_as_dicts(list(pairs))

    detail = conn.execute(
        f"""
        SELECT frequency, group_,
               TRIM(COALESCE(aes_key, '')) AS aes_key_raw,
               COUNT(*) AS sessions,
               MIN(date_time) AS first_dt,
               MAX(date_time) AS last_dt
        FROM {seans_q}
        WHERE id = ?
        GROUP BY frequency, group_, TRIM(COALESCE(aes_key, ''))
        ORDER BY frequency, group_, MIN(date_time)
        LIMIT ?
        """,
        (cid, max_aes_detail_rows),
    ).fetchall()
    detail_list: list[dict[str, Any]] = []
    for r in detail:
        d = dict(r)
        ak = str(d.get("aes_key_raw") or "").strip()
        d["aes_key"] = ak if ak else "(нет ключа)"
        d.pop("aes_key_raw", None)
        detail_list.append(d)
    out["aes_keys_detail"] = detail_list
    out["aes_keys_detail_truncated"] = len(detail_list) >= max_aes_detail_rows

    rot = conn.execute(
        f"""
        SELECT frequency, group_,
               COUNT(DISTINCT TRIM(COALESCE(aes_key, ''))) AS key_variants,
               GROUP_CONCAT(DISTINCT
                 CASE
                   WHEN TRIM(COALESCE(aes_key, '')) = '' THEN '(нет ключа)'
                   ELSE TRIM(aes_key)
                 END
               ) AS aes_keys_seen
        FROM {seans_q}
        WHERE id = ?
        GROUP BY frequency, group_
        HAVING COUNT(DISTINCT TRIM(COALESCE(aes_key, ''))) > 1
        ORDER BY frequency, group_
        LIMIT 80
        """,
        (cid,),
    ).fetchall()
    out["aes_key_rotations"] = _rows_as_dicts(list(rot))
    return out


def _fetch_aes_followup_channels(
    conn: sqlite3.Connection,
    seans_q: str,
    cid: str,
    *,
    window_mode: str = "calendar_day",
    rolling_hours: int = 24,
    after_id_hours: int = 0,
    max_channels: int = 80,
    max_rows: int = 12000,
) -> list[dict[str, Any]]:
    """
    Для каждого канала (частота, группа), где встречается корреспондент:
    1) Находим первое появление выбранного ID на канале (якорь).
    2) Берём все сеансы на этой паре частота+группа за окно времени — **любые**
       корреспонденты, не только выбранный ID.
    Окно:
      - calendar_day: календарные сутки дня якоря [00:00:00; следующий день 00:00:00)
      - rolling: [якорь; якорь + rolling_hours] включительно по верхней границе
    Параметр **after_id_hours** (1–168): после выборки дополнительно отсекаются сеансы **после**
    якоря с момента строго позже «якорь + N часов» (до конца основного окна). 0 = без отсечки.
    Дополнительно по времени **первого** появления выбранного ID на канале:
    - множества **непустых** AES key id до этого момента и с него (в пределах окна);
    - **новые** ключи после появления ID = те, что встречаются «с первого выхода», но не
      встречались «до» — в UI подсвечиваются отдельно (не вся строка).
    """
    out: list[dict[str, Any]] = []
    mode = (window_mode or "calendar_day").strip().lower()
    if mode not in ("calendar_day", "rolling"):
        mode = "calendar_day"
    hours = max(1, min(int(rolling_hours), 168))

    ch_rows = conn.execute(
        f"""
        SELECT DISTINCT frequency, group_
        FROM {seans_q}
        WHERE id = ?
        ORDER BY frequency, group_
        LIMIT ?
        """,
        (cid, max_channels),
    ).fetchall()

    for ch in ch_rows:
        freq = str(ch["frequency"] if hasattr(ch, "keys") else ch[0] or "")
        grp = str(ch["group_"] if hasattr(ch, "keys") else ch[1] or "")

        first_r = conn.execute(
            f"""
            SELECT date_time, TRIM(COALESCE(aes_key, '')) AS ak
            FROM {seans_q}
            WHERE id = ? AND frequency = ? AND group_ = ?
            ORDER BY date_time ASC
            LIMIT 1
            """,
            (cid, freq, grp),
        ).fetchone()
        if not first_r:
            continue

        first_dt_s = str(
            first_r["date_time"] if hasattr(first_r, "keys") else first_r[0] or ""
        ).strip()
        ak_first_raw = (
            first_r["ak"] if hasattr(first_r, "keys") else first_r[1]
        )
        key_at_correspondent_first = _norm_aes_display(ak_first_raw)

        dt0 = _parse_db_datetime(first_dt_s)
        if not dt0:
            out.append(
                {
                    "frequency": freq,
                    "group_": grp,
                    "first_correspondent_dt": first_dt_s,
                    "aes_key_when_correspondent_first": key_at_correspondent_first,
                    "window_mode": mode,
                    "error": "Не удалось разобрать date_time (ожидается YYYY-MM-DD HH:MM:SS)",
                    "alert_red": False,
                }
            )
            continue

        day_end_excl: datetime | None = None
        rolling_end_dt: datetime | None = None
        if mode == "calendar_day":
            day_start = dt0.replace(hour=0, minute=0, second=0, microsecond=0)
            day_end_excl = day_start + timedelta(days=1)
            win_start_s = _fmt_db_datetime(day_start)
            win_end_excl_s = _fmt_db_datetime(day_end_excl)
            win_end_display_s = _fmt_db_datetime(day_end_excl - timedelta(seconds=1))
            win_label = f"календарный день {day_start.strftime('%Y-%m-%d')}"
            win_rows = conn.execute(
                f"""
                SELECT date_time, id, TRIM(COALESCE(aes_key, '')) AS ak
                FROM {seans_q}
                WHERE frequency = ? AND group_ = ?
                  AND date_time >= ? AND date_time < ?
                ORDER BY date_time
                LIMIT ?
                """,
                (freq, grp, win_start_s, win_end_excl_s, max_rows),
            ).fetchall()
        else:
            end_dt = dt0 + timedelta(hours=hours)
            rolling_end_dt = end_dt
            win_start_s = first_dt_s
            win_end_display_s = _fmt_db_datetime(end_dt)
            win_label = f"скользящие {hours} ч от первого выхода"
            win_rows = conn.execute(
                f"""
                SELECT date_time, id, TRIM(COALESCE(aes_key, '')) AS ak
                FROM {seans_q}
                WHERE frequency = ? AND group_ = ?
                  AND date_time >= ? AND date_time <= ?
                ORDER BY date_time
                LIMIT ?
                """,
                (freq, grp, first_dt_s, win_end_display_s, max_rows),
            ).fetchall()

        after_h = max(0, min(int(after_id_hours), 168))
        slice_end_note: str | None = None
        if after_h > 0:
            post_end = dt0 + timedelta(hours=after_h)
            if mode == "calendar_day" and day_end_excl is not None:
                last_in_day = day_end_excl - timedelta(seconds=1)
                slice_until = min(post_end, last_in_day)
                slice_end_note = _fmt_db_datetime(slice_until)
            elif mode == "rolling" and rolling_end_dt is not None:
                slice_until = min(post_end, rolling_end_dt)
                slice_end_note = _fmt_db_datetime(slice_until)
            win_label += f"; после ID — {after_h} ч (до {slice_end_note or '—'})"
            win_rows = _filter_followup_rows_after_anchor_cap(
                win_rows,
                anchor_dt=dt0,
                mode=mode,
                day_end_excl=day_end_excl,
                rolling_end_dt=rolling_end_dt,
                after_id_hours=after_h,
            )

        keys_order: list[str] = []
        seen: set[str] = set()
        segments: list[dict[str, Any]] = []
        cur_key: str | None = None
        cur_start: str | None = None
        cur_end: str | None = None
        cur_cnt = 0
        cur_has_cid = False

        rows_missing_aes = 0
        rows_with_aes = 0
        nonempty_keys: set[str] = set()
        keys_before_first: set[str] = set()
        keys_from_first: set[str] = set()

        for wr in win_rows:
            dts = str(
                wr["date_time"] if hasattr(wr, "keys") else wr[0] or ""
            ).strip()
            rid = str(wr["id"] if hasattr(wr, "keys") else wr[1] or "").strip()
            ak_raw = wr["ak"] if hasattr(wr, "keys") else wr[2]
            ak_trim = str(ak_raw or "").strip()
            if ak_trim:
                rows_with_aes += 1
                nonempty_keys.add(ak_trim)
                if dts < first_dt_s:
                    keys_before_first.add(ak_trim)
                else:
                    keys_from_first.add(ak_trim)
            else:
                rows_missing_aes += 1

            ak = _norm_aes_display(ak_raw)
            if ak not in seen:
                seen.add(ak)
                keys_order.append(ak)

            if cur_key is None:
                cur_key = ak
                cur_start = dts
                cur_end = dts
                cur_cnt = 1
                cur_has_cid = rid == cid
            elif ak == cur_key:
                cur_end = dts
                cur_cnt += 1
                if rid == cid:
                    cur_has_cid = True
            else:
                segments.append(
                    {
                        "aes_key": cur_key,
                        "from_dt": cur_start or "",
                        "to_dt": cur_end or "",
                        "row_count": cur_cnt,
                        "includes_correspondent": cur_has_cid,
                    }
                )
                cur_key = ak
                cur_start = dts
                cur_end = dts
                cur_cnt = 1
                cur_has_cid = rid == cid

        if cur_key is not None:
            segments.append(
                {
                    "aes_key": cur_key,
                    "from_dt": cur_start or "",
                    "to_dt": cur_end or "",
                    "row_count": cur_cnt,
                    "includes_correspondent": cur_has_cid,
                }
            )

        distinct_n = len(seen)
        key_change_within_window = distinct_n > 1
        nonempty_sorted = sorted(nonempty_keys, key=lambda x: (len(x), x))
        keys_before_sorted = sorted(keys_before_first, key=lambda x: (len(x), x))
        keys_from_sorted = sorted(keys_from_first, key=lambda x: (len(x), x))
        keys_new_after_first = sorted(
            keys_from_first - keys_before_first, key=lambda x: (len(x), x)
        )
        only_empty_aes = rows_with_aes == 0 and rows_missing_aes > 0

        out.append(
            {
                "frequency": freq,
                "group_": grp,
                "window_mode": mode,
                "rolling_hours": hours if mode == "rolling" else None,
                "after_id_hours": after_h,
                "slice_end_after_anchor_dt": slice_end_note,
                "window_label": win_label,
                "first_correspondent_dt": first_dt_s,
                "window_start_dt": win_start_s,
                "window_end_dt": win_end_display_s,
                "aes_key_when_correspondent_first": key_at_correspondent_first,
                "distinct_keys_in_window": distinct_n,
                "nonempty_keys_distinct": nonempty_sorted,
                "nonempty_keys_before_first": keys_before_sorted,
                "nonempty_keys_from_first_onward": keys_from_sorted,
                "nonempty_keys_new_after_first": keys_new_after_first,
                "has_new_aes_after_first": len(keys_new_after_first) > 0,
                "nonempty_keys_count": len(nonempty_keys),
                "rows_missing_aes_key": rows_missing_aes,
                "rows_with_aes_key": rows_with_aes,
                "only_empty_aes_in_window": only_empty_aes,
                "key_change_within_window": key_change_within_window,
                "alert_red": False,
                "channel_rows_in_window": len(win_rows),
                "window_hits_row_limit": len(win_rows) >= max_rows,
                "keys_sequence": " → ".join(keys_order),
                "timeline": segments,
            }
        )

    return out


def run_admin_db_health_checks(
    conn: sqlite3.Connection,
    *,
    correspondent_id: str | None = None,
    max_detail_rows: int = 120,
    max_network_names: int = 500,
    max_aes_detail_rows: int = 300,
    aes_followup_mode: str = "calendar_day",
    aes_followup_hours: int = 24,
    aes_after_id_hours: int = 0,
    max_aes_followup_channels: int = 80,
    max_aes_followup_rows: int = 12000,
) -> dict[str, Any]:
    seans_t = _resolve_seanses_table(conn)
    unit_t = _resolve_unit_table(conn)
    findings: list[dict[str, Any]] = []

    if not seans_t:
        findings.append(
            {
                "id": "missing_seanses",
                "severity": "error",
                "title": "Нет таблицы сеансов",
                "explanation": "Ожидалась таблица seanses (или Seanses).",
                "rows": [],
                "row_count": 0,
            }
        )
        return {
            "ok": False,
            "seanses_table": None,
            "unit_table": unit_t,
            "summary": {},
            "findings": findings,
            "correspondent": None,
        }

    if not unit_t:
        findings.append(
            {
                "id": "missing_unit",
                "severity": "error",
                "title": "Нет таблицы unit",
                "explanation": "Справочник подразделений (unit) отсутствует — привязка радиосетей к частоте/группе недоступна.",
                "rows": [],
                "row_count": 0,
            }
        )

    seans_q = _quote_ident(seans_t)
    summary: dict[str, Any] = {"seanses_table": seans_t, "unit_table": unit_t}

    try:
        n = int(conn.execute(f"SELECT COUNT(*) FROM {seans_q};").fetchone()[0])
        summary["seanses_count"] = n
        rng = conn.execute(
            f"SELECT MIN(date_time), MAX(date_time) FROM {seans_q};"
        ).fetchone()
        summary["seanses_date_min"] = str(rng[0]) if rng and rng[0] else None
        summary["seanses_date_max"] = str(rng[1]) if rng and rng[1] else None
    except Exception as e:
        summary["seanses_error"] = str(e)

    if unit_t:
        unit_q = _quote_ident(unit_t)
        try:
            summary["unit_count"] = int(
                conn.execute(f"SELECT COUNT(*) FROM {unit_q};").fetchone()[0]
            )
        except Exception:
            summary["unit_count"] = None

        # Полный wildcard: как в аналитике — любой сеанс подходит под имя сети.
        try:
            wild_rows = conn.execute(
                f"""
                SELECT name, frequency, group_
                FROM {unit_q}
                WHERE TRIM(IFNULL(frequency,'')) = '*' AND TRIM(IFNULL(group_,'')) = '*'
                ORDER BY name
                LIMIT ?
                """,
                (max_detail_rows + 1,),
            ).fetchall()
            wild_list = _rows_as_dicts(list(wild_rows))
            cnt = conn.execute(
                f"""
                SELECT COUNT(*) FROM {unit_q}
                WHERE TRIM(IFNULL(frequency,'')) = '*' AND TRIM(IFNULL(group_,'')) = '*'
                """
            ).fetchone()[0]
            if int(cnt or 0) > 0:
                findings.append(
                    {
                        "id": "unit_double_star",
                        "severity": "warning",
                        "title": "Подразделения с частотой * и группой *",
                        "explanation": "Такие строки в unit совпадают с любым сеансом в БД (как в запросах анализа). "
                        "Если таких имён несколько, один и тот же ID корреспондента может «появляться» во всех этих радиосетях.",
                        "rows": wild_list[:max_detail_rows],
                        "row_count": int(cnt or 0),
                    }
                )
        except Exception as e:
            findings.append(
                {
                    "id": "unit_wildcard_query_error",
                    "severity": "error",
                    "title": "Ошибка проверки wildcard в unit",
                    "explanation": str(e),
                    "rows": [],
                    "row_count": 0,
                }
            )

        # Одна пара (частота, группа) — несколько разных имён (неоднозначность).
        try:
            amb_rows = conn.execute(
                f"""
                SELECT frequency, group_, COUNT(DISTINCT name) AS name_count,
                       GROUP_CONCAT(DISTINCT name) AS names
                FROM {unit_q}
                GROUP BY frequency, group_
                HAVING COUNT(DISTINCT name) > 1
                ORDER BY name_count DESC, frequency, group_
                LIMIT ?
                """,
                (max_detail_rows + 1,),
            ).fetchall()
            amb_list = _rows_as_dicts(list(amb_rows))
            if amb_list:
                findings.append(
                    {
                        "id": "unit_ambiguous_pairs",
                        "severity": "warning",
                        "title": "Одна пара частота/группа — несколько имён",
                        "explanation": "В справочнике для одной и той же пары заданы разные названия подразделений; "
                        "это может путать отчёты и фильтры.",
                        "rows": amb_list[:max_detail_rows],
                        "row_count": len(amb_list),
                    }
                )
        except Exception as e:
            findings.append(
                {
                    "id": "unit_ambiguous_query_error",
                    "severity": "error",
                    "title": "Ошибка проверки дубликатов имён в unit",
                    "explanation": str(e),
                    "rows": [],
                    "row_count": 0,
                }
            )

    correspondent_block: dict[str, Any] | None = None
    cid = str(correspondent_id or "").strip()
    if cid and unit_t:
        unit_q = _quote_ident(unit_t)
        try:
            aes_stats = _fetch_correspondent_aes_stats(
                conn,
                seans_q,
                cid,
                max_pairs=max_detail_rows,
                max_aes_detail_rows=max_aes_detail_rows,
            )
            pairs_list = aes_stats["pairs"]
            total = conn.execute(
                f"SELECT COUNT(*) FROM {seans_q} WHERE id = ?;", (cid,)
            ).fetchone()[0]
            net_rows = conn.execute(
                f"""
                SELECT DISTINCT u.name
                FROM {unit_q} u
                WHERE EXISTS (
                  SELECT 1 FROM {seans_q} s
                  WHERE s.id = ?
                    AND (u.frequency = s.frequency OR u.frequency = '*')
                    AND (u.group_ = s.group_ OR u.group_ = '*')
                )
                ORDER BY 1
                LIMIT ?
                """,
                (cid, max_network_names + 1),
            ).fetchall()
            networks = [str(r[0]) for r in net_rows if r and r[0]]
            correspondent_block = {
                "id": cid,
                "total_sessions": int(total or 0),
                "pairs": pairs_list,
                "aes_keys_detail": aes_stats.get("aes_keys_detail") or [],
                "aes_keys_detail_truncated": bool(
                    aes_stats.get("aes_keys_detail_truncated")
                ),
                "aes_key_rotations": aes_stats.get("aes_key_rotations") or [],
                "aes_followup": _fetch_aes_followup_channels(
                    conn,
                    seans_q,
                    cid,
                    window_mode=aes_followup_mode,
                    rolling_hours=aes_followup_hours,
                    after_id_hours=aes_after_id_hours,
                    max_channels=max_aes_followup_channels,
                    max_rows=max_aes_followup_rows,
                ),
                "networks_matching": networks[:max_network_names],
                "networks_matching_truncated": len(networks) > max_network_names,
            }
        except Exception as e:
            correspondent_block = {
                "id": cid,
                "error": str(e),
            }

    elif cid and not unit_t:
        try:
            aes_stats = _fetch_correspondent_aes_stats(
                conn,
                seans_q,
                cid,
                max_pairs=max_detail_rows,
                max_aes_detail_rows=max_aes_detail_rows,
            )
            total = conn.execute(
                f"SELECT COUNT(*) FROM {seans_q} WHERE id = ?;", (cid,)
            ).fetchone()[0]
            correspondent_block = {
                "id": cid,
                "total_sessions": int(total or 0),
                "pairs": aes_stats["pairs"],
                "aes_keys_detail": aes_stats.get("aes_keys_detail") or [],
                "aes_keys_detail_truncated": bool(
                    aes_stats.get("aes_keys_detail_truncated")
                ),
                "aes_key_rotations": aes_stats.get("aes_key_rotations") or [],
                "aes_followup": _fetch_aes_followup_channels(
                    conn,
                    seans_q,
                    cid,
                    window_mode=aes_followup_mode,
                    rolling_hours=aes_followup_hours,
                    after_id_hours=aes_after_id_hours,
                    max_channels=max_aes_followup_channels,
                    max_rows=max_aes_followup_rows,
                ),
                "networks_matching": [],
                "networks_matching_truncated": False,
                "note": "Таблица unit отсутствует — список радиосетей по правилам анализа не строится.",
            }
        except Exception as e:
            correspondent_block = {"id": cid, "error": str(e)}

    if not any(str(f.get("severity") or "") in ("warning", "error") for f in findings):
        findings.append(
            {
                "id": "no_issues",
                "severity": "info",
                "title": "Критичных шаблонов не найдено",
                "explanation": "Двойных wildcard (*,*) в unit и неоднозначных пар с несколькими именами не обнаружено "
                "(в пределах лимита выборки). При сомнениях укажите ID корреспондента в форме ниже.",
                "rows": [],
                "row_count": 0,
            }
        )

    return {
        "ok": True,
        "seanses_table": seans_t,
        "unit_table": unit_t,
        "summary": summary,
        "findings": findings,
        "correspondent": correspondent_block,
    }


def run_seanses_multi_channel_day_report(
    conn: sqlite3.Connection,
    *,
    calendar_date: str,
    only_id: str | None = None,
    max_ids: int = 400,
) -> dict[str, Any]:
    """
    За календарные сутки YYYY-MM-DD: ID корреспондента встречается на двух и более
    различных парах (frequency, group_) в seanses — типичный повод проверить парсер/импорт.
    """
    seans_t = _resolve_seanses_table(conn)
    raw = str(calendar_date).strip()[:10]
    if not seans_t:
        return {
            "seanses_table": None,
            "error": "Нет таблицы сеансов (seanses / Seanses).",
            "date": raw,
            "items": [],
            "multi_channel_id_count": 0,
        }

    dt_day = _parse_db_datetime(raw + " 00:00:00")
    if not dt_day:
        return {
            "seanses_table": seans_t,
            "error": "Неверная дата (ожидается YYYY-MM-DD).",
            "date": raw,
            "items": [],
            "multi_channel_id_count": 0,
        }

    day_start = dt_day.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end_excl = day_start + timedelta(days=1)
    win_start_s = _fmt_db_datetime(day_start)
    win_end_excl_s = _fmt_db_datetime(day_end_excl)
    seans_q = _quote_ident(seans_t)

    cap = max(1, min(int(max_ids), 500))
    lim_fetch = cap + 1

    oid = str(only_id or "").strip() or None
    id_extra = ""
    params_summary: list[Any] = [win_start_s, win_end_excl_s]
    if oid:
        id_extra = " AND id = ?"
        params_summary.append(oid)

    summary_sql = f"""
        SELECT id, SUM(cnt) AS sessions, COUNT(*) AS channel_count
        FROM (
            SELECT id, frequency, group_, COUNT(*) AS cnt
            FROM {seans_q}
            WHERE date_time >= ? AND date_time < ?{id_extra}
            GROUP BY id, frequency, group_
        ) AS ch
        GROUP BY id
        HAVING channel_count > 1
        ORDER BY channel_count DESC, sessions DESC
        LIMIT ?
    """
    params_summary.append(lim_fetch)
    id_summary = conn.execute(summary_sql, tuple(params_summary)).fetchall()
    truncated = len(id_summary) > cap
    id_summary = id_summary[:cap]

    if not id_summary:
        msg = (
            "За этот день нет ID, которые встречались бы более чем на одной паре "
            "«частота + группа»."
        )
        if oid:
            msg += f" (фильтр: ID {oid})."
        return {
            "seanses_table": seans_t,
            "date": raw,
            "day_start_dt": win_start_s,
            "day_end_excl_dt": win_end_excl_s,
            "items": [],
            "multi_channel_id_count": 0,
            "ids_truncated": False,
            "only_id_filter": oid,
            "message": msg,
        }

    ids_list = [
        str(r["id"] if hasattr(r, "keys") else r[0] or "") for r in id_summary
    ]
    summary_map: dict[str, dict[str, int]] = {}
    for r in id_summary:
        iid = str(r["id"] if hasattr(r, "keys") else r[0] or "")
        summary_map[iid] = {
            "sessions": int(r["sessions"] if hasattr(r, "keys") else r[1] or 0),
            "channel_count": int(
                r["channel_count"] if hasattr(r, "keys") else r[2] or 0
            ),
        }

    ph = ",".join("?" * len(ids_list))
    detail_sql = f"""
        SELECT id, frequency, group_, COUNT(*) AS sessions,
               MIN(date_time) AS first_dt, MAX(date_time) AS last_dt
        FROM {seans_q}
        WHERE date_time >= ? AND date_time < ?
          AND id IN ({ph})
        GROUP BY id, frequency, group_
        ORDER BY id, frequency, group_
    """
    drows = conn.execute(
        detail_sql,
        (win_start_s, win_end_excl_s, *ids_list),
    ).fetchall()

    items_map: dict[str, dict[str, Any]] = {}
    for iid in ids_list:
        sm = summary_map.get(iid, {})
        items_map[iid] = {
            "id": iid,
            "sessions": sm.get("sessions", 0),
            "channel_count": sm.get("channel_count", 0),
            "pairs": [],
        }

    for r in drows:
        iid = str(r["id"] if hasattr(r, "keys") else r[0] or "")
        if iid not in items_map:
            continue
        freq = str(r["frequency"] if hasattr(r, "keys") else r[1] or "")
        grp = str(r["group_"] if hasattr(r, "keys") else r[2] or "")
        sess = int(r["sessions"] if hasattr(r, "keys") else r[3] or 0)
        fdt = str(r["first_dt"] if hasattr(r, "keys") else r[4] or "")
        ldt = str(r["last_dt"] if hasattr(r, "keys") else r[5] or "")
        items_map[iid]["pairs"].append(
            {
                "frequency": freq,
                "group_": grp,
                "sessions": sess,
                "first_dt": fdt,
                "last_dt": ldt,
            }
        )

    items = list(items_map.values())
    return {
        "seanses_table": seans_t,
        "date": raw,
        "day_start_dt": win_start_s,
        "day_end_excl_dt": win_end_excl_s,
        "multi_channel_id_count": len(items),
        "items": items,
        "ids_truncated": truncated,
        "only_id_filter": oid,
    }
