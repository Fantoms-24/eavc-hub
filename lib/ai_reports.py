from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import json
import hashlib
from typing import Any

from web_portal.lib.ai_client import generate_ai_text, current_ai_config
from web_portal.app_perf import perf_span
from web_portal.lib.ai_prompts import (
    AI_PROMPT_VERSION,
    AI_SYSTEM_PROMPT,
    build_period_report_prompt,
    build_reduce_prompt,
    build_shift_summary_prompt,
)
from web_portal.lib.db import (
    create_ai_job,
    create_ai_report,
    get_intercept_session,
    list_intercept_callsigns,
    list_intercept_items_for_session,
    update_ai_job,
)


MAX_DIRECT_CHARS = 18000
CHUNK_CHARS = 9000


def _report_cache_key(report_type: str, *, position_name: str, params: dict[str, Any], model: str) -> str:
    parts = [str(report_type or ""), str(position_name or ""), str(model or ""), AI_PROMPT_VERSION]
    for key in sorted(params):
        parts.append(f"{key}={str(params.get(key) or '').strip()}")
    return "|".join(parts)


def _rows_fingerprint(rows: list[dict[str, Any]]) -> str:
    digest = hashlib.sha1()
    digest.update(str(len(rows)).encode("utf-8"))
    for row in rows:
        digest.update(str(row.get("session_id") or "").encode("utf-8", errors="ignore"))
        digest.update(str(row.get("updated_at") or "").encode("utf-8", errors="ignore"))
        digest.update(str(row.get("content") or "").encode("utf-8", errors="ignore"))
    return digest.hexdigest()


def _cached_ai_report(conn, *, report_type: str, position_name: str, cache_key: str) -> dict[str, Any] | None:
    rows = conn.execute(
        """
        SELECT id, report_text, result_json
        FROM ai_reports
        WHERE report_type=? AND position_name=? AND prompt_version=?
        ORDER BY id DESC
        LIMIT 50
        """,
        (str(report_type or ""), str(position_name or ""), AI_PROMPT_VERSION),
    ).fetchall()
    for row in rows:
        try:
            result = json.loads(str(row["result_json"] or "{}"))
        except Exception:
            result = {}
        if isinstance(result, dict) and result.get("cache_key") == cache_key:
            return {
                "report_id": int(row["id"]),
                "report_text": str(row["report_text"] or ""),
                "result": result,
            }
    return None


def _norm_ts(value: str) -> str:
    return str(value or "").strip().replace("T", " ")


def _clip(value: str, limit: int) -> str:
    text = str(value or "")
    return text if len(text) <= limit else text[:limit] + "\n...[обрезано]"


def _item_block(row: dict[str, Any]) -> str:
    header = " | ".join(
        x
        for x in [
            f"позиция: {row.get('position_name')}" if row.get("position_name") else "",
            f"смена: {row.get('session_id')}" if row.get("session_id") else "",
            f"подразделение: {row.get('unit_name')}" if row.get("unit_name") else "",
            f"частота: {row.get('frequency')}" if row.get("frequency") else "",
            f"группа: {row.get('group_code')}" if row.get("group_code") else "",
            f"обновлено: {row.get('updated_at')}" if row.get("updated_at") else "",
        ]
        if x
    )
    callsigns = row.get("callsigns")
    callsign_note = ""
    if isinstance(callsigns, list) and callsigns:
        callsign_note = "\nПозывные в бланке: " + "; ".join(str(x) for x in callsigns[:30])
    return f"[{header}{callsign_note}]\n{str(row.get('content') or '').strip()}".strip()


def _format_items(rows: list[dict[str, Any]]) -> str:
    blocks = [_item_block(r) for r in rows if str(r.get("content") or "").strip()]
    return "\n\n---\n\n".join(blocks)


def _callsign_scope_score(row: dict[str, Any], cs: dict[str, Any]) -> int:
    score = 0
    if str(cs.get("frequency") or "").strip() and str(cs.get("frequency") or "").strip() == str(row.get("frequency") or "").strip():
        score += 4
    if str(cs.get("group_code") or "").strip() and str(cs.get("group_code") or "").strip() == str(row.get("group_code") or "").strip():
        score += 4
    if str(cs.get("unit_name") or "").strip() and str(cs.get("unit_name") or "").strip() == str(row.get("unit_name") or "").strip():
        score += 2
    return score


def _build_callsign_lookup(callsigns: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    lookup: dict[str, list[dict[str, Any]]] = {}
    for cs in callsigns or []:
        code = re.sub(r"\D+", "", str(cs.get("code") or ""))
        label = str(cs.get("label") or "").strip()
        if not code or not label:
            continue
        lookup.setdefault(code, []).append(cs)
    return lookup


def _resolve_callsign(row: dict[str, Any], code: str, lookup: dict[str, list[dict[str, Any]]]) -> dict[str, Any] | None:
    variants = lookup.get(re.sub(r"\D+", "", str(code or ""))) or []
    if not variants:
        return None
    return sorted(variants, key=lambda cs: _callsign_scope_score(row, cs), reverse=True)[0]


def _decorate_callsigns_in_content(
    row: dict[str, Any], lookup: dict[str, list[dict[str, Any]]]
) -> tuple[str, list[str]]:
    content = str(row.get("content") or "")
    if not content or not lookup:
        return content, []
    seen: dict[str, str] = {}

    def repl(match: re.Match) -> str:
        code = match.group(1)
        cs = _resolve_callsign(row, code, lookup)
        if not cs:
            return match.group(0)
        label = str(cs.get("label") or "").strip()
        tag = str(cs.get("tag") or "").strip()
        desc = f"{code} — {label}" + (f" ({tag})" if tag else "")
        seen[code] = desc
        return f"({desc})"

    decorated = re.sub(r"\((\d{3,8})\)", repl, content)
    return decorated, list(seen.values())


def _enrich_rows_with_callsigns(
    rows: list[dict[str, Any]], callsigns: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    lookup = _build_callsign_lookup(callsigns)
    if not lookup:
        return rows
    out: list[dict[str, Any]] = []
    for row in rows:
        decorated, found = _decorate_callsigns_in_content(row, lookup)
        out.append({**row, "content": decorated, "callsigns": found})
    return out


_WOUNDED_RE = re.compile(
    r"(?iu)(?<!\d)(?:300(?:[\s\-.]?(?:й|е|х|го|ый|ые|ых))?|тр[её]хсот\w*|ран[её]н\w*|медик\w*|эвакуац\w*)(?!\d)"
)
_KILLED_RE = re.compile(
    r"(?iu)(?<!\d)(?:200(?:[\s\-.]?(?:й|е|х|го|ый|ые|ых))?|двухсот\w*|убит\w*|погиб\w*)(?!\d)"
)
_COMBAT_RE = re.compile(
    r"(?iu)(?:бой|боя|бои|обстрел\w*|стреля\w*|штурм\w*|удар\w*|враг|противник|эвакуац\w*|отход\w*|накры\w*|мином[её]т\w*|артиллер\w*|дрон\w*|fpv)"
)
_MORALE_RE = re.compile(
    r"(?iu)(?:паник\w*|страшн\w*|устал\w*|не\s+мож\w*|отказ\w*|не\s+пойд\w*|бросил\w*|жалоб\w*|недоволь\w*|проблем\w*|командир\w*|командован\w*|помощ\w*|нет\s+(?:еды|воды|бк|боекомплект\w*|патрон\w*|сигарет\w*))"
)
_SUPPLY_RE = re.compile(
    r"(?iu)(?:бк|боекомплект\w*|патрон\w*|снаряд\w*|вод[аы]|еды|еда|сигарет\w*|сигарет[аы]?|топлив\w*|горюч\w*|медицин\w*|медик\w*|аптечк\w*|связ\w*|раци\w*|обеспеч\w*|снабжен\w*|не\s+хвата\w*|нет\s+(?:еды|воды|бк|патрон\w*|сигарет\w*))"
)


def _snippet_around(text: str, start: int, end: int, radius: int = 90) -> str:
    src = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    left = max(0, int(start) - radius)
    right = min(len(src), int(end) + radius)
    snippet = src[left:right].strip()
    snippet = re.sub(r"\s+", " ", snippet)
    if left > 0:
        snippet = "..." + snippet
    if right < len(src):
        snippet += "..."
    return snippet


def _is_negated_match(text: str, start: int, end: int, term: str) -> bool:
    src = str(text or "").lower()
    term_l = str(term or "").lower()
    left = max(0, int(start) - 28)
    right = min(len(src), int(end) + 28)
    window = src[left:right]
    is_300 = term_l.startswith("300")
    is_200 = term_l.startswith("200")
    code_negated = False
    if is_300:
        code_negated = bool(re.search(r"(?iu)(нет\s+300|300\s+нет|без\s+300)", window))
    elif is_200:
        code_negated = bool(re.search(r"(?iu)(нет\s+200|200\s+нет|без\s+200)", window))
    return bool(
        re.search(r"(?iu)(нет|не было|отсутств\w*|без)\s+\S{0,12}$", src[left : int(start)])
        or re.search(r"(?iu)^\S{0,12}\s+(нет|не было|отсутств\w*)", src[int(end) : right])
        or code_negated
        or re.search(r"(?iu)(убит\w*\s+не\s+было|ранен\w*\s+не\s+было)", window)
    )


def _casualty_findings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    wounded: list[dict[str, str]] = []
    killed: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        content = str(row.get("content") or "")
        meta = {
            "session_id": str(row.get("session_id") or ""),
            "started_at": str(row.get("started_at") or row.get("updated_at") or ""),
            "unit_name": str(row.get("unit_name") or "не указано"),
            "frequency": str(row.get("frequency") or "не указано"),
            "group_code": str(row.get("group_code") or "не указано"),
        }
        for kind, regex, target in (
            ("wounded", _WOUNDED_RE, wounded),
            ("killed", _KILLED_RE, killed),
        ):
            for match in regex.finditer(content):
                term = match.group(0)
                if _is_negated_match(content, match.start(), match.end(), term):
                    continue
                snippet = _snippet_around(content, match.start(), match.end())
                key = (kind, meta["unit_name"], meta["frequency"], meta["group_code"], snippet)
                if key in seen:
                    continue
                seen.add(key)
                target.append({**meta, "term": term, "snippet": snippet})
    return {
        "has_wounded": bool(wounded),
        "has_killed": bool(killed),
        "wounded": wounded[:20],
        "killed": killed[:20],
    }


def _format_casualty_findings(findings: dict[str, Any]) -> str:
    lines = [
        "Предварительная автоматическая проверка санитарных потерь по текстам перехватов:",
        f"- Раненые / 300-е: {'найдены' if findings.get('has_wounded') else 'не найдены'}",
        f"- Убитые / 200-е: {'найдены' if findings.get('has_killed') else 'не найдены'}",
    ]
    wounded = findings.get("wounded") if isinstance(findings.get("wounded"), list) else []
    killed = findings.get("killed") if isinstance(findings.get("killed"), list) else []
    if wounded:
        lines.append("- Найденные признаки раненых:")
        for item in wounded[:8]:
            link = _intercept_link(item)
            lines.append(
                "  * "
                f"Подразделение: {item.get('unit_name')}; "
                f"Дата/смена: {item.get('started_at') or item.get('session_id')}; "
                f"Частота: {item.get('frequency')}; "
                f"Группа: {item.get('group_code')}; "
                f"термин: {item.get('term')}; "
                f"фрагмент: {item.get('snippet')}; "
                f"Открыть бланк: {link}"
            )
    if killed:
        lines.append("- Найденные признаки убитых:")
        for item in killed[:8]:
            link = _intercept_link(item)
            lines.append(
                "  * "
                f"Подразделение: {item.get('unit_name')}; "
                f"Дата/смена: {item.get('started_at') or item.get('session_id')}; "
                f"Частота: {item.get('frequency')}; "
                f"Группа: {item.get('group_code')}; "
                f"термин: {item.get('term')}; "
                f"фрагмент: {item.get('snippet')}; "
                f"Открыть бланк: {link}"
            )
    return "\n".join(lines)


def _shift_operational_findings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    morale: list[dict[str, str]] = []
    supply: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str]] = set()
    for row in rows:
        content = str(row.get("content") or "")
        meta = {
            "session_id": str(row.get("session_id") or ""),
            "started_at": str(row.get("started_at") or row.get("updated_at") or ""),
            "unit_name": str(row.get("unit_name") or "не указано"),
            "frequency": str(row.get("frequency") or "не указано"),
            "group_code": str(row.get("group_code") or "не указано"),
        }
        for kind, regex, target in (
            ("morale", _MORALE_RE, morale),
            ("supply", _SUPPLY_RE, supply),
        ):
            for match in regex.finditer(content):
                snippet = _snippet_around(content, match.start(), match.end())
                key = (kind, meta["unit_name"], meta["frequency"], meta["group_code"], snippet)
                if key in seen:
                    continue
                seen.add(key)
                target.append({**meta, "term": match.group(0), "snippet": snippet})
    return {"morale": morale[:20], "supply": supply[:20]}


def _format_shift_operational_findings(findings: dict[str, Any]) -> str:
    morale = findings.get("morale") if isinstance(findings.get("morale"), list) else []
    supply = findings.get("supply") if isinstance(findings.get("supply"), list) else []
    lines = [
        "Предварительная автоматическая проверка МПС и обеспечения:",
        f"- МПС-признаки жалоб/паники/отказа/просьб о помощи: {'найдены' if morale else 'не найдены'}",
        f"- Признаки проблем обеспечения/связи/БК/воды/еды/медицины: {'найдены' if supply else 'не найдены'}",
    ]
    if morale:
        lines.append("- Найденные МПС-признаки:")
        for item in morale[:8]:
            lines.append(
                "  * "
                f"Подразделение: {item.get('unit_name')}; "
                f"Дата/смена: {item.get('started_at') or item.get('session_id')}; "
                f"Частота: {item.get('frequency')}; "
                f"Группа: {item.get('group_code')}; "
                f"термин: {item.get('term')}; "
                f"фрагмент: {item.get('snippet')}"
            )
    if supply:
        lines.append("- Найденные признаки проблем обеспечения:")
        for item in supply[:8]:
            lines.append(
                "  * "
                f"Подразделение: {item.get('unit_name')}; "
                f"Дата/смена: {item.get('started_at') or item.get('session_id')}; "
                f"Частота: {item.get('frequency')}; "
                f"Группа: {item.get('group_code')}; "
                f"термин: {item.get('term')}; "
                f"фрагмент: {item.get('snippet')}"
            )
    return "\n".join(lines)


def _period_event_findings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    buckets: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str, str, str, str]] = set()

    def bucket_for(row: dict[str, Any], *, count_item: bool = False) -> dict[str, Any]:
        unit = str(row.get("unit_name") or "не указано").strip() or "не указано"
        bucket = buckets.setdefault(
            unit,
            {
                "unit_name": unit,
                "items_count": 0,
                "sessions": set(),
                "channels": set(),
                "wounded": [],
                "killed": [],
                "combat": [],
                "morale": [],
                "supply": [],
            },
        )
        if count_item:
            bucket["items_count"] += 1
        if row.get("session_id"):
            bucket["sessions"].add(str(row.get("session_id")))
        channel = f"{row.get('frequency') or 'не указано'} / {row.get('group_code') or 'не указано'}"
        bucket["channels"].add(channel)
        return bucket

    def add_event(row: dict[str, Any], category: str, match: re.Match) -> None:
        term = match.group(0)
        if category in {"wounded", "killed"} and _is_negated_match(
            str(row.get("content") or ""), match.start(), match.end(), term
        ):
            return
        snippet = _snippet_around(str(row.get("content") or ""), match.start(), match.end(), radius=110)
        unit = str(row.get("unit_name") or "не указано").strip() or "не указано"
        key = (
            category,
            unit,
            str(row.get("session_id") or ""),
            str(row.get("frequency") or ""),
            snippet,
        )
        if key in seen:
            return
        seen.add(key)
        item = {
            "session_id": str(row.get("session_id") or ""),
            "started_at": str(row.get("started_at") or row.get("updated_at") or ""),
            "unit_name": unit,
            "frequency": str(row.get("frequency") or "не указано"),
            "group_code": str(row.get("group_code") or "не указано"),
            "term": term,
            "snippet": snippet,
        }
        bucket_for(row)[category].append(item)

    for row in rows:
        content = str(row.get("content") or "")
        if not content.strip():
            continue
        bucket_for(row, count_item=True)
        for category, regex in (
            ("wounded", _WOUNDED_RE),
            ("killed", _KILLED_RE),
            ("combat", _COMBAT_RE),
            ("morale", _MORALE_RE),
            ("supply", _SUPPLY_RE),
        ):
            for match in regex.finditer(content):
                add_event(row, category, match)

    units: list[dict[str, Any]] = []
    for bucket in buckets.values():
        units.append(
            {
                **bucket,
                "sessions": sorted(bucket["sessions"]),
                "channels": sorted(bucket["channels"]),
            }
        )
    units.sort(
        key=lambda x: (
            len(x.get("wounded") or []) + len(x.get("killed") or []),
            len(x.get("combat") or []),
            len(x.get("morale") or []) + len(x.get("supply") or []),
            int(x.get("items_count") or 0),
        ),
        reverse=True,
    )
    return {"units": units}


def _format_period_event_findings(findings: dict[str, Any]) -> str:
    units = findings.get("units") if isinstance(findings.get("units"), list) else []
    total_wounded = sum(len(u.get("wounded") or []) for u in units)
    total_killed = sum(len(u.get("killed") or []) for u in units)
    total_combat = sum(len(u.get("combat") or []) for u in units)
    total_morale = sum(len(u.get("morale") or []) for u in units)
    total_supply = sum(len(u.get("supply") or []) for u in units)
    lines = [
        "Предварительная автоматическая карта событий периода:",
        f"- Подразделений с перехватами: {len(units)}",
        f"- Признаки раненых / 300-х: {total_wounded}",
        f"- Признаки убитых / 200-х: {total_killed}",
        f"- Признаки боя/обстрела/эвакуации: {total_combat}",
        f"- МПС-признаки жалоб/паники/отказа/помощи: {total_morale}",
        f"- Признаки проблем обеспечения/связи/БК/медицины: {total_supply}",
        "",
        "Карта по подразделениям:",
    ]
    for unit in units[:25]:
        lines.append(
            f"- Подразделение: {unit.get('unit_name')} | "
            f"записей: {unit.get('items_count')} | "
            f"смен: {len(unit.get('sessions') or [])} | "
            f"каналы: {', '.join((unit.get('channels') or [])[:8]) or 'не указано'}"
        )
        for label, key in (
            ("300-е/раненые", "wounded"),
            ("200-е/убитые", "killed"),
            ("Бой/обстрел/эвакуация", "combat"),
            ("МПС/жалобы/паника", "morale"),
            ("Обеспечение/связь/БК/медицина", "supply"),
        ):
            events = unit.get(key) if isinstance(unit.get(key), list) else []
            if not events:
                continue
            lines.append(f"  * {label}: найдено признаков {len(events)}")
            for event in events[:6]:
                link = _intercept_link(event)
                lines.append(
                    "    - "
                    f"Дата/смена: {event.get('started_at') or event.get('session_id')}; "
                    f"частота: {event.get('frequency')}; группа: {event.get('group_code')}; "
                    f"термин: {event.get('term')}; фрагмент: {event.get('snippet')}; "
                    f"Открыть бланк: {link}"
                )
    return "\n".join(lines)


def _format_period_activity_digest(rows: list[dict[str, Any]], *, max_units: int = 35) -> str:
    units: dict[str, dict[str, Any]] = {}
    for row in rows:
        unit = str(row.get("unit_name") or "не указано").strip() or "не указано"
        bucket = units.setdefault(
            unit,
            {
                "unit_name": unit,
                "items_count": 0,
                "sessions": set(),
                "channels": set(),
                "first_seen": "",
                "last_seen": "",
                "samples": [],
            },
        )
        bucket["items_count"] += 1
        if row.get("session_id"):
            bucket["sessions"].add(str(row.get("session_id")))
        bucket["channels"].add(f"{row.get('frequency') or 'не указано'} / {row.get('group_code') or 'не указано'}")
        ts = str(row.get("started_at") or row.get("updated_at") or "")
        if ts:
            bucket["first_seen"] = min(str(bucket["first_seen"] or ts), ts)
            bucket["last_seen"] = max(str(bucket["last_seen"] or ts), ts)
        content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
        if content and len(bucket["samples"]) < 3:
            bucket["samples"].append(
                {
                    "date": ts,
                    "channel": f"{row.get('frequency') or 'не указано'} / {row.get('group_code') or 'не указано'}",
                    "text": _clip(content, 220),
                }
            )

    sorted_units = sorted(
        units.values(),
        key=lambda x: (int(x.get("items_count") or 0), str(x.get("last_seen") or "")),
        reverse=True,
    )
    lines = ["Компактная активность по подразделениям за период:"]
    for unit in sorted_units[:max_units]:
        channels = sorted(unit.get("channels") or [])
        lines.append(
            f"- Подразделение: {unit.get('unit_name')} | записей: {unit.get('items_count')} | "
            f"смен: {len(unit.get('sessions') or [])} | период: {unit.get('first_seen') or 'н/у'} — {unit.get('last_seen') or 'н/у'} | "
            f"каналы: {', '.join(channels[:10]) or 'не указано'}"
        )
        samples = unit.get("samples") if isinstance(unit.get("samples"), list) else []
        for sample in samples[:2]:
            lines.append(
                f"  * пример: {sample.get('date') or 'н/у'} | {sample.get('channel')}: {sample.get('text')}"
            )
    return "\n".join(lines)


def _build_compact_period_input(rows: list[dict[str, Any]], period_block: str) -> str:
    activity = _format_period_activity_digest(rows)
    compact = f"{period_block}\n\n{activity}".strip()
    return _clip(compact, 28000)


def _first_finding(findings: dict[str, Any], key: str) -> dict[str, Any] | None:
    items = findings.get(key)
    if isinstance(items, list) and items:
        first = items[0]
        return first if isinstance(first, dict) else None
    return None


def _format_focused_casualty_answer(findings: dict[str, Any]) -> str:
    wounded = _first_finding(findings, "wounded")
    killed = _first_finding(findings, "killed")
    if wounded and not killed:
        title = "Итог: 200-х не найдено, 300-е есть"
        main = "Убитых / 200-х по перехватам не найдено. Есть признаки раненых / 300-х."
        item = wounded
        fact = "Зафиксированы раненые / 300-е."
    elif wounded and killed:
        title = "Итог: есть признаки 200-х и 300-х"
        main = "По перехватам есть признаки и убитых / 200-х, и раненых / 300-х."
        item = killed
        fact = "Зафиксированы признаки убитых / 200-х и раненых / 300-х."
    elif killed:
        title = "Итог: 300-х не найдено, есть признаки 200-х"
        main = "Раненых / 300-х по перехватам не найдено. Есть признаки убитых / 200-х."
        item = killed
        fact = "Зафиксированы признаки убитых / 200-х."
    else:
        return (
            "### Итог: признаков 200-х/300-х не найдено\n\n"
            "По автоматической проверке текста перехватов признаки раненых / 300-х и убитых / 200-х не найдены.\n\n"
            "### Что проверить\n"
            "- Сверить с предыдущими сменами.\n"
            "- Проверить другие источники, если есть подозрение на потери."
        )

    link = _intercept_link(item)
    return (
        f"### {title}\n\n"
        f"{main}\n\n"
        "### Где найдено\n"
        f"- **Подразделение:** {item.get('unit_name')}\n"
        f"- **Частота:** {item.get('frequency')}\n"
        f"- **Группа:** {item.get('group_code')}\n"
        f"- **Фрагмент:** {item.get('snippet')}\n"
        f"- **Открыть бланк:** {link}\n\n"
        "### Краткий анализ\n"
        f"- {fact}\n"
        "- Требуется уточнить, выполнена ли эвакуация и есть ли развитие события.\n\n"
        "### МПС\n"
        "- Есть стрессовый признак: запрос действий при наличии раненых и необходимость эвакуации.\n"
        "- Прямых жалоб на командование/снабжение не выявлено, если их нет в полном тексте бланка."
    )


def _url_quote(value: Any) -> str:
    from urllib.parse import quote

    return quote(str(value or ""), safe="")


def _is_report_focus(text: str) -> bool:
    src = str(text or "").lower()
    return any(term in src for term in ("отчет", "отчёт", "расшир", "доклад", "военно-делов"))


def _intercept_link(item: dict[str, Any]) -> str:
    session_id = _url_quote(item.get("session_id"))
    frequency = _url_quote(item.get("frequency"))
    group_code = _url_quote(item.get("group_code"))
    highlight = _url_quote(item.get("term"))
    return f"/intercepts?session_id={session_id}&frequency={frequency}&group_code={group_code}&highlight={highlight}"


def _format_casualty_report_answer(findings: dict[str, Any]) -> str:
    wounded = findings.get("wounded") if isinstance(findings.get("wounded"), list) else []
    killed = findings.get("killed") if isinstance(findings.get("killed"), list) else []
    lines = [
        "### Доклад по признакам санитарных потерь",
        "",
        "#### 1. Основание",
        "Доклад сформирован по текстам радиоперехватов выбранной смены. Сведения являются признаками/упоминаниями и требуют проверки оператором.",
        "",
        "#### 2. Общий вывод",
        f"- Признаки раненых / 300-х: {'обнаружены' if wounded else 'не обнаружены'} ({len(wounded)} упоминание(я)).",
        f"- Признаки убитых / 200-х: {'обнаружены' if killed else 'не обнаружены'} ({len(killed)} упоминание(я)).",
        "",
        "#### 3. Зафиксированные эпизоды",
    ]
    events = [("Раненые / 300-е", item) for item in wounded] + [("Убитые / 200-е", item) for item in killed]
    if not events:
        lines.append("- Эпизоды санитарных потерь в перехватах не выявлены.")
    for idx, (label, item) in enumerate(events[:12], start=1):
        lines.append(
            f"{idx}. **{label}**\n"
            f"- Подразделение: {item.get('unit_name') or 'не указано'}.\n"
            f"- Дата/смена: {item.get('started_at') or item.get('session_id') or 'не указано'}.\n"
            f"- Частота/группа: {item.get('frequency') or 'не указано'} / {item.get('group_code') or 'не указано'}.\n"
            f"- Выявленный термин: {item.get('term') or 'не указано'}.\n"
            f"- Фрагмент: {item.get('snippet') or 'не указано'}.\n"
            f"- Открыть бланк: {_intercept_link(item)}"
        )
    lines.extend(
        [
            "",
            "#### 4. Оценка",
            "- Потери не считать подтвержденными без дополнительной проверки.",
            "- Если в тексте указано количество, трактовать его как текстовое указание, а не подтвержденную статистику.",
            "- Принадлежность раненых/убитых уточнить по контексту переговоров и дополнительным источникам.",
            "",
            "#### 5. Необходимо уточнить",
            "- Кому принадлежат указанные 300-е/200-е.",
            "- Выполнена ли эвакуация и каким подразделением.",
            "- Есть ли развитие события в соседних бланках, сеансах и последующих сменах.",
        ]
    )
    return "\n".join(lines)


def _norm_query(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").lower().replace("ё", "е")).strip()


def _user_question_from_focus(focus_query: str) -> str:
    src = str(focus_query or "").strip()
    marker = "\n\nКонтекст предыдущих реплик"
    if marker in src:
        return src.split(marker, 1)[0].strip()
    return src


def _is_general_shift_summary_question(text: str) -> bool:
    src = _norm_query(text)
    if not src:
        return False
    summary_terms = (
        "сводк",
        "что было",
        "что происходило",
        "кратк",
        "итог",
        "опиши",
        "расскаж",
        "обзор",
        "резюме",
        "последн",
    )
    if not any(term in src for term in summary_terms):
        return False
    if _is_casualty_focus(text) and not any(
        term in src for term in ("сводк", "что было", "что происходило", "смен", "последн")
    ):
        return False
    return True


def _build_shift_channel_digest(rows: list[dict[str, Any]]) -> str:
    channels: dict[tuple[str, str, str], list[str]] = {}
    for row in rows:
        content = re.sub(r"\s+", " ", str(row.get("content") or "").strip())
        if not content:
            continue
        key = (
            str(row.get("unit_name") or "не указано").strip() or "не указано",
            str(row.get("frequency") or "не указано").strip() or "не указано",
            str(row.get("group_code") or "не указано").strip() or "не указано",
        )
        channels.setdefault(key, []).append(content[:220])
    if not channels:
        return ""
    lines = ["Краткая карта каналов смены (автоматически):"]
    for (unit, freq, group), snippets in sorted(channels.items()):
        merged = " | ".join(snippets[:3])
        if len(snippets) > 3:
            merged += f" | … ещё {len(snippets) - 3} записей"
        lines.append(f"- {unit} — {freq} / {group} — {merged}")
    return "\n".join(lines)


def _is_casualty_focus(text: str) -> bool:
    src = str(text or "").lower()
    terms = (
        "ранен",
        "ранён",
        "раненн",
        "ранённ",
        "300",
        "трехсот",
        "трёхсот",
        "убит",
        "погиб",
        "200",
        "двухсот",
        "потер",
        "эвакуац",
        "медик",
    )
    return any(term in src for term in terms)


def _chunk_text(text: str, *, chunk_chars: int = CHUNK_CHARS) -> list[str]:
    src = str(text or "").strip()
    if not src:
        return []
    chunks: list[str] = []
    while src:
        if len(src) <= chunk_chars:
            chunks.append(src)
            break
        split_at = src.rfind("\n---\n", 0, chunk_chars)
        if split_at < chunk_chars // 2:
            split_at = src.rfind("\n\n", 0, chunk_chars)
        if split_at < chunk_chars // 2:
            split_at = chunk_chars
        chunks.append(src[:split_at].strip())
        src = src[split_at:].strip()
    return [c for c in chunks if c]


def _ai_chunk_workers() -> int:
    raw = os.environ.get("WEB_PORTAL_AI_CHUNK_WORKERS") or "2"
    try:
        return max(1, min(4, int(raw)))
    except Exception:
        return 2


def _generate_with_chunking(*, task_title: str, prompt_builder, items_text: str) -> str:
    if len(items_text) <= MAX_DIRECT_CHARS:
        prompt = prompt_builder(items_text)
        return generate_ai_text(
            system_prompt=AI_SYSTEM_PROMPT,
            user_prompt=prompt,
            temperature=0.2,
            max_tokens=1600,
        )["text"]

    chunks = _chunk_text(items_text)

    def summarize_chunk(idx: int, chunk: str) -> tuple[int, str]:
        prompt = prompt_builder(chunk)
        partial = generate_ai_text(
            system_prompt=AI_SYSTEM_PROMPT,
            user_prompt=f"Часть {idx}. Сначала сделай промежуточную сводку этой части.\n\n{prompt}",
            temperature=0.2,
            max_tokens=1000,
        )["text"]
        return idx, f"Часть {idx}:\n{partial}"

    partials_by_idx: dict[int, str] = {}
    workers = min(_ai_chunk_workers(), len(chunks))
    if workers <= 1:
        for idx, chunk in enumerate(chunks, start=1):
            part_idx, partial = summarize_chunk(idx, chunk)
            partials_by_idx[part_idx] = partial
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(summarize_chunk, idx, chunk)
                for idx, chunk in enumerate(chunks, start=1)
            ]
            for future in as_completed(futures):
                part_idx, partial = future.result()
                partials_by_idx[part_idx] = partial

    partials = [partials_by_idx[idx] for idx in sorted(partials_by_idx)]

    return generate_ai_text(
        system_prompt=AI_SYSTEM_PROMPT,
        user_prompt=build_reduce_prompt(task_title=task_title, partial_summaries="\n\n".join(partials)),
        temperature=0.2,
        max_tokens=1800,
    )["text"]


def _latest_session(conn, position_name: str) -> dict[str, Any] | None:
    pos = str(position_name or "").strip()
    params: list[Any] = []
    where_sql = ""
    if pos and pos != "__all__":
        where_sql = "WHERE position_name = ? OR TRIM(COALESCE(position_name,'')) = ''"
        params.append(pos)
    row = conn.execute(
        f"""
        SELECT id, position_name, started_at, ended_at, created_by
        FROM (
            SELECT id, position_name, started_at, ended_at, created_by FROM intercept_sessions {where_sql}
            UNION ALL
            SELECT id, position_name, started_at, ended_at, created_by FROM intercept_sessions_archive {where_sql}
        ) t
        ORDER BY started_at DESC, id DESC
        LIMIT 1
        """,
        (*params, *params),
    ).fetchone()
    if not row:
        return None
    return {
        "id": int(row["id"]),
        "position_name": str(row["position_name"] or ""),
        "started_at": str(row["started_at"] or ""),
        "ended_at": str(row["ended_at"] or ""),
        "created_by": str(row["created_by"] or ""),
    }


def _period_items(conn, *, position_name: str, start_ts: str, end_ts: str) -> list[dict[str, Any]]:
    pos = str(position_name or "").strip()
    start = _norm_ts(start_ts)
    end = _norm_ts(end_ts)
    if not start or not end:
        raise ValueError("Укажите начало и конец периода")
    params: list[Any] = [end, start]
    pos_filter = ""
    if pos and pos != "__all__":
        pos_filter = "AND (s.position_name = ? OR TRIM(COALESCE(s.position_name,'')) = '')"
        params.append(pos)
    sql_tpl = """
        SELECT s.id AS session_id, s.position_name, s.started_at, s.ended_at,
               i.unit_name, i.frequency, i.group_code, i.content, i.updated_at
        FROM {sessions} s
        JOIN {items} i ON i.session_id = s.id
        WHERE COALESCE(s.started_at, '') <= ?
          AND COALESCE(s.ended_at, s.started_at, '') >= ?
          AND TRIM(COALESCE(i.content, '')) <> ''
          {pos_filter}
    """
    rows = conn.execute(
        f"""
        {sql_tpl.format(sessions="intercept_sessions", items="intercept_items", pos_filter=pos_filter)}
        UNION ALL
        {sql_tpl.format(sessions="intercept_sessions_archive", items="intercept_items_archive", pos_filter=pos_filter)}
        ORDER BY started_at ASC, session_id ASC, unit_name ASC, frequency ASC, group_code ASC
        """,
        (*params, *params),
    ).fetchall()
    return [
        {
            "session_id": int(r["session_id"]),
            "position_name": str(r["position_name"] or ""),
            "started_at": str(r["started_at"] or ""),
            "ended_at": str(r["ended_at"] or ""),
            "unit_name": str(r["unit_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "content": str(r["content"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


def run_shift_summary(
    conn,
    *,
    position_name: str,
    session_id: int | None = None,
    focus_query: str = "",
    created_by: str = "",
    job_id: int | None = None,
) -> dict[str, Any]:
    cfg = current_ai_config()
    params = {"session_id": session_id, "focus_query": str(focus_query or "").strip()}
    cache_key = _report_cache_key(
        "shift_summary",
        position_name=position_name,
        params=params,
        model=cfg.model,
    )
    if job_id is None:
        job_id = create_ai_job(
            conn,
            task_type="shift_summary",
            position_name=position_name,
            params=params,
            model_name=cfg.model,
            prompt_version=AI_PROMPT_VERSION,
            created_by=created_by,
        )
    update_ai_job(conn, job_id, status="running")
    try:
        with perf_span("ai/shift-summary/load"):
            session = get_intercept_session(conn, int(session_id)) if session_id else _latest_session(conn, position_name)
        if not session:
            raise ValueError("Смена для сводки не найдена")
        with perf_span("ai/shift-summary/items"):
            items = list_intercept_items_for_session(conn, int(session["id"]))
        rows = [
            {
                **item,
                "session_id": session["id"],
                "position_name": session.get("position_name") or position_name,
                "started_at": session.get("started_at") or "",
                "ended_at": session.get("ended_at") or "",
            }
            for item in items
            if str(item.get("content") or "").strip()
        ]
        if not rows:
            raise ValueError("В выбранной смене нет заполненных перехватов")
        cache_key = _report_cache_key(
            "shift_summary",
            position_name=session.get("position_name") or position_name,
            params={
                "session_id": int(session["id"]),
                "focus_query": str(focus_query or "").strip(),
                "fingerprint": _rows_fingerprint(rows),
            },
            model=cfg.model,
        )
        cached = _cached_ai_report(
            conn,
            report_type="shift_summary",
            position_name=session.get("position_name") or position_name,
            cache_key=cache_key,
        )
        if cached:
            result = {**(cached.get("result") or {}), "cached": True}
            update_ai_job(conn, job_id, status="completed", result=result)
            return {
                "job_id": job_id,
                "report_id": cached["report_id"],
                "report_text": cached["report_text"],
                "result": result,
            }
        with perf_span("ai/shift-summary/enrich"):
            callsigns = list_intercept_callsigns(conn, session.get("position_name") or position_name)
            rows = _enrich_rows_with_callsigns(rows, callsigns)
        items_text = _format_items(rows)
        channel_digest = _build_shift_channel_digest(rows)
        user_question = _user_question_from_focus(focus_query)
        narrative_mode = _is_general_shift_summary_question(user_question)
        casualty_findings = _casualty_findings(rows)
        casualty_block = _format_casualty_findings(casualty_findings)
        operational_findings = _shift_operational_findings(rows)
        operational_block = _format_shift_operational_findings(operational_findings)

        def build(chunk: str) -> str:
            prompt = build_shift_summary_prompt(
                position_name=session.get("position_name") or position_name,
                session_meta=session,
                items_text=chunk,
                narrative=narrative_mode,
            )
            if channel_digest and narrative_mode:
                prompt += f"\n\n{channel_digest}\n"
            focus = str(focus_query or "").strip()
            if focus:
                prompt += (
                    "\n\nОтдельный вопрос пользователя, на который нужно ответить по данным смены:\n"
                    f"{focus}\n"
                    "Если в данных нет подтверждения, прямо напиши, что подтверждений в перехватах не найдено.\n"
                    "Если предварительная проверка ниже нашла 300-е/раненых или 200-е/убитых, "
                    "обязательно учитывай это в ответе и не пиши, что подтверждений нет."
                )
                if narrative_mode:
                    prompt += (
                        "\nПользователь просит общую сводку смены: сначала опиши, что происходило по каналам, "
                        "затем отдельно укажи риски, потери и МПС только если они есть в данных."
                    )
            prompt += f"\n\n{casualty_block}\n\n{operational_block}"
            return prompt

        if _is_casualty_focus(user_question) and _is_report_focus(user_question):
            text = _format_casualty_report_answer(casualty_findings)
        elif _is_casualty_focus(user_question) and not narrative_mode:
            text = _format_focused_casualty_answer(casualty_findings)
        else:
            with perf_span("ai/shift-summary/generate"):
                text = _generate_with_chunking(
                    task_title="Сводка смены по перехватам",
                    prompt_builder=build,
                    items_text=items_text,
                )
        result = {
            "session": session,
            "items_count": len(rows),
            "chars": len(items_text),
            "casualty_findings": casualty_findings,
            "operational_findings": operational_findings,
            "report_text": text,
            "cache_key": cache_key,
        }
        report_id = create_ai_report(
            conn,
            job_id=job_id,
            report_type="shift_summary",
            position_name=session.get("position_name") or position_name,
            title=f"Сводка смены #{session['id']}",
            input_summary=f"Смена {session.get('started_at')} — {session.get('ended_at') or 'активна'}, записей: {len(rows)}",
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


def run_period_report(
    conn,
    *,
    position_name: str,
    start_ts: str,
    end_ts: str,
    created_by: str = "",
    job_id: int | None = None,
) -> dict[str, Any]:
    cfg = current_ai_config()
    start = _norm_ts(start_ts)
    end = _norm_ts(end_ts)
    params = {"start": start, "end": end}
    cache_key = _report_cache_key(
        "period_report",
        position_name=position_name,
        params=params,
        model=cfg.model,
    )
    if job_id is None:
        job_id = create_ai_job(
            conn,
            task_type="period_report",
            position_name=position_name,
            params=params,
            model_name=cfg.model,
            prompt_version=AI_PROMPT_VERSION,
            created_by=created_by,
        )
    update_ai_job(conn, job_id, status="running")
    try:
        with perf_span("ai/period-report/items"):
            rows = _period_items(conn, position_name=position_name, start_ts=start, end_ts=end)
        if not rows:
            raise ValueError("За выбранный период нет заполненных перехватов")
        cache_key = _report_cache_key(
            "period_report",
            position_name=position_name,
            params={**params, "fingerprint": _rows_fingerprint(rows)},
            model=cfg.model,
        )
        cached = _cached_ai_report(
            conn,
            report_type="period_report",
            position_name=position_name,
            cache_key=cache_key,
        )
        if cached:
            result = {**(cached.get("result") or {}), "cached": True}
            update_ai_job(conn, job_id, status="completed", result=result)
            return {
                "job_id": job_id,
                "report_id": cached["report_id"],
                "report_text": cached["report_text"],
                "result": result,
            }
        with perf_span("ai/period-report/enrich"):
            callsigns = list_intercept_callsigns(conn, position_name)
            rows = _enrich_rows_with_callsigns(rows, callsigns)
        with perf_span("ai/period-report/compact"):
            items_text = _format_items(rows)
            period_findings = _period_event_findings(rows)
            period_block = _format_period_event_findings(period_findings)
            compact_items_text = _build_compact_period_input(rows, period_block)
        def build(chunk: str) -> str:
            return build_period_report_prompt(
                position_name=position_name,
                start_ts=start,
                end_ts=end,
                items_text=chunk,
            )

        with perf_span("ai/period-report/generate"):
            text = _generate_with_chunking(
                task_title=f"AI-анализ периода {start} — {end}",
                prompt_builder=build,
                items_text=compact_items_text,
            )
        sessions_count = len({int(r["session_id"]) for r in rows})
        result = {
            "start": start,
            "end": end,
            "sessions_count": sessions_count,
            "items_count": len(rows),
            "chars": len(items_text),
            "compact_chars": len(compact_items_text),
            "period_findings": period_findings,
            "report_text": text,
            "cache_key": cache_key,
        }
        report_id = create_ai_report(
            conn,
            job_id=job_id,
            report_type="period_report",
            position_name=position_name,
            title=f"AI-анализ периода {start} — {end}",
            input_summary=f"Период {start} — {end}, смен: {sessions_count}, записей: {len(rows)}",
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
