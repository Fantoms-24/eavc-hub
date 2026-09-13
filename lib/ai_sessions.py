from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from web_portal.lib.ai_client import AIClientError, current_ai_config, generate_ai_text
from web_portal.lib.ai_prompts import AI_PROMPT_VERSION, AI_SYSTEM_PROMPT
from web_portal.lib.db import create_ai_job, create_ai_report, get_network_intensity_clusters, update_ai_job

_SESSIONS_AI_ROW_LIMIT = 25000


def _norm_ts(value: str) -> str:
    return str(value or "").strip().replace("T", " ")


def _unit_name_sql(alias: str = "s") -> str:
    return f"""
    COALESCE(
      NULLIF((SELECT u.name FROM unit u
              WHERE u.frequency = {alias}.frequency AND u.group_ = {alias}.group_
              ORDER BY u.manual DESC, u.updated_at DESC LIMIT 1), ''),
      NULLIF((SELECT u.name FROM unit u
              WHERE u.frequency = {alias}.frequency AND u.group_ = '*'
              ORDER BY u.manual DESC, u.updated_at DESC LIMIT 1), ''),
      NULLIF((SELECT u.name FROM unit u
              WHERE u.frequency = '*' AND u.group_ = {alias}.group_
              ORDER BY u.manual DESC, u.updated_at DESC LIMIT 1), ''),
      'не указано'
    )
    """


def _extract_requested_ids(question: str) -> set[str]:
    return set(re.findall(r"(?<!\d)(\d{3,10})(?!\d)", str(question or "")))


def _is_duty_query(question: str) -> bool:
    src = str(question or "").lower().replace("ё", "е")
    return any(term in src for term in ("оперативн", "дежурн", "опер деж", "опердеж"))


def _is_activity_query(question: str) -> bool:
    src = str(question or "").lower().replace("ё", "е")
    return any(
        term in src
        for term in (
            "активн",
            "интенсив",
            "топ подраздел",
            "проблемн подраздел",
            "загруженн",
            "всплеск",
            "анomal",
            "аномал",
        )
    )


def _question_for_sessions_period(question: str) -> str:
    """Только формулировка пользователя — без хвоста памяти/контекста для планировщика."""
    q = str(question or "").strip()
    for marker in (
        "\n\nКонтекст предыдущих реплик",
        "\n\nКонтекст диалога",
        "\n\nКонтекст предыдущих",
    ):
        if marker in q:
            q = q.split(marker, 1)[0].strip()
    return q


def _wants_full_sessions_range(question: str) -> bool:
    """Явный запрос смотреть все/ранние периоды, а не только текущие сутки."""
    src = _question_for_sessions_period(question).lower().replace("ё", "е")
    return any(
        x in src
        for x in (
            "ранее период",
            "раньш",
            "ранее",
            "прошл",
            "за все время",
            "за всё время",
            "все сеанс",
            "все период",
            "по всей баз",
            "все смен",
            "когда-либо",
            "когда либо",
            "за весь период",
            "архив",
            "историческ",
            "не только сегодня",
            "не за сегодня",
            "предыдущ",
            "за все дни",
        )
    )


def _has_explicit_sessions_period(question: str) -> bool:
    """Пользователь явно сузил период (сегодня, дата, неделя и т.д.)."""
    src = _question_for_sessions_period(question).lower().replace("ё", "е")
    if any(
        x in src
        for x in (
            "сегодня",
            "вчера",
            "завтра",
            "сутк",
            "24 час",
            "недел",
            "7 д",
            "месяц",
            "30 д",
            "тридц",
        )
    ):
        return True
    if re.search(r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?", _question_for_sessions_period(question)):
        return True
    if re.search(r"\d{4}-\d{2}-\d{2}", _question_for_sessions_period(question)):
        return True
    if re.search(r"\b\d{1,2}\s*[-–]\s*\d{1,2}\b", src):
        return True
    if re.search(r"с\s+\d{1,2}\s*(?:до|по|-)", src):
        return True
    return False


def _sessions_db_bounds(conn, *, position_name: str = "") -> tuple[str, str]:
    """Минимальная и максимальная дата сеансов в БД (активные + архив)."""
    pos = str(position_name or "").strip()
    start_val: str | None = None
    end_val: str | None = None
    tables = ["seanses"]
    if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='seanses_archive'"
    ).fetchone():
        tables.append("seanses_archive")

    for table in tables:
        sql = f"""
            SELECT MIN(date_time), MAX(date_time)
            FROM {table}
            WHERE TRIM(COALESCE(id, '')) <> ''
        """
        params: list[Any] = []
        if pos and pos != "__all__":
            sql += " AND (client_name = ? OR TRIM(COALESCE(client_name,'')) = '')"
            params.append(pos)
        row = conn.execute(sql, params).fetchone()
        if not row or not row[0] or not row[1]:
            continue
        mn, mx = _norm_ts(str(row[0])), _norm_ts(str(row[1]))
        start_val = mn if start_val is None or mn < start_val else start_val
        end_val = mx if end_val is None or mx > end_val else end_val

    if start_val and end_val:
        return start_val, end_val

    if pos and pos != "__all__":
        return _sessions_db_bounds(conn, position_name="__all__")

    now = datetime.now().replace(microsecond=0)
    return (
        (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S"),
        now.strftime("%Y-%m-%d %H:%M:%S"),
    )


def resolve_sessions_period(
    conn,
    *,
    question: str,
    position_name: str = "",
    date_from: str = "",
    date_to: str = "",
) -> tuple[str, str]:
    """
    Период для анализа сеансов.
    Без явной даты в вопросе — все сеансы в базе (активные + архив).
    """
    df = str(date_from or "").strip().replace("T", " ")
    dt = str(date_to or "").strip().replace("T", " ")
    if df and dt:
        start = _norm_ts(df)
        end = _norm_ts(dt)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", start):
            start = f"{start} 00:00:00"
        if re.match(r"^\d{4}-\d{2}-\d{2}$", end):
            end = f"{end} 23:59:59"
        return start, end
    if df and not dt:
        from web_portal.lib.ai_router import _period_from_question

        _, end = _period_from_question(question)
        start = _norm_ts(df)
        if re.match(r"^\d{4}-\d{2}-\d{2}$", start):
            start = f"{start} 00:00:00"
        return start, end

    q = _question_for_sessions_period(question)
    if _wants_full_sessions_range(q):
        return _sessions_db_bounds(conn, position_name=position_name)
    if not _has_explicit_sessions_period(q):
        return _sessions_db_bounds(conn, position_name=position_name)

    from web_portal.lib.ai_router import _period_from_question

    return _period_from_question(q)


def _is_id_network_query(question: str) -> bool:
    src = str(question or "").lower().replace("ё", "е")
    return (
        ("других подраздел" in src or "другом подраздел" in src or "разных подраздел" in src)
        and ("id" in src or "айди" in src or "айдиш" in src)
    )


def _question_focus_tokens(question: str) -> set[str]:
    stop = {
        "какие",
        "какой",
        "когда",
        "были",
        "был",
        "была",
        "других",
        "другом",
        "подразделениях",
        "подразделение",
        "айдишники",
        "айди",
        "сеансы",
        "сегодня",
        "неделя",
        "неделю",
        "месяц",
        "взаимодействовал",
        "покажи",
    }
    tokens = set()
    for token in re.findall(r"(?iu)[а-яёa-z0-9]{3,}", str(question or "").lower()):
        if token not in stop:
            tokens.add(token)
    return tokens


def _row_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("date_time") or ""),
        str(row.get("frequency") or ""),
        str(row.get("group") or ""),
    )


def _unit_key(value: Any) -> str:
    src = str(value or "").strip().lower().replace("ё", "е")
    if not src:
        return "не указано"
    tokens = re.findall(r"(?iu)[а-яa-z0-9]+", src)
    if not tokens:
        return "не указано"
    if set(tokens) <= {"не", "указано", "ну"}:
        return "не указано"

    pairs: list[str] = []
    used: set[int] = set()
    # Сохраняем смысловые пары: "3 бон", "3 брон", "425 ошп", "152 оебр".
    for idx in range(len(tokens) - 1):
        if tokens[idx].isdigit() and re.search(r"(?iu)[а-яa-z]", tokens[idx + 1]):
            pairs.append(f"{tokens[idx]}:{tokens[idx + 1]}")
            used.add(idx)
            used.add(idx + 1)
    rest = [tok for idx, tok in enumerate(tokens) if idx not in used]
    return "|".join(sorted(pairs) + sorted(rest)) or "не указано"


def _choose_unit_display(names: list[str]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for name in names:
        s = str(name or "не указано").strip() or "не указано"
        counts[s] += 1
    if not counts:
        return "не указано"
    return sorted(counts.items(), key=lambda x: (x[1], len(x[0])), reverse=True)[0][0]


def _is_unknown_unit_name(value: Any) -> bool:
    src = str(value or "").strip().lower().replace("ё", "е")
    if not src:
        return True
    tokens = set(re.findall(r"(?iu)[а-яa-z0-9]+", src))
    if not tokens:
        return True
    if tokens <= {"не", "указано", "ну", "н", "у"}:
        return True
    return src.startswith("н/у") or "н/у подразделение" in src


def _sessions_rows(
    conn,
    *,
    start_ts: str,
    end_ts: str,
    position_name: str = "",
    include_archive: bool = True,
) -> list[dict[str, Any]]:
    start = _norm_ts(start_ts)
    end = _norm_ts(end_ts)
    if not start or not end:
        raise ValueError("Укажите начало и конец периода")
    params_base: list[Any] = [start, end]
    pos = str(position_name or "").strip()
    pos_filter = ""
    if pos and pos != "__all__":
        pos_filter = "AND (s.client_name = ? OR TRIM(COALESCE(s.client_name,'')) = '')"
        params_base.append(pos)

    def sql_for(table: str) -> str:
        return f"""
        SELECT
          s.date_time AS date_time,
          s.frequency AS frequency,
          s.group_ AS group_code,
          s.id AS correspondent_id,
          COALESCE(s.client_name, '') AS client_name,
          {_unit_name_sql("s")} AS unit_name
        FROM {table} s
        WHERE s.date_time BETWEEN ? AND ?
          AND TRIM(COALESCE(s.id, '')) <> ''
          {pos_filter}
        """

    sql_parts = [sql_for("seanses")]
    params: list[Any] = [*params_base]
    if include_archive:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='seanses_archive'"
        ).fetchone()
        if exists:
            sql_parts.append(sql_for("seanses_archive"))
            params.extend(params_base)

    rows = conn.execute(
        "\nUNION ALL\n".join(sql_parts) + "\nORDER BY date_time ASC, frequency ASC, group_code ASC",
        params,
    ).fetchall()
    return [
        {
            "date_time": str(r["date_time"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group": str(r["group_code"] or ""),
            "id": str(r["correspondent_id"] or "").strip(),
            "client_name": str(r["client_name"] or ""),
            "unit_name": str(r["unit_name"] or "не указано"),
        }
        for r in rows
    ]


def _sessions_scope_filter(position_name: str = "") -> tuple[str, list[Any]]:
    pos = str(position_name or "").strip()
    if pos and pos != "__all__":
        return "AND (s.client_name = ? OR TRIM(COALESCE(s.client_name,'')) = '')", [pos]
    return "", []


def _sessions_source_tables(conn, *, include_archive: bool = True) -> list[str]:
    tables = ["seanses"]
    if include_archive and conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='seanses_archive'"
    ).fetchone():
        tables.append("seanses_archive")
    return tables


def _count_sessions_rows(
    conn,
    *,
    start_ts: str,
    end_ts: str,
    position_name: str = "",
    include_archive: bool = True,
) -> int:
    start = _norm_ts(start_ts)
    end = _norm_ts(end_ts)
    pos_filter, pos_params = _sessions_scope_filter(position_name)
    total = 0
    for table in _sessions_source_tables(conn, include_archive=include_archive):
        row = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {table} s
            WHERE s.date_time BETWEEN ? AND ?
              AND TRIM(COALESCE(s.id, '')) <> ''
              {pos_filter}
            """,
            [start, end, *pos_params],
        ).fetchone()
        total += int(row[0] or 0) if row else 0
    return total


def _sessions_daily_buckets(
    conn,
    *,
    start_ts: str,
    end_ts: str,
    position_name: str = "",
    include_archive: bool = True,
    limit: int = 400,
) -> list[dict[str, Any]]:
    start = _norm_ts(start_ts)
    end = _norm_ts(end_ts)
    pos_filter, pos_params = _sessions_scope_filter(position_name)
    parts: list[str] = []
    params: list[Any] = []
    for table in _sessions_source_tables(conn, include_archive=include_archive):
        parts.append(
            f"""
            SELECT substr(s.date_time, 1, 10) AS bucket_day,
                   COUNT(*) AS rows_cnt,
                   COUNT(DISTINCT s.date_time || '|' || s.frequency || '|' || s.group_) AS events_cnt
            FROM {table} s
            WHERE s.date_time BETWEEN ? AND ?
              AND TRIM(COALESCE(s.id, '')) <> ''
              {pos_filter}
            GROUP BY bucket_day
            """
        )
        params.extend([start, end, *pos_params])
    sql = f"""
        SELECT bucket_day, SUM(rows_cnt) AS rows_cnt, SUM(events_cnt) AS events_cnt
        FROM ({" UNION ALL ".join(parts)})
        GROUP BY bucket_day
        ORDER BY events_cnt DESC, rows_cnt DESC
        LIMIT ?
    """
    params.append(int(limit))
    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "day": str(r["bucket_day"] or ""),
            "rows_count": int(r["rows_cnt"] or 0),
            "events_count": int(r["events_cnt"] or 0),
        }
        for r in rows
    ]


def _format_spike_activity_summary(
    *,
    start: str,
    end: str,
    row_count: int,
    daily: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    position_scope: str,
) -> str:
    lines = [
        "### Активность и всплески по сеансам (агрегированная сводка)",
        f"Период: **{start}** — **{end}**",
        f"Всего строк сеансов: **{row_count}**"
        + (f" (позиция: {position_scope})" if position_scope and position_scope != "__all__" else ""),
    ]
    if not daily:
        lines.append("\nЗа период нет агрегированной активности по дням.")
        return "\n".join(lines)

    avg_events = sum(int(d.get("events_count") or 0) for d in daily) / max(len(daily), 1)
    spike_days = [
        d for d in daily if int(d.get("events_count") or 0) >= max(avg_events * 1.35, avg_events + 3)
    ][:12]
    if not spike_days:
        spike_days = daily[:8]

    lines.append("\n#### Дни с повышенной активностью (всплески)")
    for idx, day in enumerate(spike_days, start=1):
        lines.append(
            f"{idx}. **{day.get('day') or 'н/у'}**: "
            f"уникальных сеансов {day.get('events_count')}, выходов {day.get('rows_count')}."
        )
    if avg_events > 0:
        lines.append(
            f"\nСредняя активность: ~{avg_events:.1f} уникальных сеансов в день "
            f"(по {len(daily)} дням с данными)."
        )

    if clusters:
        lines.append("\n#### Самые активные подразделения за период")
        for idx, row in enumerate(clusters[:12], start=1):
            lines.append(
                f"{idx}. **{row.get('unit_name') or 'не указано'}**: "
                f"сеансов {row.get('sessions')}, ID {row.get('correspondents')}."
            )
    return "\n".join(lines)


def _build_sessions_findings(rows: list[dict[str, Any]], *, question: str = "") -> dict[str, Any]:
    requested_ids = _extract_requested_ids(question)
    focus_tokens = _question_focus_tokens(question)
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_event: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        by_id[cid].append(row)
        by_event[_row_key(row)].append(row)
    known_units_by_id: dict[str, set[str]] = {
        cid: {
            _unit_key(x.get("unit_name"))
            for x in items
            if not _is_unknown_unit_name(x.get("unit_name"))
        }
        for cid, items in by_id.items()
    }
    known_units_display_by_id: dict[str, set[str]] = {
        cid: {
            str(x.get("unit_name") or "не указано")
            for x in items
            if not _is_unknown_unit_name(x.get("unit_name"))
        }
        for cid, items in by_id.items()
    }

    candidates: list[dict[str, Any]] = []
    for cid, items in by_id.items():
        if requested_ids and cid not in requested_ids:
            continue
        units = sorted(
            {
                str(x.get("unit_name") or "не указано")
                for x in items
                if not _is_unknown_unit_name(x.get("unit_name"))
            }
        )
        channels = sorted({f"{x.get('frequency')} / {x.get('group')}" for x in items})
        if len(units) < 2 and not requested_ids:
            continue
        peers: dict[str, dict[str, Any]] = {}
        appearances: list[dict[str, Any]] = []
        cross_appearances: list[dict[str, Any]] = []
        cross_peer_units: set[str] = set()
        for item in items:
            same_event = by_event.get(_row_key(item), [])
            current_unit = _unit_key(item.get("unit_name"))
            if _is_unknown_unit_name(item.get("unit_name")):
                continue
            peer_rows = [
                x
                for x in same_event
                if str(x.get("id") or "") and str(x.get("id") or "") != cid
            ]
            cross_peer_rows = [
                x
                for x in peer_rows
                if any(
                    unit != current_unit
                    for unit in known_units_by_id.get(str(x.get("id") or ""), set())
                    if unit and unit != "не указано"
                )
            ]
            peer_ids = sorted({str(x.get("id") or "") for x in peer_rows})
            cross_peer_ids = sorted({str(x.get("id") or "") for x in cross_peer_rows})
            all_event_ids = sorted({str(x.get("id") or "") for x in same_event if str(x.get("id") or "")})
            peer_units = sorted(
                {
                    unit
                    for x in cross_peer_rows
                    for unit in known_units_display_by_id.get(str(x.get("id") or ""), set())
                    if _unit_key(unit) != current_unit and not _is_unknown_unit_name(unit)
                }
            )
            for unit in peer_units:
                cross_peer_units.add(unit)
            appearances.append(
                {
                    "date_time": item.get("date_time"),
                    "unit_name": item.get("unit_name"),
                    "frequency": item.get("frequency"),
                    "group": item.get("group"),
                    "peers": peer_ids[:20],
                }
            )
            if cross_peer_ids:
                cross_appearances.append(
                    {
                        "date_time": item.get("date_time"),
                        "unit_name": item.get("unit_name"),
                        "frequency": item.get("frequency"),
                        "group": item.get("group"),
                        "cross_peers": cross_peer_ids[:30],
                        "cross_peer_units": peer_units[:12],
                        "all_ids": all_event_ids[:50],
                    }
                )
            for peer in cross_peer_rows:
                peer_id = str(peer.get("id") or "")
                p = peers.setdefault(
                    peer_id,
                    {"id": peer_id, "count": 0, "last_seen": "", "units": set(), "examples": []},
                )
                p["count"] += 1
                p["last_seen"] = max(str(p.get("last_seen") or ""), str(item.get("date_time") or ""))
                for unit in known_units_display_by_id.get(peer_id, set()):
                    if _unit_key(unit) != current_unit:
                        p["units"].add(str(unit or "не указано"))
                if len(p["examples"]) < 5:
                    p["examples"].append(
                        {
                            "date_time": item.get("date_time"),
                            "unit_name": peer.get("unit_name"),
                            "frequency": item.get("frequency"),
                            "group": item.get("group"),
                        }
                    )
        if not cross_appearances and not requested_ids:
            continue
        candidates.append(
            {
                "id": cid,
                "total_sessions": len(items),
                "units": units,
                "channels": channels,
                "first_seen": min(str(x.get("date_time") or "") for x in items),
                "last_seen": max(str(x.get("date_time") or "") for x in items),
                "appearances": appearances[:80],
                "cross_appearances": cross_appearances[:80],
                "cross_peer_units": sorted(cross_peer_units),
                "peers": sorted(
                    (
                        {
                            **p,
                            "units": sorted(p.get("units") or []),
                        }
                        for p in peers.values()
                    ),
                    key=lambda x: (int(x.get("count") or 0), str(x.get("last_seen") or "")),
                    reverse=True,
                )[:30],
            }
        )

    candidates.sort(
        key=lambda x: (len(x.get("units") or []), int(x.get("total_sessions") or 0), str(x.get("last_seen") or "")),
        reverse=True,
    )
    if focus_tokens and not requested_ids:
        focused = [
            item
            for item in candidates
            if any(
                any(token in str(unit or "").lower() for token in focus_tokens)
                for unit in (item.get("units") or [])
            )
        ]
        if focused:
            candidates = focused
    return {
        "requested_ids": sorted(requested_ids),
        "focus_tokens": sorted(focus_tokens),
        "total_rows": len(rows),
        "unique_ids": len(by_id),
        "cross_unit_ids": candidates[:80],
    }


def _format_findings_for_prompt(findings: dict[str, Any]) -> str:
    ids = findings.get("cross_unit_ids") if isinstance(findings.get("cross_unit_ids"), list) else []
    lines = [
        "Детерминированная проверка сеансов:",
        f"- Всего строк сеансов в периоде: {findings.get('total_rows')}",
        f"- Уникальных ID: {findings.get('unique_ids')}",
        f"- ID, найденные в нескольких подразделениях или запрошенные пользователем: {len(ids)}",
    ]
    requested = findings.get("requested_ids") if isinstance(findings.get("requested_ids"), list) else []
    if requested:
        lines.append(f"- Запрошенные ID: {', '.join(requested)}")
    for item in ids[:30]:
        lines.append(
            f"\nID {item.get('id')}: сеансов {item.get('total_sessions')}; "
            f"первый раз {item.get('first_seen')}; последний раз {item.get('last_seen')}"
        )
        lines.append(f"- Подразделения: {', '.join(item.get('units') or [])}")
        if item.get("cross_peer_units"):
            lines.append(f"- Другие подразделения рядом в сеансах: {', '.join(item.get('cross_peer_units') or [])}")
        lines.append(f"- Каналы: {', '.join((item.get('channels') or [])[:12])}")
        lines.append("- Межподразделенческие появления:")
        cross_apps = item.get("cross_appearances") if isinstance(item.get("cross_appearances"), list) else []
        for app in cross_apps[:14]:
            peers = ", ".join(app.get("cross_peers") or []) or "нет ID из других подразделений"
            peer_units = ", ".join(app.get("cross_peer_units") or []) or "не указано"
            all_ids = ", ".join(app.get("all_ids") or []) or "не указано"
            lines.append(
                f"  * {app.get('date_time')} | {app.get('unit_name')} | "
                f"{app.get('frequency')} / {app.get('group')} | другие подразделения: {peer_units} | "
                f"ID из других подразделений: {peers} | все ID в сеансе: {all_ids}"
            )
        if not cross_apps:
            lines.append("  * Межподразделенческих появлений не найдено.")
        peers = item.get("peers") or []
        if peers:
            lines.append("- Частые межподразделенческие взаимодействия / одновременные появления:")
            for peer in peers[:10]:
                lines.append(
                    f"  * ID {peer.get('id')}: вместе {peer.get('count')} раз; "
                    f"подразделения: {', '.join(peer.get('units') or [])}; последний раз: {peer.get('last_seen')}"
                )
    return "\n".join(lines)


def _format_cross_unit_summary(findings: dict[str, Any]) -> str:
    ids = findings.get("cross_unit_ids") if isinstance(findings.get("cross_unit_ids"), list) else []
    lines = ["### Обязательная сводка межподразделенческих взаимодействий"]
    if not ids:
        lines.append("Межподразделенческие взаимодействия за выбранный период не найдены.")
        return "\n".join(lines)

    lines.append("Показаны только связи между реально привязанными разными подразделениями. `Не указано` исключено из расчета.")
    links: dict[tuple[str, str], dict[str, Any]] = {}
    for item in ids:
        cid = str(item.get("id") or "")
        own_units = [u for u in (item.get("units") or []) if not _is_unknown_unit_name(u)]
        own_unit = own_units[0] if own_units else ""
        if not cid or not own_unit:
            continue
        peers = item.get("peers") if isinstance(item.get("peers"), list) else []
        for peer in peers[:12]:
            peer_id = str(peer.get("id") or "")
            peer_units = [u for u in (peer.get("units") or []) if not _is_unknown_unit_name(u)]
            if not peer_id or not peer_units:
                continue
            pair_key = tuple(sorted([cid, peer_id]))
            examples = peer.get("examples") if isinstance(peer.get("examples"), list) else []
            ex = examples[0] if examples else {}
            link = links.setdefault(
                pair_key,
                {
                    "left_id": cid,
                    "left_unit": own_unit,
                    "right_id": peer_id,
                    "right_unit": peer_units[0],
                    "count": 0,
                    "last_seen": "",
                    "channels": set(),
                    "examples": [],
                },
            )
            link["count"] = max(int(link.get("count") or 0), int(peer.get("count") or 0))
            link["last_seen"] = max(str(link.get("last_seen") or ""), str(peer.get("last_seen") or ""))
            for ex_item in examples[:3]:
                channel = f"{ex_item.get('frequency') or 'н/у'} / {ex_item.get('group') or 'н/у'}"
                link["channels"].add(channel)
                if len(link["examples"]) < 3:
                    link["examples"].append(
                        f"{ex_item.get('date_time') or 'н/у'} {channel}"
                    )
            if ex and not link["channels"]:
                link["channels"].add(f"{ex.get('frequency') or 'н/у'} / {ex.get('group') or 'н/у'}")

    rows = sorted(
        links.values(),
        key=lambda x: (int(x.get("count") or 0), str(x.get("last_seen") or "")),
        reverse=True,
    )
    if not rows:
        lines.append("Подтвержденных связей между разными привязанными подразделениями не найдено.")
        return "\n".join(lines)

    for idx, row in enumerate(rows[:20], start=1):
        channels = ", ".join(sorted(row.get("channels") or [])[:3]) or "не указано"
        examples = "; ".join(row.get("examples") or []) or "нет примеров"
        lines.append(
            f"\n{idx}. **ID {row.get('left_id')}** ({row.get('left_unit')}) ↔ "
            f"**ID {row.get('right_id')}** ({row.get('right_unit')})\n"
            f"- Совместных появлений: {row.get('count')}.\n"
            f"- Последний контакт: {row.get('last_seen') or 'н/у'}.\n"
            f"- Каналы: {channels}.\n"
            f"- Примеры: {examples}."
        )
    return "\n".join(lines)


def _build_id_network_findings(rows: list[dict[str, Any]], *, top_n: int = 30) -> dict[str, Any]:
    by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_event: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        by_id[cid].append(row)
        by_event[_row_key(row)].append(row)

    out: list[dict[str, Any]] = []
    for cid, items in by_id.items():
        known_units: dict[str, str] = {}
        unknown_channels: set[str] = set()
        event_examples: list[dict[str, Any]] = []
        for item in items:
            unit_name = str(item.get("unit_name") or "не указано")
            channel = f"{item.get('frequency') or 'не указано'} / {item.get('group') or 'не указано'}"
            if _is_unknown_unit_name(unit_name):
                unknown_channels.add(channel)
            else:
                known_units.setdefault(_unit_key(unit_name), unit_name)
            same_event = by_event.get(_row_key(item), [])
            event_examples.append(
                {
                    "date_time": str(item.get("date_time") or ""),
                    "unit_name": unit_name,
                    "frequency": str(item.get("frequency") or ""),
                    "group": str(item.get("group") or ""),
                    "all_ids": sorted({str(x.get("id") or "") for x in same_event if str(x.get("id") or "")}),
                    "unknown": _is_unknown_unit_name(unit_name),
                }
            )

        known_count = len(known_units)
        has_unknown = bool(unknown_channels)
        if known_count < 2 and not (known_count >= 1 and has_unknown):
            continue
        event_examples.sort(key=lambda x: str(x.get("date_time") or ""), reverse=True)
        status = (
            "разные привязанные подразделения"
            if known_count >= 2
            else "привязанное подразделение + непривязанная сеть"
        )
        out.append(
            {
                "id": cid,
                "status": status,
                "known_units": sorted(known_units.values()),
                "unknown_channels": sorted(unknown_channels),
                "total_rows": len(items),
                "first_seen": min(str(x.get("date_time") or "") for x in items),
                "last_seen": max(str(x.get("date_time") or "") for x in items),
                "examples": event_examples[:8],
            }
        )

    out.sort(
        key=lambda x: (
            1 if x.get("status") == "разные привязанные подразделения" else 0,
            int(x.get("total_rows") or 0),
            str(x.get("last_seen") or ""),
        ),
        reverse=True,
    )
    return {"ids": out[:top_n], "total_candidates": len(out)}


def _format_id_network_summary(findings: dict[str, Any]) -> str:
    ids = findings.get("ids") if isinstance(findings.get("ids"), list) else []
    lines = ["### ID в других подразделениях / сетях"]
    if not ids:
        lines.append("За выбранный период ID, которые выходили в разных подразделениях или в привязанной и непривязанной сети, не найдены.")
        return "\n".join(lines)
    lines.append(
        "Показываю ID, которые появлялись в разных привязанных подразделениях или дополнительно выходили в сетях без привязки подразделения."
    )
    for idx, item in enumerate(ids[:15], start=1):
        examples = item.get("examples") if isinstance(item.get("examples"), list) else []
        lines.append(
            f"\n{idx}. **ID {item.get('id')}** — {item.get('status')}; выходов: {item.get('total_rows')}."
        )
        lines.append(f"- Подразделения: {', '.join(item.get('known_units') or []) or 'нет привязанных'}.")
        if item.get("unknown_channels"):
            lines.append(f"- Непривязанные сети: {', '.join((item.get('unknown_channels') or [])[:5])}.")
        lines.append(f"- Период: {item.get('first_seen') or 'н/у'} — {item.get('last_seen') or 'н/у'}.")
        lines.append("- Последние появления:")
        for ex in examples[:4]:
            marker = "непривязанная сеть" if ex.get("unknown") else str(ex.get("unit_name") or "подразделение н/у")
            lines.append(
                f"  - {ex.get('date_time') or 'н/у'} | {ex.get('frequency') or 'н/у'} / {ex.get('group') or 'н/у'} | "
                f"{marker} | все ID в сеансе: {', '.join(ex.get('all_ids') or []) or 'не указано'}."
            )
    return "\n".join(lines)


def _build_duty_findings(rows: list[dict[str, Any]], *, top_n: int = 5) -> dict[str, Any]:
    units: dict[str, dict[str, Any]] = {}
    unknown_rows = 0
    for row in rows:
        cid = str(row.get("id") or "").strip()
        if not cid:
            continue
        if _is_unknown_unit_name(row.get("unit_name")):
            unknown_rows += 1
            continue
        unit_key = _unit_key(row.get("unit_name"))
        unit = units.setdefault(
            unit_key,
            {
                "unit_key": unit_key,
                "unit_names": [],
                "ids": {},
                "total_rows": 0,
                "channels": set(),
            },
        )
        unit["unit_names"].append(str(row.get("unit_name") or "не указано"))
        unit["total_rows"] += 1
        unit["channels"].add(f"{row.get('frequency') or 'не указано'} / {row.get('group') or 'не указано'}")
        item = unit["ids"].setdefault(
            cid,
            {
                "id": cid,
                "appearances": 0,
                "events": set(),
                "channels": set(),
                "first_seen": "",
                "last_seen": "",
                "examples": [],
            },
        )
        item["appearances"] += 1
        item["events"].add(_row_key(row))
        item["channels"].add(f"{row.get('frequency') or 'не указано'} / {row.get('group') or 'не указано'}")
        ts = str(row.get("date_time") or "")
        if ts:
            item["first_seen"] = min(str(item["first_seen"] or ts), ts)
            item["last_seen"] = max(str(item["last_seen"] or ts), ts)
        if len(item["examples"]) < 5:
            item["examples"].append(
                {
                    "date_time": ts,
                    "frequency": str(row.get("frequency") or ""),
                    "group": str(row.get("group") or ""),
                }
            )

    out_units: list[dict[str, Any]] = []
    for unit in units.values():
        id_items = []
        for item in unit["ids"].values():
            id_items.append(
                {
                    **item,
                    "events_count": len(item.get("events") or []),
                    "events": [],
                    "channels": sorted(item.get("channels") or []),
                }
            )
        id_items.sort(
            key=lambda x: (
                int(x.get("appearances") or 0),
                int(x.get("events_count") or 0),
                str(x.get("last_seen") or ""),
            ),
            reverse=True,
        )
        out_units.append(
            {
                "unit_name": _choose_unit_display(unit.get("unit_names") or []),
                "total_rows": int(unit.get("total_rows") or 0),
                "channels": sorted(unit.get("channels") or []),
                "top_ids": id_items[:top_n],
            }
        )
    out_units.sort(key=lambda x: int(x.get("total_rows") or 0), reverse=True)
    return {"units": out_units, "unknown_rows": unknown_rows}


def _format_duty_summary(findings: dict[str, Any]) -> str:
    units = findings.get("units") if isinstance(findings.get("units"), list) else []
    lines = ["### Оперативные дежурные по подразделениям"]
    if not units:
        lines.append("За выбранный период не найдено сеансов для определения оперативных дежурных.")
        return "\n".join(lines)
    lines.append(
        "Кандидат в оперативные дежурные = ID с наибольшим числом выходов в подразделении за выбранный период."
    )
    for idx_unit, unit in enumerate(units[:12], start=1):
        top_ids = unit.get("top_ids") if isinstance(unit.get("top_ids"), list) else []
        if not top_ids:
            continue
        main = top_ids[0]
        backups = top_ids[1:3]
        backup_text = ", ".join(
            f"ID {item.get('id')} ({item.get('appearances')} выходов)"
            for item in backups
            if item.get("id")
        )
        unit_channels = ", ".join((unit.get("channels") or [])[:3]) or "не указано"
        main_channels = ", ".join((main.get("channels") or [])[:3]) or unit_channels
        lines.append(
            f"\n{idx_unit}. **{unit.get('unit_name')}**\n"
            f"- Основной кандидат: **ID {main.get('id')}** — {main.get('appearances')} выходов, "
            f"{main.get('events_count')} уникальных сеансов.\n"
            f"- Период активности: {main.get('first_seen') or 'н/у'} — {main.get('last_seen') or 'н/у'}.\n"
            f"- Каналы: {main_channels}.\n"
            f"- Запасные кандидаты: {backup_text or 'нет'}.\n"
            f"- Всего по подразделению: {unit.get('total_rows')} выходов; основные каналы: {unit_channels}."
        )
    skipped = int(findings.get("unknown_rows") or 0)
    if skipped:
        lines.append(
            f"\nПримечание: {skipped} выходов без привязанного подразделения скрыты, "
            "чтобы не смешивать разные сети в одном блоке."
        )
    return "\n".join(lines)


def _build_unit_activity_findings(rows: list[dict[str, Any]], *, top_n: int = 20) -> dict[str, Any]:
    units: dict[str, dict[str, Any]] = {}
    unknown_rows = 0
    for row in rows:
        if _is_unknown_unit_name(row.get("unit_name")):
            unknown_rows += 1
            continue
        unit_key = _unit_key(row.get("unit_name"))
        unit = units.setdefault(
            unit_key,
            {
                "unit_key": unit_key,
                "unit_names": [],
                "rows_count": 0,
                "events": set(),
                "ids": set(),
                "id_counts": defaultdict(int),
                "id_channels": defaultdict(set),
                "channels": set(),
                "first_seen": "",
                "last_seen": "",
            },
        )
        unit["unit_names"].append(str(row.get("unit_name") or "не указано"))
        unit["rows_count"] += 1
        unit["events"].add(_row_key(row))
        if row.get("id"):
            cid = str(row.get("id") or "").strip()
            unit["ids"].add(cid)
            unit["id_counts"][cid] += 1
            unit["id_channels"][cid].add(
                f"{row.get('frequency') or 'не указано'} / {row.get('group') or 'не указано'}"
            )
        unit["channels"].add(f"{row.get('frequency') or 'не указано'} / {row.get('group') or 'не указано'}")
        ts = str(row.get("date_time") or "")
        if ts:
            unit["first_seen"] = min(str(unit["first_seen"] or ts), ts)
            unit["last_seen"] = max(str(unit["last_seen"] or ts), ts)

    out: list[dict[str, Any]] = []
    for unit in units.values():
        id_counts = unit.get("id_counts") or {}
        top_ids = [
            {
                "id": cid,
                "count": int(cnt or 0),
                "channels": sorted((unit.get("id_channels") or {}).get(cid) or []),
            }
            for cid, cnt in sorted(id_counts.items(), key=lambda x: (-int(x[1] or 0), str(x[0])))[:12]
        ]
        out.append(
            {
                "unit_name": _choose_unit_display(unit.get("unit_names") or []),
                "rows_count": int(unit.get("rows_count") or 0),
                "events_count": len(unit.get("events") or []),
                "ids_count": len(unit.get("ids") or []),
                "top_ids": top_ids,
                "channels": sorted(unit.get("channels") or []),
                "first_seen": str(unit.get("first_seen") or ""),
                "last_seen": str(unit.get("last_seen") or ""),
            }
        )
    out.sort(
        key=lambda x: (
            int(x.get("events_count") or 0),
            int(x.get("rows_count") or 0),
            int(x.get("ids_count") or 0),
            str(x.get("last_seen") or ""),
        ),
        reverse=True,
    )
    return {"units": out[:top_n], "unknown_rows": unknown_rows}


def _format_unit_activity_summary(findings: dict[str, Any]) -> str:
    units = findings.get("units") if isinstance(findings.get("units"), list) else []
    lines = ["### Активность подразделений по сеансам"]
    if not units:
        lines.append("За выбранный период активность подразделений не найдена.")
        return "\n".join(lines)
    for idx, unit in enumerate(units, start=1):
        top_ids = unit.get("top_ids") if isinstance(unit.get("top_ids"), list) else []
        ids_text = ", ".join(
            f"{item.get('id')} ({item.get('count')})" for item in top_ids[:10] if item.get("id")
        )
        lines.append(
            f"{idx}. **{unit.get('unit_name') or 'не указано'}**: "
            f"уникальных сеансов {unit.get('events_count')}, выходов {unit.get('rows_count')}, "
            f"ID {unit.get('ids_count')}, топ ID: {ids_text or 'не указано'}, "
            f"период {unit.get('first_seen') or 'н/у'} - {unit.get('last_seen') or 'н/у'}, "
            f"каналы: {', '.join((unit.get('channels') or [])[:8]) or 'не указано'}."
        )
    skipped = int(findings.get("unknown_rows") or 0)
    if skipped:
        lines.append(f"\nПримечание: строки без привязанного подразделения не включены в топ ({skipped} выходов), чтобы не смешивать разные сети.")
    return "\n".join(lines)


def _build_sessions_ai_prompt(*, question: str, start_ts: str, end_ts: str, findings_text: str) -> str:
    return f"""
Ты аналитический AI-модуль вкладки "Сеансы". Ответь на вопрос оператора по данным сеансов.

Вопрос оператора:
{question or "Покажи ID, которые встречались в нескольких подразделениях, и их взаимодействия."}

Период: {start_ts} — {end_ts}

Правила:
- Работай только по детерминированной проверке ниже.
- Не выдумывай ID, подразделения, частоты, группы и даты.
- Если ID встречался в нескольких подразделениях, прямо покажи где и когда.
- "Взаимодействовал" трактуй как одновременное появление других ID в том же сеансе: одинаковые дата/время + частота + группа.
- Для вопроса про "другие подразделения" НЕ считай взаимодействием пару, где оба ID относятся к одному и тому же подразделению.
- В каждом важном пункте указывай дату/время, частоту, группу и все ID, которые участвовали в этом сеансе.
- Не заменяй конкретную сводку общими словами. Если есть строки в "Обязательной сводке", перенеси их смысл в ответ.
- Если вопрос про оперативных дежурных, используй определение: оперативные дежурные — ID с наибольшим количеством выходов в сеансах подразделения за период.
- Для оперативных дежурных обязательно укажи подразделение, ID, количество выходов, первый/последний выход и каналы.
- Если по ID нет пересечений или соседних ID, так и напиши.

Формат:
1. Краткий итог.
2. ID в других подразделениях.
3. С кем взаимодействовал и когда.
4. Что проверить аналитику.

{findings_text}
""".strip()


def run_sessions_ai_analysis(
    conn,
    *,
    position_name: str,
    start_ts: str,
    end_ts: str,
    question: str,
    created_by: str = "",
    job_id: int | None = None,
) -> dict[str, Any]:
    cfg = current_ai_config()
    start = _norm_ts(start_ts)
    end = _norm_ts(end_ts)
    params = {"start": start, "end": end, "question": str(question or "").strip()}
    if job_id is None:
        job_id = create_ai_job(
            conn,
            task_type="sessions_ai_analysis",
            position_name=position_name,
            params=params,
            model_name=cfg.model,
            prompt_version=AI_PROMPT_VERSION,
            created_by=created_by,
        )
    update_ai_job(conn, job_id, status="running")
    try:
        row_count = _count_sessions_rows(
            conn, start_ts=start, end_ts=end, position_name=position_name
        )
        position_scope = position_name
        if row_count == 0:
            raise ValueError(
                f"В базе нет сеансов за период {start} — {end} "
                f"(позиция: {position_name or 'все'}). "
                "Проверьте импорт сеансов и выбранную позицию."
            )

        is_duty = _is_duty_query(question)
        is_activity = _is_activity_query(question)
        use_aggregated = is_activity or row_count > _SESSIONS_AI_ROW_LIMIT

        if use_aggregated:
            daily = _sessions_daily_buckets(
                conn,
                start_ts=start,
                end_ts=end,
                position_name=position_scope if position_scope != "__all__" else "",
            )
            clusters = get_network_intensity_clusters(
                conn,
                start_dt=start,
                end_dt=end,
                position_name=None if position_scope == "__all__" else str(position_scope or ""),
            )
            deterministic_summary = _format_spike_activity_summary(
                start=start,
                end=end,
                row_count=row_count,
                daily=daily,
                clusters=clusters,
                position_scope=str(position_scope or ""),
            )
            findings_text = deterministic_summary
            findings = {"mode": "aggregated", "total_rows": row_count, "daily_top": daily[:20]}
            duty_findings: dict[str, Any] = {}
            activity_findings: dict[str, Any] = {"daily": daily[:30], "clusters": clusters[:20]}
            ai_comment = ""
            try:
                prompt = _build_sessions_ai_prompt(
                    question=question,
                    start_ts=start,
                    end_ts=end,
                    findings_text=findings_text[:10000],
                )
                ai_comment = generate_ai_text(
                    system_prompt=AI_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    temperature=0.2,
                    max_tokens=900,
                )["text"]
            except AIClientError:
                ai_comment = ""
            if ai_comment and "обязательная сводка" not in ai_comment.lower():
                text = f"{deterministic_summary}\n\n### AI-комментарий\n{ai_comment}"
            else:
                text = deterministic_summary
                if not ai_comment:
                    text += (
                        "\n\n### Примечание\n"
                        "Период большой — показана агрегированная сводка по всплескам без полной детализации. "
                        "Если AI-комментарий не добавлен, проверьте доступность модели "
                        "(Ollama/endpoint) или увеличьте `WEB_PORTAL_AI_TIMEOUT_SEC`."
                    )
        else:
            rows = _sessions_rows(
                conn, start_ts=start, end_ts=end, position_name=position_scope
            )
            findings = _build_sessions_findings(rows, question=question)
            duty_findings = _build_duty_findings(rows)
            activity_findings = _build_unit_activity_findings(rows)
            findings_text = _format_findings_for_prompt(findings)
            if is_activity:
                deterministic_summary = _format_unit_activity_summary(activity_findings)
            elif _is_id_network_query(question):
                deterministic_summary = _format_id_network_summary(_build_id_network_findings(rows))
            elif is_duty:
                deterministic_summary = _format_duty_summary(duty_findings)
            else:
                deterministic_summary = _format_cross_unit_summary(findings)
            prompt = _build_sessions_ai_prompt(
                question=question,
                start_ts=start,
                end_ts=end,
                findings_text=f"{deterministic_summary}\n\n{findings_text}",
            )
            try:
                text = generate_ai_text(
                    system_prompt=AI_SYSTEM_PROMPT,
                    user_prompt=prompt,
                    temperature=0.2,
                    max_tokens=2200,
                )["text"]
            except AIClientError as exc:
                text = (
                    f"{deterministic_summary}\n\n### Примечание\n"
                    f"AI-комментарий недоступен ({exc}). Показана детерминированная сводка по сеансам."
                )
            if "обязательная сводка" not in text.lower() and deterministic_summary:
                text = f"{deterministic_summary}\n\n### AI-комментарий\n{text}"
        result = {
            "start": start,
            "end": end,
            "rows_count": row_count,
            "position_scope": position_scope,
            "aggregated": use_aggregated,
            "findings": findings,
            "duty_findings": duty_findings,
            "activity_findings": activity_findings,
            "report_text": text,
        }
        report_id = create_ai_report(
            conn,
            job_id=job_id,
            report_type="sessions_ai_analysis",
            position_name=position_name,
            title=f"AI-анализ сеансов {start} — {end}",
            input_summary=f"Период {start} — {end}, строк: {row_count}",
            report_text=text,
            result=result,
            model_name=cfg.model,
            prompt_version=AI_PROMPT_VERSION,
            created_by=created_by,
        )
        result["report_id"] = report_id
        update_ai_job(conn, job_id, status="completed", result=result)
        return {"job_id": job_id, "report_id": report_id, "report_text": text, "result": result}
    except Exception as exc:
        update_ai_job(conn, job_id, status="failed", error_text=str(exc))
        raise
