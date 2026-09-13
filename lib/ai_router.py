from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from web_portal.lib.ai_client import generate_ai_text
from web_portal.lib.ai_project_scope import (
    PROJECT_SEARCH_SOURCE_IDS,
    get_capability_answer,
    get_search_planner_scope_block,
    wants_broad_project_scan,
)
from web_portal.lib.ai_sessions import (
    _build_unit_activity_findings,
    _build_duty_findings,
    _build_sessions_findings,
    _format_cross_unit_summary,
    _format_duty_summary,
    _build_id_network_findings,
    _format_id_network_summary,
    _format_unit_activity_summary,
    _is_duty_query,
    _is_id_network_query,
    _is_unknown_unit_name,
    _unit_key,
    _sessions_rows,
    resolve_sessions_period,
)
from web_portal.lib.auth_db import list_targeting
from web_portal.lib.db import (
    get_analysis_assignments,
    get_network_intensity_clusters,
    list_dict_callsigns,
    list_dict_frequencies,
    list_dict_units,
    search_intercept_items,
    update_unit_name,
)
import logging

_log = logging.getLogger("web_portal.lib.ai_router")


def _norm(text: str) -> str:
    return str(text or "").strip().lower().replace("ё", "е")


def _period_from_question(question: str) -> tuple[str, str]:
    src = _norm(question)
    now = datetime.now().replace(microsecond=0)
    if any(x in src for x in ("месяц", "30 д", "тридц")):
        start = now - timedelta(days=30)
    elif any(x in src for x in ("недел", "7 д", "семь")):
        start = now - timedelta(days=7)
    elif any(x in src for x in ("сутк", "24 час")):
        start = now - timedelta(days=1)
    else:
        start = now.replace(hour=0, minute=0, second=0)
    return start.strftime("%Y-%m-%d %H:%M:%S"), now.strftime("%Y-%m-%d %H:%M:%S")


def _extract_frequency_group(question: str) -> tuple[str, str]:
    text = str(question or "")
    freq_match = re.search(r"(?<!\d)(\d{3}[,.]\d{3,4})(?!\d)", text)
    group_source = text
    if freq_match:
        group_source = f"{text[:freq_match.start()]} {text[freq_match.end():]}"
    group_match = re.search(r"(?iu)\bG?(\d{3,12})\b", group_source)
    freq = freq_match.group(1).replace(",", ".") if freq_match else ""
    group = f"G{group_match.group(1)}" if group_match and "g" in text.lower() else (group_match.group(1) if group_match else "")
    return freq, group


def _extract_search_query(question: str) -> str:
    text = str(question or "").strip()
    quoted = re.findall(r"[\"'«](.+?)[\"'»]", text)
    if quoted:
        return quoted[0].strip()
    cleaned = re.sub(
        r"(?iu)\b(найди|поиск|поищи|где|указан[оы]?|указаны|упоминал[оаи]?сь?|упоминается|проект[еу]?|данных|перехватах|перехваты|бланках|бланки|пройдись|посмотри|проверь|были\s+ли|было\s+ли|покажи|сравни)\b",
        " ",
        text,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" :;,.")
    return cleaned[:120]


def _search_terms_from_question(question: str) -> list[str]:
    src = _norm(question)
    combined: list[str] = []

    def _add_unique(items: list[str]) -> None:
        for item in items:
            if item not in combined:
                combined.append(item)

    if any(x in src for x in ("ранен", "раненн", "300", "трехсот", "трёхсот", "санитарн", "потер")):
        _add_unique(["300", "ранен", "ранён", "трехсот", "трёхсот", "эвакуац", "медик", "оскол"])
    if any(x in src for x in ("убит", "погиб", "200", "двухсот")):
        _add_unique(["200", "убит", "погиб", "двухсот"])
    if combined:
        return combined
    if any(x in src for x in ("снабж", "обеспеч", "припас", "боеком", "бк", "патрон", "снаряд", "еда", "вод", "сигарет", "топлив", "горюч")):
        return [
            "снабж",
            "обеспеч",
            "боеком",
            "бк",
            "патрон",
            "снаряд",
            "мина",
            "вода",
            "воды",
            "еда",
            "еды",
            "сигарет",
            "топлив",
            "горюч",
            "не хватает",
            "не хват",
            "законч",
            "не привез",
            "не подвез",
            "подвез",
            "проблем",
        ]
    if any(x in src for x in ("жалоб", "жалов", "недоволь", "паник", "устал", "страх", "отказ", "мораль", "мпс")):
        return [
            "жалоб",
            "жалов",
            "недоволь",
            "паник",
            "устал",
            "устали",
            "страш",
            "страх",
            "отказ",
            "не хочу",
            "не будем",
            "не хватает",
            "проблем",
            "плохо",
            "брос",
        ]
    if any(x in src for x in ("бой", "обстрел", "удар", "арт", "мином", "дрон", "враг", "штурм", "атака")):
        return ["бой", "обстрел", "удар", "арта", "артил", "мином", "дрон", "враг", "штурм", "атака", "накры", "прилет"]
    if any(x in src for x in ("эваку", "вывоз", "забрать", "забери", "медик")):
        return ["эвакуац", "эваку", "вывоз", "забрать", "забери", "медик", "помощ"]
    if any(x in src for x in ("аномал", "риск", "подозр", "странн", "важн", "критич", "необыч")):
        return [
            "300",
            "200",
            "ранен",
            "убит",
            "погиб",
            "эвакуац",
            "медик",
            "враг",
            "обстрел",
            "удар",
            "дрон",
            "штурм",
            "проблем",
            "не хватает",
            "жалоб",
            "паник",
            "отказ",
            "срочно",
            "помощ",
        ]
    if any(x in src for x in ("связ", "слыш", "прием", "прийом", "частот", "групп", "канал")):
        return ["связ", "слыш", "прием", "прийом", "частот", "групп", "канал"]
    q = _extract_search_query(question)
    tokens = [
        t
        for t in re.findall(r"(?iu)[а-яa-z0-9]{3,}", q.lower())
        if t
        not in {
            "что",
            "кто",
            "как",
            "это",
            "мне",
            "нам",
            "есть",
            "все",
            "всех",
            "вся",
            "были",
            "было",
            "была",
            "был",
            "ли",
            "или",
            "там",
            "тут",
            "про",
            "где",
            "когда",
            "какие",
            "какой",
            "какая",
            "какое",
            "какую",
            "какую-нибудь",
            "нибудь",
            "нужно",
            "нужна",
            "нужен",
            "покажи",
            "найди",
            "поиск",
            "упоминания",
            "упоминание",
            "упоминается",
            "указаны",
            "указано",
            "проект",
            "проекте",
            "сделай",
            "может",
            "мог",
        }
    ]
    expanded: list[str] = []
    for token in tokens:
        expanded.append(token)
        m = re.fullmatch(r"g(\d{2,12})", token, flags=re.IGNORECASE)
        if m:
            expanded.append(m.group(1))
        elif re.fullmatch(r"\d{2,12}", token):
            expanded.append(f"g{token}")
    tokens = list(dict.fromkeys(expanded))
    numeric = [t for t in tokens if re.fullmatch(r"\d{2,12}", t)]
    if numeric:
        return numeric[:6]
    return tokens[:8]


def _ensure_non_empty_search_terms_for_project_search(question: str) -> list[str]:
    """
    Когда вопрос не попадает в шаблоны _search_terms_from_question, всё равно извлечь
    строки/токены для широкого поиска (режим freeform-агента).
    """
    q = str(_extract_search_query(question) or question or "").strip()
    if not q:
        return []
    t = _search_terms_from_question(question)
    if t:
        return t
    toks = [
        x
        for x in re.findall(r"(?iu)[а-яa-z0-9]{2,}", q.lower())
        if x
        not in {
            "что",
            "как",
            "это",
            "там",
            "тут",
            "для",
            "все",
            "всех",
            "мне",
            "нас",
            "вам",
            "они",
        }
    ]
    if toks:
        return list(dict.fromkeys(toks))[:8]
    compact = re.sub(r"(?u)[^\s\w.]+", " ", q)
    w = " ".join(compact.split()[:4]).strip()
    if len(w) >= 2:
        return [w[:48]]
    return [q[: min(48, len(q))]] if q else []


def _project_search_category(question: str) -> str:
    src = _norm(question)
    if any(x in src for x in ("ранен", "раненн", "300", "трехсот", "трехсот", "санитарн", "потер")):
        return "casualty"
    if any(x in src for x in ("убит", "погиб", "200", "двухсот")):
        return "killed"
    if any(x in src for x in ("снабж", "обеспеч", "припас", "боеком", "бк", "патрон", "снаряд", "еда", "вод", "сигарет", "топлив", "горюч")):
        return "supply"
    if any(x in src for x in ("жалоб", "жалов", "недоволь", "паник", "устал", "страх", "отказ", "мораль", "мпс")):
        return "morale"
    if any(x in src for x in ("бой", "обстрел", "удар", "арт", "мином", "дрон", "враг", "штурм", "атака")):
        return "combat"
    if any(x in src for x in ("эваку", "вывоз", "забрать", "забери", "медик")):
        return "evacuation"
    if any(x in src for x in ("аномал", "риск", "подозр", "странн", "важн", "критич", "необыч")):
        return "anomaly"
    return ""


def _wants_report_answer(question: str) -> bool:
    src = _norm(question)
    return any(x in src for x in ("отчет", "отчёт", "доклад", "справк", "расшир", "военно-делов"))


_PROJECT_SEARCH_SOURCES = set(PROJECT_SEARCH_SOURCE_IDS)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        _log.debug("_extract_json_object: suppressed error", exc_info=True)
    match = re.search(r"\{[\s\S]*\}", raw)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _normalize_search_plan(obj: dict[str, Any] | None) -> dict[str, Any]:
    if not obj:
        return {}
    category = str(obj.get("category") or "").strip().lower()
    if category not in {
        "casualty",
        "killed",
        "supply",
        "morale",
        "combat",
        "evacuation",
        "anomaly",
        "communications",
        "sessions",
        "dictionary",
        "assignments",
        "targeting",
        "ml",
        "general",
    }:
        category = "general"

    terms_raw = obj.get("terms") if isinstance(obj.get("terms"), list) else []
    terms = []
    for term in terms_raw:
        s = str(term or "").strip().lower()
        if 2 <= len(s) <= 40 and s not in terms:
            terms.append(s)
        if len(terms) >= 18:
            break

    sources_raw = obj.get("sources") if isinstance(obj.get("sources"), list) else []
    sources = []
    for source in sources_raw:
        s = str(source or "").strip().lower()
        if s in _PROJECT_SEARCH_SOURCES and s not in sources:
            sources.append(s)

    return {
        "category": category,
        "terms": terms,
        "sources": sources,
        "reason": str(obj.get("reason") or "").strip()[:180],
    }


def _ai_project_search_plan(question: str) -> dict[str, Any]:
    """Use the local model as a semantic planner. Falls back silently."""
    q = str(question or "").strip()
    if not q:
        return {}
    scope = get_search_planner_scope_block()
    prompt = f"""
Ты планировщик поиска для военного аналитического веб-портала.
Твоя задача НЕ отвечать пользователю, а выбрать, где искать факты и какими словами.

{scope}

Категории:
casualty, killed, supply, morale, combat, evacuation, anomaly, communications,
sessions, dictionary, assignments, targeting, ml, general.

Правила:
- Если пользователь спрашивает смыслом ("жалобы на снабжение", "проблемы с водой",
  "не хватает БК"), расширь terms похожими словами.
- Если вопрос про реальные фразы/события, обязательно включай intercepts.
- Если про аномалии/риски/подозрительное, категория anomaly, terms должны быть широкими:
  300, 200, ранен, убит, эвакуац, враг, обстрел, удар, дрон, проблем, жалоб, паник, отказ.
- Если вопрос про ID/сеансы/частоты/группы, включай sessions.
- Если вопрос про позывной/что за частота/группа, включай dictionaries.
- Верни только JSON без markdown.

Формат:
{{
  "category": "supply",
  "terms": ["снабж", "обеспеч", "бк", "вода", "не хватает"],
  "sources": ["intercepts", "ai_reports"],
  "reason": "кратко почему"
}}

Вопрос пользователя:
{q}
""".strip()
    try:
        result = generate_ai_text(
            system_prompt="Ты возвращаешь только валидный JSON-план поиска.",
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=700,
        )
        return _normalize_search_plan(_extract_json_object(str(result.get("text") or "")))
    except Exception:
        return {}


def _merge_search_terms(*groups: list[str]) -> list[str]:
    out: list[str] = []
    for group in groups:
        for term in group or []:
            s = str(term or "").strip().lower()
            if s and s not in out:
                out.append(s)
            if re.fullmatch(r"g\d{2,12}", s):
                bare = s[1:]
                if bare not in out:
                    out.append(bare)
            elif re.fullmatch(r"\d{2,12}", s):
                g = f"g{s}"
                if g not in out:
                    out.append(g)
            if len(out) >= 24:
                return out
    return out


def normalize_user_search_question(question: str) -> str:
    """
    Убирает служебные префиксы из текста вопроса (чат, route_project).
    «только перехваты:» / «только бланки:» — подсказка планировщику про перехваты/бланки.
    """
    raw = str(question or "").strip()
    if not raw:
        return raw
    low = raw.lower()
    if (
        low.startswith("поиск:")
        or low.startswith("search:")
        or low.startswith("по проекту:")
    ):
        rest = raw.split(":", 1)[1].strip() if ":" in raw else ""
        return rest or raw
    if low.startswith("только перехваты:") or low.startswith("только бланки:"):
        rest = raw.split(":", 1)[1].strip() if ":" in raw else ""
        body = rest or raw
        return (
            f"{body}\n\n(Режим запроса: приоритет перехватам и полнотексту бланков.)"
        )
    return raw


def has_explicit_project_search_prefix(question: str) -> bool:
    low = str(question or "").strip().lower()
    return low.startswith(
        ("поиск:", "search:", "по проекту:", "только перехваты:", "только бланки:")
    )


def _wants_text_mention_search(question: str) -> bool:
    """
    Поиск упоминаний/фраз в перехватах и сеансах, а не сводка
    «межподразделенческих взаимодействий» по структурированным сеансам.
    """
    src = _norm(question)
    scope = any(
        x in src
        for x in (
            "сеанс",
            "перехват",
            "бланк",
            "цитат",
            "вхожден",
            "в бланке",
            "в перехвате",
        )
    )
    if not scope:
        return False
    if any(
        x in src
        for x in (
            "где сказан",
            "где сказа",
            "сказано про",
            "сказали про",
            "упомин",
            "в тексте",
            "фрагмен",
            "фраз",
            "встреча",
            "строк",
            "все вхожден",
        )
    ):
        return True
    if "участ" in src and "сеанс" in src:
        return any(
            x in src
            for x in ("про", "где", "найди", "поиск", "текст", "сказа", "сказан")
        )
    if any(x in src for x in ("найди", "поиск", "поищи", "проверь", "покаж")) and any(
        x in src for x in ("строк", "вхожден", "цитат", "бланк", "перехват")
    ):
        return True
    return False


def _is_sessions_query(question: str) -> bool:
    src = _norm(question)
    mentions_id = bool(re.search(r"(?iu)(?<![а-яa-z])(?:айди\w*|id)(?![а-яa-z])", src))
    return (
        _is_duty_query(src)
        or mentions_id
        or "сеанс" in src
        or "взаимодейств" in src
        or "других подраздел" in src
    )


def _has_sessions_words(question: str) -> bool:
    src = _norm(question)
    mentions_id = bool(re.search(r"(?iu)(?<![а-яa-z])(?:айди\w*|id)(?![а-яa-z])", src))
    return mentions_id or any(x in src for x in ("сеанс", "взаимодейств", "других подраздел", "дежурн", "оперативн"))


def _extract_requested_radio_id(question: str) -> str:
    ids = re.findall(r"(?<!\d)(\d{3,10})(?!\d)", str(question or ""))
    return ids[0] if len(ids) == 1 else ""


def _is_id_profile_query(question: str) -> bool:
    src = _norm(question)
    if "других подраздел" in src or "другом подраздел" in src or "разных подраздел" in src:
        return False
    requested_id = _extract_requested_radio_id(question)
    if not requested_id:
        return False
    mentions_id = bool(re.search(r"(?iu)(?<![а-яa-z])(?:айди\w*|id)(?![а-яa-z])", src))
    wants_profile = any(x in src for x in ("расскажи", "что известно", "профиль", "информация", "сводка", "покажи"))
    numeric_lookup = any(x in src for x in ("найди", "покажи", "проверь", "расскажи"))
    return (mentions_id and wants_profile) or numeric_lookup


def _is_unknown_unit_assignment_query(question: str) -> bool:
    src = _norm(question)
    requested_id = _extract_requested_radio_id(question)
    if not requested_id:
        return False
    mentions_id = bool(re.search(r"(?iu)(?<![а-яa-z])(?:айди\w*|id)(?![а-яa-z])", src))
    mentions_unknown = "не указано" in src or "подразделение не указано" in src
    mentions_unit = any(x in src for x in ("шб", "мб", "бон", "брон", "бат", "бтгр", "ошп", "дшбр", "омбр", "нгу", "спартан", "скала", "оебр"))
    action = any(
        x in src
        for x in (
            "запиши",
            "записать",
            "поставь",
            "поставить",
            "укажи",
            "указать",
            "привяжи",
            "привязать",
            "обнови",
            "обновить",
            "добавь",
            "добавить",
            "пометь",
            "пометить",
            "заполни",
            "заполнить",
            "назначь",
            "назначить",
            "присвой",
            "присвоить",
            "автоматически",
        )
    )
    return action and mentions_id and mentions_unknown and mentions_unit


def _extract_unit_hint_from_question(question: str) -> str:
    text = re.sub(r"(?is)\n+контекст предыдущего сообщения:.*$", "", str(question or "")).strip()

    def clean(candidate: str) -> str:
        candidate = re.sub(r"(?<!\d)\d{5,10}(?!\d)", " ", str(candidate or ""))
        candidate = re.sub(
            r"(?iu)\b(ты|можешь|можно|пожалуйста|где|подразделени[еяю]|не|указано|укажи|указать|их|его|ее|её|как|на|в|для|данн\w*|этот|айдишник\w*|айди|id|был|была|были|зафиксирован\w*|контекст|предыдущего|сообщения)\b",
            " ",
            candidate,
        )
        candidate = re.sub(r"\s+", " ", candidate).strip(" ,.;:-")
        candidate = re.sub(r'\s*"\s*"', '"', candidate)
        return candidate[:120]

    def from_unit_marker(candidate: str) -> str:
        match = re.search(
            r"(?iu)(\d+\s+(?:шб|мб|бон|брон|бтгр|батальон|бригада|ошп|омбр|дшбр|оебр|нгу)\b[^\n,;]*)",
            candidate,
        )
        return clean(match.group(1)) if match else ""

    after_as = re.search(r"(?iu)\b(?:как|на|в)\s+(.+)$", text)
    if after_as:
        hinted = from_unit_marker(after_as.group(1)) or clean(after_as.group(1))
        if hinted:
            return hinted

    quoted = re.findall(r"[\"«](.+?)[\"»]", text)
    if quoted:
        prefix = text[: text.find(quoted[0])].strip()
        suffix_start = text.find(quoted[0]) + len(quoted[0])
        suffix = text[suffix_start:].strip(" \"»«")
        around_quote = f"{prefix} \"{quoted[0].strip()}\" {suffix}".strip()
        hinted = from_unit_marker(around_quote)
        if hinted:
            return hinted
        before_quote = re.sub(
            r"(?iu)\b(ты|можешь|можно|назови|укажи|указать|как|подразделени[еяю]|где|данн\w*|этот|айдишник\w*|айди|id|был|была|были|зафиксирован\w*|не|указано|контекст|предыдущего|сообщения)\b",
            " ",
            prefix,
        )
        after_quote = re.sub(
            r"(?iu)\b(ты|можешь|можно|назови|укажи|указать|как|подразделени[еяю]|где|данн\w*|этот|айдишник\w*|айди|id|был|была|были|зафиксирован\w*|не|указано|контекст|предыдущего|сообщения)\b.*$",
            " ",
            suffix,
        )
        before_quote = re.sub(r"(?<!\d)\d{3,10}(?!\d)", " ", before_quote)
        before_quote = re.sub(r"\s+", " ", before_quote).strip(" ,.;:-")
        after_quote = re.sub(r"(?<!\d)\d{3,10}(?!\d)", " ", after_quote)
        after_quote = re.sub(r"\s+", " ", after_quote).strip(" ,.;:-")
        return clean(f"{before_quote} \"{quoted[0].strip()}\" {after_quote}")
    cleaned = re.sub(
        r"(?iu)\b(ты|можешь|можно|назови|укажи|указать|как|подразделени[еяю]|где|данн\w*|этот|айдишник\w*|айди|id|был|была|были|зафиксирован\w*|не|указано|контекст|предыдущего|сообщения)\b",
        " ",
        text,
    )
    cleaned = re.sub(r"(?<!\d)\d{3,10}(?!\d)", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.;:-")
    return from_unit_marker(text) or cleaned[:120]


def _is_activity_query(question: str) -> bool:
    src = _norm(question)
    return any(
        x in src
        for x in (
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


def _is_dictionary_query(question: str) -> bool:
    src = _norm(question)
    if any(x in src for x in ("справочник", "позывн", "частот", "групп", "подразделен")):
        return True
    if "что за" not in src:
        return False
    return bool(
        re.search(r"(?<!\d)(?:\d{3}[,.]\d{3,4}|g?\d{3,12})(?!\d)", src)
        or any(x in src for x in ("позыв", "сеть", "канал"))
    )


def _is_assignment_query(question: str) -> bool:
    src = _norm(question)
    return any(x in src for x in ("назначен", "назначение", "батальон", "рота", "оперативный дежурный", "дежурный на"))


def _is_targeting_query(question: str) -> bool:
    src = _norm(question)
    return any(x in src for x in ("нацелив", "targeting", "активные задачи", "мои задачи", "поручен", "что мне назнач"))


def _is_intercept_search_query(question: str) -> bool:
    src = _norm(question)
    if any(x in src for x in ("найди", "поиск", "поищи", "упомин", "где было", "где в перехват", "где указан", "где указаны", "пройдись", "когда-либо", "когда либо")):
        return True
    if any(x in src for x in ("покажи", "проверь", "сравни")):
        return any(x in src for x in ("проект", "данн", "перехват", "бланк", "сеанс", "айди", "id", "частот", "групп", "подраздел"))
    return False


def _should_attempt_project_search(question: str) -> bool:
    src = _norm(question)
    if _project_search_category(question):
        return True
    if any(
        x in src
        for x in (
            "проект",
            "по данным",
            "в данных",
            "база",
            "бд",
            "перехват",
            "бланк",
            "сеанс",
            "айди",
            " id ",
            "частот",
            "групп",
            "подраздел",
            "позывн",
            "справочник",
            "назначен",
            "дежурн",
            "оперативн",
            "targeting",
            "активные задачи",
            "ml",
            "прогноз",
        )
    ):
        return True
    if _is_intercept_search_query(question) and any(
        x in src for x in ("найди", "поиск", "поищи", "пройдись", "упомин", "где было", "где указан", "где указаны")
    ):
        return True
    return False


def _is_ml_query(question: str) -> bool:
    src = _norm(question)
    return any(x in src for x in ("ml", "мл", "прогноз", "предсказ", "hotspot", "модель"))


def _is_capability_question(question: str) -> bool:
    src = _norm(question)
    return (
        any(x in src for x in ("можешь", "умеешь", "что ты можешь", "твои возможности", "как пользоваться"))
        and any(x in src for x in ("искать", "поиск", "проект", "данным", "свободно", "помочь"))
    )


def _is_unit_profile_query(question: str) -> bool:
    src = _norm(question)
    has_profile_phrase = any(
        x in src for x in ("расскажи про", "расскажи о", "что известно про", "что известно о", "сводка по", "информация по")
    )
    has_unit_marker = any(
        x in src for x in ("шб", "мб", "бон", "брон", "бат", "бтгр", "ошп", "дшбр", "омбр", "нгу", "спартан", "скала", "оебр")
    )
    has_unit_number = bool(re.search(r"(?<!\d)\d{1,4}(?!\d)", src))
    return has_profile_phrase and (has_unit_marker or ("подраздел" in src and has_unit_number))


def _unit_profile_query_terms(question: str) -> list[str]:
    src = _norm(question)
    cleaned = re.sub(
        r"(?iu)\b(расскажи|про|что|известно|информация|сводка|подразделени[еяю]|по|о|об)\b",
        " ",
        src,
    )
    out: list[str] = []
    for token in re.findall(r"(?iu)[а-яa-z0-9]+", cleaned):
        if token in {"нгу"}:
            continue
        if token not in out:
            out.append(token)
        if len(out) >= 12:
            break
    return out


def _unit_profile_query_pairs(question: str) -> list[str]:
    cleaned = re.sub(
        r"(?iu)\b(расскажи|про|что|известно|информация|сводка|подразделени[еяю]|по|о|об)\b",
        " ",
        _norm(question),
    )
    tokens = re.findall(r"(?iu)[а-яa-z0-9]+", cleaned)
    pairs = []
    for idx in range(len(tokens) - 1):
        if tokens[idx].isdigit() and re.search(r"(?iu)[а-яa-z]", tokens[idx + 1]):
            pair = f"{tokens[idx]}:{tokens[idx + 1]}"
            if pair not in pairs:
                pairs.append(pair)
    return pairs


def _unit_profile_score(unit_name: str, terms: list[str], pairs: list[str]) -> int:
    hay = _norm(unit_name)
    key = _unit_key(unit_name)
    term_score = sum(1 for term in terms if term in hay)
    pair_score = sum(1 for pair in pairs if pair in key) * 4
    return term_score + pair_score


def _unit_matches_query(unit_name: str, terms: list[str], pairs: list[str] | None = None) -> bool:
    hay = _norm(unit_name)
    if not hay or not terms:
        return False
    score = _unit_profile_score(unit_name, terms, pairs or [])
    return score >= max(1, min(3, len(terms)))


def _unit_doc_dirs() -> list[Path]:
    root = Path(__file__).resolve().parents[1]
    dirs: list[Path] = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        name = _norm(child.name)
        if any(marker in name for marker in ("подраздел", "поздраздел", "podraz", "unit")):
            dirs.append(child)
    return dirs


def _read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def _significant_unit_tokens(text: str) -> set[str]:
    skip = {
        "про",
        "что",
        "как",
        "шб",
        "мб",
        "бон",
        "брон",
        "бат",
        "бтгр",
        "ошп",
        "омбр",
        "дшбр",
        "нгу",
    }
    return {
        token
        for token in re.findall(r"(?iu)[а-яa-z0-9]{2,}", _norm(text))
        if token not in skip and (token.isdigit() or len(token) >= 4)
    }


def _find_unit_document(*, unit_name: str, question: str, terms: list[str], pairs: list[str]) -> dict[str, Any] | None:
    unit_tokens = _significant_unit_tokens(unit_name)
    query_tokens = _significant_unit_tokens(question)
    best: tuple[int, Path] | None = None
    for directory in _unit_doc_dirs():
        for path in directory.glob("*.txt"):
            stem = _norm(path.stem)
            doc_tokens = _significant_unit_tokens(path.stem)
            score = 0
            score += sum(3 for token in unit_tokens if token in doc_tokens or token in stem)
            score += sum(2 for token in query_tokens if token in doc_tokens or token in stem)
            score += _unit_profile_score(path.stem, terms, pairs)
            if score <= 0:
                continue
            if best is None or score > best[0]:
                best = (score, path)
    if best is None:
        return None
    text = _read_text_file(best[1]).strip()
    if not text:
        return None
    return {"path": best[1], "text": text, "score": best[0]}


def _line_after_label(lines: list[str], label: str) -> str:
    label_l = _norm(label)
    for idx, line in enumerate(lines):
        current = line.strip()
        if _norm(current).startswith(label_l):
            value = current[len(label) :].strip(" \t:-")
            if value:
                return value
            for nxt in lines[idx + 1 : idx + 4]:
                nxt = nxt.strip()
                if nxt:
                    return nxt
    return ""


def _section_lines(lines: list[str], start_label: str, stop_labels: tuple[str, ...], *, limit: int = 6) -> list[str]:
    start_idx = -1
    for idx, line in enumerate(lines):
        if _norm(line).startswith(_norm(start_label)):
            start_idx = idx + 1
            break
    if start_idx < 0:
        return []
    out: list[str] = []
    for line in lines[start_idx:]:
        clean = line.strip(" \t•-")
        if not clean:
            continue
        if any(_norm(clean).startswith(_norm(stop)) for stop in stop_labels):
            break
        if len(clean) > 120:
            continue
        out.append(clean)
        if len(out) >= limit:
            break
    return out


def _clean_doc_value(value: str) -> str:
    cleaned = re.sub(r"\[\d+\]", "", str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .;,\t")
    return cleaned


def _format_unit_document_summary(document: dict[str, Any]) -> str:
    text = str(document.get("text") or "")
    raw_lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in raw_lines if line]
    if not lines:
        return ""

    title = lines[0]
    founded = _line_after_label(lines, "Основан")
    affiliation = _line_after_label(lines, "Принадлежащий")
    unit_type = _line_after_label(lines, "Тип")
    role = _line_after_label(lines, "Роль")
    nickname = _line_after_label(lines, "Псевдонимы")
    commander = _line_after_label(lines, "командир") or _line_after_label(lines, "Текущий")
    site = _line_after_label(lines, "Сайт")
    structure = _section_lines(lines, "Структура", ("Оборудование", "Символизм", "Командование"), limit=5)
    equipment = _section_lines(lines, "Оборудование", ("Символизм", "Командование", "Награжден"), limit=6)
    battles = [
        line
        for line in lines
        if any(marker in _norm(line) for marker in ("битв", "сражен", "вторжение", "изюм", "покровск", "торецк"))
    ][:6]

    rel_path = str(document.get("path") or "")
    try:
        rel_path = str(Path(rel_path).resolve().relative_to(Path(__file__).resolve().parents[1]))
    except Exception:
        _log.debug("_format_unit_document_summary: suppressed error", exc_info=True)

    facts = []
    if founded:
        facts.append(f"основан: {founded}")
    if affiliation:
        facts.append(f"принадлежность: {affiliation}")
    if unit_type:
        facts.append(f"тип: {unit_type}")
    if role:
        facts.append(f"роль: {role}")
    if nickname:
        facts.append(f"псевдоним: {nickname}")
    if commander:
        facts.append(f"командир: {commander}")

    title = _clean_doc_value(title)
    facts = [_clean_doc_value(fact) for fact in facts if _clean_doc_value(fact)]
    battles = [_clean_doc_value(item) for item in battles if _clean_doc_value(item)]
    structure = [_clean_doc_value(item) for item in structure if _clean_doc_value(item)]
    equipment = [_clean_doc_value(item) for item in equipment if _clean_doc_value(item)]

    out = ["#### Краткая справка"]
    out.append(f"**{title}.**")
    if facts:
        out.append(f"**Основное:** {'; '.join(facts[:6])}.")
    if battles:
        out.append(f"**Боевой путь:** {'; '.join(battles[:4])}.")
    if structure or equipment:
        out.append("")
        out.append("#### Структура и оснащение")
    if structure:
        out.append(f"- **Структура:** {', '.join(structure)}.")
    if equipment:
        out.append(f"- **Техника:** {', '.join(equipment)}.")
    if site:
        out.append(f"- **Сайт:** {_clean_doc_value(site)}.")
    out.append(f"- **Источник:** `{rel_path}`.")
    return "\n".join(out)


def _format_unit_profile_answer(conn, *, position_name: str, question: str) -> str | None:
    terms = _unit_profile_query_terms(question)
    pairs = _unit_profile_query_pairs(question)
    if not terms:
        return None

    start, end = _period_from_question("сегодня")
    session_rows_all = _sessions_rows(conn, start_ts=start, end_ts=end, position_name=position_name)
    units = list_dict_units(conn)
    unit_candidates: dict[str, dict[str, Any]] = {}
    for u in units:
        name = str(u.get("unit_name") or "").strip()
        if not name:
            continue
        item = unit_candidates.setdefault(
            _unit_key(name),
            {"unit_name": name, "frequencies": [], "score": 0},
        )
        item["frequencies"].extend(u.get("frequencies") if isinstance(u.get("frequencies"), list) else [])
    for row in session_rows_all:
        name = str(row.get("unit_name") or "").strip()
        if not name:
            continue
        item = unit_candidates.setdefault(
            _unit_key(name),
            {"unit_name": name, "frequencies": [], "score": 0},
        )
        item["frequencies"].append({"frequency": row.get("frequency"), "group": row.get("group")})
    for row in list_dict_callsigns(conn):
        name = str(row.get("unit_name") or "").strip()
        if not name:
            continue
        item = unit_candidates.setdefault(
            _unit_key(name),
            {"unit_name": name, "frequencies": [], "score": 0},
        )
        item["frequencies"].append({"frequency": row.get("frequency"), "group": row.get("group")})

    matched_units = []
    for item in unit_candidates.values():
        name = str(item.get("unit_name") or "")
        if not _unit_matches_query(name, terms, pairs):
            continue
        item["score"] = _unit_profile_score(name, terms, pairs)
        matched_units.append(item)
    if not matched_units:
        return None

    matched_units.sort(key=lambda u: (-int(u.get("score") or 0), str(u.get("unit_name") or "").lower()))
    primary = matched_units[0]
    unit_name = str(primary.get("unit_name") or "").strip()
    unit_key = _unit_key(unit_name)
    frequencies = primary.get("frequencies") if isinstance(primary.get("frequencies"), list) else []
    seen_pairs = set()
    freq_pairs = []
    for row in frequencies:
        pair = f"{row.get('frequency') or 'н/у'} / {row.get('group') or 'н/у'}"
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        freq_pairs.append(pair)

    session_rows = [r for r in session_rows_all if _unit_key(r.get("unit_name")) == unit_key]
    unique_events = {_row_key_for_search(r) for r in session_rows}
    unique_ids = sorted({str(r.get("id") or "") for r in session_rows if str(r.get("id") or "")})

    duty_text = "не определен"
    if session_rows:
        duty_findings = _build_duty_findings(session_rows, top_n=3)
        duty_units = duty_findings.get("units") if isinstance(duty_findings.get("units"), list) else []
        top_ids = duty_units[0].get("top_ids") if duty_units and isinstance(duty_units[0].get("top_ids"), list) else []
        if top_ids:
            main = top_ids[0]
            backups = ", ".join(
                f"ID {x.get('id')} ({x.get('appearances')} выходов)"
                for x in top_ids[1:3]
                if x.get("id")
            )
            duty_text = (
                f"ID {main.get('id')} ({main.get('appearances')} выходов, "
                f"{main.get('events_count')} уникальных сеансов)"
            )
            if backups:
                duty_text += f"; запасные: {backups}"

    callsigns = []
    for row in list_dict_callsigns(conn):
        if _unit_key(row.get("unit_name")) == unit_key:
            callsigns.append(row)
        if len(callsigns) >= 10:
            break

    important_terms = [
        "300",
        "200",
        "ранен",
        "убит",
        "погиб",
        "эвакуац",
        "враг",
        "обстрел",
        "удар",
        "дрон",
        "проблем",
        "жалоб",
        "не хватает",
        "срочно",
    ]
    intercept_rows = conn.execute(
        """
        SELECT i.session_id, i.unit_name, i.frequency, i.group_code, i.content,
               s.started_at, s.position_name
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id = i.session_id
        ORDER BY s.started_at DESC, i.id DESC
        LIMIT 5000
        """
    ).fetchall()
    important_intercepts = []
    for row in intercept_rows:
        if position_name != "__all__" and str(row["position_name"] or "") != position_name:
            continue
        if _unit_key(row["unit_name"]) != unit_key:
            continue
        content = re.sub(r"\s+", " ", str(row["content"] or "")).strip()
        hit_terms = [term for term in important_terms if term in content.lower()]
        if not hit_terms:
            continue
        idx = min([content.lower().find(t) for t in hit_terms if content.lower().find(t) >= 0] or [0])
        snippet = content[max(0, idx - 90) : idx + 230][:320]
        url = (
            f"/intercepts?session_id={quote(str(row['session_id'] or ''))}"
            f"&frequency={quote(str(row['frequency'] or ''))}"
            f"&group_code={quote(str(row['group_code'] or ''))}"
            f"&highlight={quote(hit_terms[0])}"
        )
        important_intercepts.append(
            {
                "started_at": str(row["started_at"] or ""),
                "frequency": str(row["frequency"] or ""),
                "group": str(row["group_code"] or ""),
                "terms": sorted(set(hit_terms)),
                "snippet": snippet,
                "url": url,
            }
        )
        if len(important_intercepts) >= 6:
            break

    lines = [f"### Профиль подразделения: {unit_name}"]
    document = _find_unit_document(unit_name=unit_name, question=question, terms=terms, pairs=pairs)
    if document:
        summary = _format_unit_document_summary(document)
        if summary:
            lines.append(summary)

    lines.append("\n#### Оперативные данные портала")
    lines.append(f"- **Известные сети:** {', '.join(freq_pairs[:8]) or 'не найдены'}.")
    lines.append(
        f"- **Сеансы сегодня:** {len(unique_events)} уникальных сеансов, "
        f"{len(session_rows)} выходов, {len(unique_ids)} ID."
    )
    lines.append(f"- **Предполагаемый оперативный дежурный:** {duty_text}.")

    if callsigns:
        cs_text = ", ".join(
            f"{c.get('label') or 'без имени'} ({c.get('code') or 'код н/у'})"
            for c in callsigns[:8]
        )
        lines.append(f"- **Позывные/метки:** {cs_text}.")
    else:
        lines.append("- **Позывные/метки:** не найдены.")

    if unique_ids:
        lines.append(f"- **Самые заметные ID сегодня:** {', '.join(unique_ids[:12])}.")

    if important_intercepts:
        lines.append("\n#### Важные перехваты")
        for item in important_intercepts:
            lines.append(
                f"- **{item['started_at']}** | **{item['frequency']} / {item['group']}**\n"
                f"  Признаки: {', '.join(item['terms'])}\n"
                f"  Фрагмент: {item['snippet']}\n"
                f"  Открыть бланк: {item['url']}"
            )
    else:
        lines.append("\n#### Важные перехваты\n- За найденный период критических фрагментов по подразделению не найдено.")

    if len(matched_units) > 1:
        variants = ", ".join(str(u.get("unit_name") or "") for u in matched_units[1:5])
        if variants:
            lines.append(f"\n#### Похожие совпадения\n{variants}.")

    return "\n".join(lines)


def _format_capability_answer() -> str:
    return get_capability_answer()


def _format_sessions_answer(conn, *, position_name: str, question: str) -> str:
    start, end = resolve_sessions_period(conn, question=question, position_name=position_name)
    rows = _sessions_rows(conn, start_ts=start, end_ts=end, position_name=position_name)
    if not rows:
        return f"### Сеансы\n\nЗа период {start} - {end} сеансов не найдено."
    if _is_duty_query(question):
        findings = _build_duty_findings(rows)
        return _format_duty_summary(findings)
    if _is_id_network_query(question):
        findings = _build_id_network_findings(rows)
        return _format_id_network_summary(findings)
    findings = _build_sessions_findings(rows, question=question)
    return _format_cross_unit_summary(findings)


def _format_id_profile_answer(conn, *, position_name: str, question: str) -> str | None:
    requested_id = _extract_requested_radio_id(question)
    if not requested_id:
        return None

    start, end = resolve_sessions_period(conn, question=question, position_name=position_name)
    rows = _sessions_rows(conn, start_ts=start, end_ts=end, position_name=position_name)
    id_rows = [row for row in rows if str(row.get("id") or "").strip() == requested_id]

    fallback_note = ""
    if not id_rows and any(x in _norm(question) for x in ("сегодня", "сутк", "день")):
        fallback_start = (datetime.now().replace(microsecond=0) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        fallback_end = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        rows = _sessions_rows(conn, start_ts=fallback_start, end_ts=fallback_end, position_name=position_name)
        id_rows = [row for row in rows if str(row.get("id") or "").strip() == requested_id]
        if id_rows:
            start, end = fallback_start, fallback_end
            fallback_note = "За сегодня выходов не найдено, показан расширенный поиск за последние 30 дней."

    if not id_rows:
        return (
            f"### Профиль ID {requested_id}\n\n"
            f"За период {start} - {end} сеансов с этим ID не найдено."
        )

    events_by_key: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        key = (str(row.get("date_time") or ""), str(row.get("frequency") or ""), str(row.get("group") or ""))
        events_by_key.setdefault(key, []).append(row)

    id_event_keys = []
    seen_keys = set()
    for row in id_rows:
        key = (str(row.get("date_time") or ""), str(row.get("frequency") or ""), str(row.get("group") or ""))
        if key not in seen_keys:
            seen_keys.add(key)
            id_event_keys.append(key)

    units = sorted(
        {
            str(row.get("unit_name") or "не указано")
            for row in id_rows
            if not _is_unknown_unit_name(row.get("unit_name"))
        }
    )
    channels = sorted({f"{row.get('frequency') or 'не указано'} / {row.get('group') or 'не указано'}" for row in id_rows})
    dates = sorted(str(row.get("date_time") or "") for row in id_rows if row.get("date_time"))
    peer_counts: dict[str, int] = {}
    peer_units: dict[str, set[str]] = {}
    cross_unit_events: list[str] = []
    own_unit_keys = {_unit_key(unit) for unit in units}
    for key in id_event_keys:
        participants = events_by_key.get(key, [])
        participant_ids = sorted({str(row.get("id") or "") for row in participants if str(row.get("id") or "")})
        participant_units = sorted(
            {
                str(row.get("unit_name") or "не указано")
                for row in participants
                if not _is_unknown_unit_name(row.get("unit_name"))
            }
        )
        for pid in participant_ids:
            if pid == requested_id:
                continue
            peer_counts[pid] = peer_counts.get(pid, 0) + 1
            for row in participants:
                if str(row.get("id") or "") == pid and not _is_unknown_unit_name(row.get("unit_name")):
                    peer_units.setdefault(pid, set()).add(str(row.get("unit_name") or ""))
        event_unit_keys = {_unit_key(unit) for unit in participant_units}
        if own_unit_keys and event_unit_keys - own_unit_keys:
            dt, freq, group = key
            cross_unit_events.append(
                f"{dt} | {freq} / {group} | подразделения: {', '.join(participant_units)} | ID: {', '.join(participant_ids)}"
            )

    top_peers = sorted(peer_counts.items(), key=lambda x: (-x[1], x[0]))[:8]
    lines = [f"### Профиль ID {requested_id}"]
    if fallback_note:
        lines.append(f"_{fallback_note}_")
    lines.extend(
        [
            "",
            "#### Краткий вывод",
            f"- **Период:** {start} - {end}.",
            f"- **Выходов ID:** {len(id_rows)}; **уникальных сеансов:** {len(id_event_keys)}.",
            f"- **Подразделения:** {', '.join(units) if units else 'привязка не указана'}.",
            f"- **Частоты/группы:** {', '.join(channels[:10])}.",
        ]
    )
    if dates:
        lines.append(f"- **Первый/последний выход:** {dates[0]} / {dates[-1]}.")

    lines.append("\n#### Корреспонденты рядом")
    if top_peers:
        for peer_id, count in top_peers:
            peer_unit_text = ", ".join(sorted(peer_units.get(peer_id) or [])) or "подразделение не указано"
            lines.append(f"- **ID {peer_id}**: вместе в сеансах {count} раз(а); {peer_unit_text}.")
    else:
        lines.append("- Другие ID в тех же сеансах не найдены.")

    lines.append("\n#### Последние сеансы")
    for key in list(reversed(id_event_keys))[:12]:
        dt, freq, group = key
        participants = events_by_key.get(key, [])
        participant_ids = sorted({str(row.get("id") or "") for row in participants if str(row.get("id") or "")})
        participant_units = sorted(
            {
                str(row.get("unit_name") or "не указано")
                for row in participants
                if not _is_unknown_unit_name(row.get("unit_name"))
            }
        )
        unit_text = ", ".join(participant_units) if participant_units else "подразделение не указано"
        lines.append(
            f"- **{dt}** | **{freq} / {group}** | {unit_text}\n"
            f"  Участники сеанса: {', '.join(participant_ids) or 'не указано'}."
        )

    lines.append("\n#### Межподразделенческие признаки")
    if cross_unit_events:
        lines.append("Найдены сеансы, где рядом присутствовали ID из других привязанных подразделений:")
        for item in cross_unit_events[:8]:
            lines.append(f"- {item}.")
    else:
        lines.append("Подтвержденных пересечений с другими привязанными подразделениями за период не найдено.")

    return "\n".join(lines)


def _format_unknown_unit_assignment_answer(conn, *, position_name: str, question: str) -> str | None:
    requested_id = _extract_requested_radio_id(question)
    if not requested_id:
        return None
    unit_hint = _extract_unit_hint_from_question(question)
    if not unit_hint:
        return None

    start, end = resolve_sessions_period(conn, question=question, position_name=position_name)
    rows = _sessions_rows(conn, start_ts=start, end_ts=end, position_name=position_name)
    id_rows = [row for row in rows if str(row.get("id") or "").strip() == requested_id]
    fallback_note = ""
    if not id_rows and any(x in _norm(question) for x in ("сегодня", "сутк", "день")):
        fallback_start = (datetime.now().replace(microsecond=0) - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        fallback_end = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
        rows = _sessions_rows(conn, start_ts=fallback_start, end_ts=fallback_end, position_name=position_name)
        id_rows = [row for row in rows if str(row.get("id") or "").strip() == requested_id]
        if id_rows:
            start, end = fallback_start, fallback_end
            fallback_note = "За сегодня выходов не найдено, показан расширенный поиск за последние 30 дней."

    if not id_rows:
        return f"### Привязка ID {requested_id}\n\nЗа период {start} - {end} этот ID в сеансах не найден."

    unknown_rows = [row for row in id_rows if _is_unknown_unit_name(row.get("unit_name"))]
    unique_unknown_pairs = sorted(
        {
            (str(row.get("frequency") or "").strip(), str(row.get("group") or "").strip())
            for row in unknown_rows
            if str(row.get("frequency") or "").strip() and str(row.get("group") or "").strip()
        }
    )
    if len(unique_unknown_pairs) > 25:
        return (
            f"### Привязка ID {requested_id}\n\n"
            f"Найдено слишком много пар частота/группа для автоматической записи: {len(unique_unknown_pairs)}.\n\n"
            "Чтобы не перезаписать лишнее, уточните период или конкретную частоту/группу."
        )
    applied_pairs: list[tuple[str, str]] = []
    apply_errors: list[str] = []
    seen_apply_pairs: set[tuple[str, str]] = set()
    for row in unknown_rows:
        frequency = str(row.get("frequency") or "").strip()
        group = str(row.get("group") or "").strip()
        if not frequency or not group:
            continue
        key = (frequency, group)
        if key in seen_apply_pairs:
            continue
        seen_apply_pairs.add(key)
        try:
            update_unit_name(conn, frequency, group, unit_hint)
            applied_pairs.append(key)
        except Exception as exc:
            apply_errors.append(f"{frequency} / {group}: {exc}")
    known_units = sorted(
        {
            str(row.get("unit_name") or "")
            for row in id_rows
            if not _is_unknown_unit_name(row.get("unit_name"))
        }
    )
    unit_terms = _unit_profile_query_terms(unit_hint)
    unit_pairs = _unit_profile_query_pairs(unit_hint)
    matching_known_units = [
        unit for unit in known_units if _unit_matches_query(unit, unit_terms, unit_pairs)
    ]

    lines = [f"### Привязка ID {requested_id} к подразделению"]
    if fallback_note:
        lines.append(f"_{fallback_note}_")
    lines.extend(
        [
            "",
            "#### Вывод",
            f"- Для строк, где подразделение не указано, рабочая подпись: **{unit_hint}**.",
            f"- Найдено выходов ID за период: **{len(id_rows)}**.",
            f"- Выходов с пустой привязкой подразделения: **{len(unknown_rows)}**.",
            f"- Автоматически записано в `unit`: **{len(applied_pairs)}** частота/группа.",
        ]
    )
    if matching_known_units:
        lines.append(f"- В известных привязках этого ID уже встречается похожее подразделение: **{', '.join(matching_known_units)}**.")
    elif known_units:
        lines.append(f"- Другие известные привязки этого ID за период: {', '.join(known_units)}.")
    else:
        lines.append("- Известных привязок подразделения для этого ID за период нет.")

    lines.append("\n#### Где было `не указано`")
    if unknown_rows:
        for row in list(reversed(unknown_rows))[:12]:
            lines.append(
                f"- **{row.get('date_time') or 'дата не указана'}** | "
                f"**{row.get('frequency') or 'не указано'} / {row.get('group') or 'не указано'}** | "
                f"указать подразделение: **{unit_hint}**."
            )
    else:
        lines.append("- За выбранный период строк с `не указано` для этого ID не найдено.")

    if applied_pairs:
        lines.append("\n#### Что записано в Unit")
        for frequency, group in applied_pairs[:12]:
            lines.append(f"- **{frequency} / {group}** -> **{unit_hint}**.")
        lines.append("Запись выполнена как ручная привязка (`manual=1`), чтобы синхронизация не перезаписала подразделение.")
    if apply_errors:
        lines.append("\n#### Ошибки записи")
        for error in apply_errors[:6]:
            lines.append(f"- {error}")
    return "\n".join(lines)


def _format_activity_answer(conn, *, position_name: str, question: str) -> str:
    start, end = resolve_sessions_period(conn, question=question, position_name=position_name)
    rows = _sessions_rows(conn, start_ts=start, end_ts=end, position_name=position_name)
    if rows:
        return f"Период: {start} - {end}\n\n{_format_unit_activity_summary(_build_unit_activity_findings(rows))}"
    clusters = get_network_intensity_clusters(
        conn,
        start_dt=start,
        end_dt=end,
        position_name=None if position_name == "__all__" else position_name,
    )
    if not clusters:
        return f"### Активность подразделений\n\nЗа период {start} - {end} активных кластеров не найдено."
    lines = [f"### Активность подразделений\n\nПериод: {start} - {end}"]
    for idx, row in enumerate(clusters[:15], start=1):
        lines.append(
            f"{idx}. **{row.get('unit_name') or 'не указано'}**: "
            f"сеансов {row.get('sessions')}, ID {row.get('correspondents')}."
        )
    return "\n".join(lines)


def _format_dictionary_answer(conn, *, position_name: str, question: str) -> str:
    src = _norm(question)
    freq, group = _extract_frequency_group(question)
    code_match = re.search(r"(?<!\d)(\d{3,10})(?!\d)", str(question or ""))

    wants_callsign = (
        "позыв" in src
        or ("кто" in src and code_match)
        or (code_match and not any(x in src for x in ("групп", "частот", "подраздел")))
    )
    if wants_callsign:
        callsigns = list_dict_callsigns(conn)
        q_code = code_match.group(1) if code_match else ""
        tokens = [t for t in re.findall(r"(?iu)[а-яa-z0-9]{3,}", src) if t not in {"позывной", "позывные", "что", "кто"}]
        rows = []
        for c in callsigns:
            hay = f"{c.get('code')} {c.get('label')} {c.get('unit_name')} {c.get('frequency')} {c.get('group')}".lower()
            if q_code and str(c.get("code") or "") != q_code:
                continue
            if not q_code and tokens and not any(t in hay for t in tokens):
                continue
            if position_name != "__all__" and c.get("position_name") and c.get("position_name") != position_name:
                continue
            rows.append(c)
            if len(rows) >= 12:
                break
        if not rows:
            return "### Справочник позывных\n\nСовпадений не найдено."
        lines = ["### Справочник позывных"]
        for c in rows:
            code_suffix = f" ({c.get('code')})" if c.get("code") else ""
            lines.append(
                f"- **{c.get('label') or 'без имени'}**"
                f"{code_suffix}: "
                f"{c.get('unit_name') or 'подразделение не указано'}, "
                f"{c.get('frequency') or 'частота н/у'} / {c.get('group') or 'группа н/у'}."
            )
        return "\n".join(lines)

    freqs = list_dict_frequencies(conn)
    rows = []
    for r in freqs:
        if freq and str(r.get("frequency") or "") != freq:
            continue
        if group and str(r.get("group") or "") != group:
            continue
        hay = f"{r.get('unit_name')} {r.get('frequency')} {r.get('group')}".lower()
        if not freq and not group:
            words = [w for w in re.findall(r"(?iu)[а-яa-z0-9]{3,}", src) if w not in {"частота", "частоты", "группа", "группы", "подразделение"}]
            if words and not any(w in hay for w in words):
                continue
        rows.append(r)
        if len(rows) >= 15:
            break
    if not rows:
        units = list_dict_units(conn)
        unit_rows = [u for u in units if any(t in str(u.get("unit_name") or "").lower() for t in re.findall(r"(?iu)[а-яa-z0-9]{3,}", src))]
        if not unit_rows:
            return "### Справочник\n\nСовпадений по частотам, группам или подразделениям не найдено."
        lines = ["### Справочник подразделений"]
        for u in unit_rows[:10]:
            lines.append(f"- **{u.get('unit_name')}**: частот/групп {len(u.get('frequencies') or [])}, последняя запись {u.get('last_recorded') or 'н/у'}.")
        return "\n".join(lines)
    lines = ["### Справочник частот и групп"]
    for r in rows:
        lines.append(
            f"- **{r.get('frequency')} / {r.get('group')}**: {r.get('unit_name') or 'подразделение не указано'}, "
            f"последняя запись: {r.get('last_recorded') or 'н/у'}."
        )
    return "\n".join(lines)


def _format_assignment_answer(conn, *, position_name: str, question: str) -> str | None:
    freq, group = _extract_frequency_group(question)
    if not freq or not group:
        return "### Назначения\n\nУкажите частоту и группу, например: `кто дежурный на 160.8260 G5558894`."
    groups_to_try = [group]
    if group.upper().startswith("G"):
        groups_to_try.append(group[1:])
    else:
        groups_to_try.append(f"G{group}")

    assignment_rows: list[tuple[str, dict[str, object], str]] = []
    if position_name == "__all__":
        rows = conn.execute(
            """
            SELECT DISTINCT position_name, group_code
            FROM analysis_assignments
            WHERE frequency=? AND group_code IN ({})
            ORDER BY position_name
            """.format(",".join("?" for _ in groups_to_try)),
            [freq] + groups_to_try,
        ).fetchall()
        for r in rows:
            pos = str(r["position_name"] or "")
            grp = str(r["group_code"] or "")
            assignment_rows.append(
                (
                    pos,
                    get_analysis_assignments(conn, position_name=pos, frequency=freq, group_code=grp),
                    grp,
                )
            )
    else:
        for grp in groups_to_try:
            found = get_analysis_assignments(
                conn,
                position_name=position_name,
                frequency=freq,
                group_code=grp,
            )
            if found:
                assignment_rows.append((position_name, found, grp))
                break
    if assignment_rows:
        assignments = assignment_rows[0][1]
        group = assignment_rows[0][2]
    else:
        assignments = {}
    if not assignments:
        return f"### Назначения\n\nДля {freq} / {group} назначений не найдено."
    lines = [f"### Назначения на {freq} / {group}"]
    for pos, assignments, grp in assignment_rows[:10]:
        duty = assignments.get("duty") if isinstance(assignments.get("duty"), list) else []
        battalion = str(assignments.get("battalion") or "")
        company = str(assignments.get("company") or "")
        prefix = f"**{pos or 'позиция не указана'}** ({freq} / {grp})"
        lines.append(f"- {prefix}: оперативные дежурные: {', '.join(duty) if duty else 'не назначены'}.")
        if battalion:
            lines.append(f"  Батальон: {battalion}.")
        if company:
            lines.append(f"  Рота: {company}.")
    return "\n".join(lines)


def _format_targeting_answer(portal_conn, *, user_id: int, position_name: str | None) -> str:
    items = list_targeting(
        portal_conn,
        user_id=user_id,
        position_name=None if position_name == "__all__" else position_name,
        include_read=False,
    )
    if not items:
        return "### Активные задачи\n\nНепрочитанных активных нацеливаний для вас сейчас нет."
    lines = ["### Активные задачи / нацеливания"]
    for item in items[:10]:
        lines.append(
            f"- **{item.get('title') or 'Без названия'}** ({item.get('created_at') or 'дата н/у'}): "
            f"{item.get('message') or ''}"
        )
    return "\n".join(lines)


def _format_intercept_search_answer(conn, *, position_name: str, question: str) -> str | None:
    terms = _search_terms_from_question(question)
    if not terms:
        return None
    rows_by_key: dict[tuple[int, str, str, str], dict[str, Any]] = {}
    for term in terms:
        for row in search_intercept_items(
            conn,
            query=term,
            position_name=None if position_name == "__all__" else position_name,
            limit=200,
        ):
            key = (
                int(row.get("session_id") or 0),
                str(row.get("frequency") or ""),
                str(row.get("group_code") or ""),
                str(row.get("content") or "")[:80],
            )
            if key not in rows_by_key:
                row = dict(row)
                row["_matched_terms"] = []
                rows_by_key[key] = row
            rows_by_key[key]["_matched_terms"].append(term)
    rows = list(rows_by_key.values())
    rows.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
    q = terms[0]
    if not rows:
        return f"### Поиск по данным проекта\n\nПо запросу `{_extract_search_query(question) or question}` совпадений в перехватах **по всем сменам в базе** не найдено."
    title = _extract_search_query(question) or ", ".join(terms[:4])
    lines = [
        f"### Поиск по данным проекта: `{title}`",
        f"Найдено совпадений в перехватах **по всем сменам в базе**: **{len(rows)}**. Ниже самые свежие.",
    ]
    for r in rows[:15]:
        snippet = re.sub(r"\s+", " ", str(r.get("content") or "")).strip()
        matched_terms = [str(t) for t in (r.get("_matched_terms") or [])]
        term_for_link = matched_terms[0] if matched_terms else q
        idx = -1
        for term in matched_terms or [q]:
            idx = snippet.lower().find(term.lower())
            if idx >= 0:
                term_for_link = term
                break
        if idx >= 0:
            snippet = snippet[max(0, idx - 90) : idx + len(term_for_link) + 170]
        snippet = snippet[:260]
        url = (
            f"/intercepts?session_id={quote(str(r.get('session_id') or ''))}"
            f"&frequency={quote(str(r.get('frequency') or ''))}"
            f"&group_code={quote(str(r.get('group_code') or ''))}"
            f"&highlight={quote(term_for_link)}"
        )
        lines.append(
            f"- **{r.get('unit_name') or 'не указано'}** | {r.get('started_at') or 'дата н/у'} | "
            f"{r.get('frequency')} / {r.get('group_code')} | термины: {', '.join(sorted(set(matched_terms))) or term_for_link}\n"
            f"  Фрагмент: {snippet}\n"
            f"  Открыть бланк: {url}"
        )
    return "\n".join(lines)


def _format_ml_answer(conn, *, position_name: str) -> str:
    where = ""
    params: list[Any] = []
    if position_name and position_name != "__all__":
        where = "WHERE position_name=?"
        params.append(position_name)
    rows = conn.execute(
        f"""
        SELECT id, position_name, start_ts, end_ts, model_version, top_label, top_probability,
               reasons_json, hotspots_json, created_at
        FROM ml_predictions
        {where}
        ORDER BY created_at DESC, id DESC
        LIMIT 5
        """,
        params,
    ).fetchall()
    if not rows:
        return "### ML-прогноз\n\nСохраненных ML-предсказаний пока нет."
    lines = ["### Последние ML-прогнозы"]
    for r in rows:
        lines.append(
            f"- **{r['top_label']}** ({float(r['top_probability'] or 0):.2f}) | "
            f"{r['start_ts']} - {r['end_ts']} | модель {r['model_version']} | создано {r['created_at']}."
        )
        reasons = str(r["reasons_json"] or "[]")
        if reasons and reasons != "[]":
            lines.append(f"  Причины: {reasons[:300]}")
    return "\n".join(lines)


class ProjectSearchTool:
    """Read-only project-wide search tool for EAVC Manager."""

    def __init__(
        self,
        *,
        conn,
        portal_conn=None,
        position_name: str,
        user_id: int | None = None,
    ) -> None:
        self.conn = conn
        self.portal_conn = portal_conn
        self.position_name = position_name
        self.user_id = user_id

    def search(self, question: str) -> str | None:
        plan = _ai_project_search_plan(question)
        terms = _merge_search_terms(plan.get("terms") or [], _search_terms_from_question(question))
        if not terms:
            terms = _ensure_non_empty_search_terms_for_project_search(question)
        if not terms:
            return None

        category = str(plan.get("category") or "") or _project_search_category(question)
        broad_scan = wants_broad_project_scan(question)
        operational_search = category in {
            "casualty",
            "killed",
            "supply",
            "morale",
            "combat",
            "evacuation",
            "anomaly",
        }
        explicit_sessions = _has_sessions_words(question)
        explicit_reference = _is_dictionary_query(question) or _is_assignment_query(question)
        planned_sources = set(plan.get("sources") or [])
        if not planned_sources or broad_scan:
            planned_sources = set(_PROJECT_SEARCH_SOURCES)
        if broad_scan:
            operational_search = False
            explicit_sessions = True

        sections: list[str] = []
        intercepts = ""
        intercept_rows: list[dict[str, Any]] = []
        if "intercepts" in planned_sources:
            intercept_rows = self._collect_intercept_rows(terms)
            intercepts = self._format_intercept_rows(question, terms, intercept_rows)
            if intercepts:
                sections.append(intercepts)

        if "sessions" in planned_sources and (explicit_sessions or not operational_search):
            sessions = self._search_sessions(question, terms)
            if sessions:
                sections.append(sessions)

        if explicit_reference or not operational_search:
            dictionaries = self._search_dictionaries(terms)
            if dictionaries and "dictionaries" in planned_sources:
                sections.append(dictionaries)

            assignments = self._search_assignments(terms)
            if assignments and "assignments" in planned_sources:
                sections.append(assignments)

        if "ai_reports" in planned_sources and (not operational_search or not intercepts or "отчет" in _norm(question)):
            reports = self._search_ai_reports(terms)
            if reports:
                sections.append(reports)

        if not operational_search:
            ml = self._search_ml_predictions(terms)
            if ml and "ml_predictions" in planned_sources:
                sections.append(ml)

            targeting = self._search_targeting(terms)
            if targeting and "targeting" in planned_sources:
                sections.append(targeting)

        query = _extract_search_query(question) or question
        plan_line = ""
        if plan:
            src_text = ", ".join(plan.get("sources") or []) or "основные источники"
            term_text = ", ".join(terms[:10])
            plan_line = (
                f"AI определил категорию: **{category or 'general'}**. "
                f"Ищу по источникам: {src_text}. Термины: {term_text}.\n\n"
            )
        if not sections:
            return (
                f"### Поиск по данным проекта: `{query}`\n\n"
                f"{plan_line}"
                "Совпадений в основных источниках не найдено.\n\n"
                "Проверены: перехваты, сеансы, справочники, назначения, AI-отчеты, ML-прогнозы и активные задачи."
            )
        if operational_search and _wants_report_answer(question):
            report = self._format_operational_report(
                question=question,
                category=category,
                terms=terms,
                rows=intercept_rows,
                extra_sections=sections[1:] if intercepts else sections,
            )
            if report:
                return report
        return (
            f"### Поиск по данным проекта: `{query}`\n\n"
            f"{plan_line}"
            "Ниже найденные факты по разделам.\n\n"
            + "\n\n".join(sections)
        )

    def _matches(self, text: str, terms: list[str]) -> bool:
        hay = _norm(text)
        return any(_norm(term) in hay for term in terms if str(term or "").strip())

    def _collect_intercept_rows(self, terms: list[str]) -> list[dict[str, Any]]:
        rows_by_key: dict[tuple[int, str, str, str], dict[str, Any]] = {}
        for term in terms:
            for row in search_intercept_items(
                self.conn,
                query=term,
                position_name=None if self.position_name == "__all__" else self.position_name,
                limit=200,
            ):
                key = (
                    int(row.get("session_id") or 0),
                    str(row.get("frequency") or ""),
                    str(row.get("group_code") or ""),
                    str(row.get("content") or "")[:80],
                )
                if key not in rows_by_key:
                    row = dict(row)
                    row["_matched_terms"] = []
                    rows_by_key[key] = row
                rows_by_key[key]["_matched_terms"].append(term)
        rows = list(rows_by_key.values())
        rows.sort(key=lambda r: str(r.get("started_at") or ""), reverse=True)
        return rows

    def _format_intercept_rows(self, question: str, terms: list[str], rows: list[dict[str, Any]]) -> str:
        if not rows:
            return ""
        lines = [f"#### Перехваты ({len(rows)}, все смены в базе)"]
        for row in rows[:15]:
            content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
            matched_terms = [str(t) for t in (row.get("_matched_terms") or [])]
            term_for_link = matched_terms[0] if matched_terms else terms[0]
            idx = -1
            for term in matched_terms or terms:
                idx = content.lower().find(str(term).lower())
                if idx >= 0:
                    term_for_link = str(term)
                    break
            if idx >= 0:
                content = content[max(0, idx - 90) : idx + len(term_for_link) + 170]
            content = content[:280]
            url = (
                f"/intercepts?session_id={quote(str(row.get('session_id') or ''))}"
                f"&frequency={quote(str(row.get('frequency') or ''))}"
                f"&group_code={quote(str(row.get('group_code') or ''))}"
                f"&highlight={quote(term_for_link)}"
            )
            lines.append(
                f"- **{row.get('unit_name') or 'не указано'}** | {row.get('started_at') or 'дата н/у'} | "
                f"{row.get('frequency')} / {row.get('group_code')} | термины: {', '.join(sorted(set(matched_terms))) or term_for_link}\n"
                f"  Фрагмент: {content}\n"
                f"  Открыть бланк: {url}"
            )
        return "\n".join(lines)

    def _search_intercepts(self, question: str, terms: list[str]) -> str:
        return self._format_intercept_rows(question, terms, self._collect_intercept_rows(terms))

    def _format_operational_report(
        self,
        *,
        question: str,
        category: str,
        terms: list[str],
        rows: list[dict[str, Any]],
        extra_sections: list[str],
    ) -> str:
        if not rows and not extra_sections:
            return ""
        category_title = {
            "casualty": "санитарных потерях / раненых",
            "killed": "санитарных потерях / 200-х",
            "supply": "проблемах обеспечения",
            "morale": "морально-психологических признаках",
            "combat": "боевых событиях",
            "evacuation": "эвакуации",
            "anomaly": "аномалиях и рисках",
        }.get(category or "", "выявленных событиях")
        lines = [
            f"### Расширенный доклад о {category_title}",
            "",
            "#### 1. Основание",
            "Доклад сформирован по найденным данным проекта. Сведения являются рабочими признаками и требуют проверки оператором/аналитиком.",
            "",
            "#### 2. Краткий вывод",
        ]
        if rows:
            units = sorted({str(r.get("unit_name") or "не указано") for r in rows})
            channels = sorted({f"{r.get('frequency') or 'не указано'} / {r.get('group_code') or 'не указано'}" for r in rows})
            lines.extend(
                [
                    f"- Найдено релевантных фрагментов в перехватах: {len(rows)}.",
                    f"- Подразделения: {', '.join(units[:8])}.",
                    f"- Частоты/группы: {', '.join(channels[:8])}.",
                ]
            )
        else:
            lines.append("- Прямые фрагменты перехватов не найдены, ниже приведены совпадения из других источников.")

        lines.extend(["", "#### 3. Зафиксированные факты"])
        for idx, row in enumerate(rows[:12], start=1):
            content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
            matched_terms = [str(t) for t in (row.get("_matched_terms") or [])]
            term_for_link = matched_terms[0] if matched_terms else (terms[0] if terms else "")
            idx_in_text = -1
            for term in matched_terms or terms:
                idx_in_text = content.lower().find(str(term).lower())
                if idx_in_text >= 0:
                    term_for_link = str(term)
                    break
            if idx_in_text >= 0:
                content = content[max(0, idx_in_text - 90) : idx_in_text + len(term_for_link) + 190]
            content = content[:320]
            url = (
                f"/intercepts?session_id={quote(str(row.get('session_id') or ''))}"
                f"&frequency={quote(str(row.get('frequency') or ''))}"
                f"&group_code={quote(str(row.get('group_code') or ''))}"
                f"&highlight={quote(term_for_link)}"
            )
            lines.append(
                f"{idx}. **{row.get('unit_name') or 'не указано'}**\n"
                f"- Дата/смена: {row.get('started_at') or 'дата не указана'}.\n"
                f"- Частота/группа: {row.get('frequency') or 'не указано'} / {row.get('group_code') or 'не указано'}.\n"
                f"- Совпавшие признаки: {', '.join(sorted(set(matched_terms))) or term_for_link or 'не указано'}.\n"
                f"- Фрагмент: {content or 'не указано'}.\n"
                f"- Открыть бланк: {url}"
            )

        lines.extend(
            [
                "",
                "#### 4. Оценка",
                "- Информацию считать предварительной до сверки с исходным бланком и смежными сеансами.",
                "- Не смешивать текстовые упоминания с подтвержденной статистикой потерь или обеспеченности.",
                "- При наличии количества в речи фиксировать его как заявленное в перехвате, а не как установленный факт.",
                "",
                "#### 5. Рекомендации аналитику",
                "- Открыть исходные бланки по ссылкам и проверить полный контекст переговоров.",
                "- Сверить событие с соседними частотами, группами и последующими сменами.",
                "- При необходимости сформировать отдельную карточку события по подразделению, частоте и группе.",
            ]
        )
        if extra_sections:
            lines.extend(["", "#### 6. Дополнительные совпадения", *extra_sections[:3]])
        return "\n".join(lines)

    def _search_sessions(self, question: str, terms: list[str]) -> str:
        src = _norm(question)
        numeric_terms = [t for t in terms if re.fullmatch(r"\d{2,12}", str(t or ""))]
        explicit_sessions = (
            bool(re.search(r"(?iu)(?<![а-яa-z])(?:айди\w*|id)(?![а-яa-z])", src))
            or any(x in src for x in ("сеанс", "частот", "групп", "подраздел"))
        )
        # Casualty shorthand like "300" should search intercept text, not radio IDs.
        if numeric_terms and all(str(t) in {"200", "300"} for t in numeric_terms) and not explicit_sessions:
            return ""
        if not numeric_terms and not explicit_sessions:
            return ""
        start, end = resolve_sessions_period(
            self.conn, question=question, position_name=self.position_name
        )
        rows = _sessions_rows(self.conn, start_ts=start, end_ts=end, position_name=self.position_name)
        hits = []
        for row in rows:
            hay = f"{row.get('id')} {row.get('unit_name')} {row.get('frequency')} {row.get('group')}"
            if self._matches(hay, terms):
                hits.append(row)
            if len(hits) >= 20:
                break
        if not hits:
            return ""
        lines = [f"#### Сеансы ({len(hits)} из периода {start} - {end})"]
        for row in hits[:12]:
            same_event = [
                str(x.get("id") or "")
                for x in rows
                if _row_key_for_search(x) == _row_key_for_search(row) and str(x.get("id") or "")
            ][:40]
            lines.append(
                f"- {row.get('date_time')} | **ID {row.get('id')}** | "
                f"{row.get('unit_name') or 'подразделение н/у'} | {row.get('frequency')} / {row.get('group')} | "
                f"все ID в сеансе: {', '.join(sorted(set(same_event))) or 'не указано'}."
            )
        return "\n".join(lines)

    def _search_dictionaries(self, terms: list[str]) -> str:
        hits: list[str] = []
        for row in list_dict_callsigns(self.conn)[:5000]:
            hay = f"{row.get('code')} {row.get('label')} {row.get('unit_name')} {row.get('frequency')} {row.get('group')}"
            if self._matches(hay, terms):
                code = f" ({row.get('code')})" if row.get("code") else ""
                hits.append(
                    f"- Позывной: **{row.get('label') or 'без имени'}**{code}, "
                    f"{row.get('unit_name') or 'подразделение н/у'}, {row.get('frequency') or 'частота н/у'} / {row.get('group') or 'группа н/у'}."
                )
            if len(hits) >= 8:
                break
        if len(hits) < 8:
            for row in list_dict_frequencies(self.conn)[:5000]:
                hay = f"{row.get('unit_name')} {row.get('frequency')} {row.get('group')} {row.get('last_recorded')}"
                if self._matches(hay, terms):
                    hits.append(
                        f"- Сеть: **{row.get('frequency')} / {row.get('group')}** — "
                        f"{row.get('unit_name') or 'подразделение н/у'}, последняя запись {row.get('last_recorded') or 'н/у'}."
                    )
                if len(hits) >= 12:
                    break
        if not hits:
            return ""
        return "#### Справочники\n" + "\n".join(hits[:12])

    def _search_assignments(self, terms: list[str]) -> str:
        try:
            rows = self.conn.execute(
                """
                SELECT position_name, frequency, group_code, role_type, callsign_code
                FROM analysis_assignments
                ORDER BY position_name, frequency, group_code, role_type
                LIMIT 5000
                """
            ).fetchall()
        except Exception:
            return ""
        hits = []
        for row in rows:
            hay = f"{row['position_name']} {row['frequency']} {row['group_code']} {row['role_type']} {row['callsign_code']}"
            if self._matches(hay, terms):
                hits.append(
                    f"- **{row['position_name'] or 'позиция н/у'}** | {row['frequency']} / {row['group_code']} | "
                    f"{row['role_type']}: {row['callsign_code'] or 'не назначено'}."
                )
            if len(hits) >= 10:
                break
        if not hits:
            return ""
        return "#### Назначения\n" + "\n".join(hits)

    def _search_ai_reports(self, terms: list[str]) -> str:
        try:
            rows = self.conn.execute(
                """
                SELECT id, report_type, report_text, created_at
                FROM ai_reports
                ORDER BY created_at DESC, id DESC
                LIMIT 200
                """
            ).fetchall()
        except Exception:
            return ""
        hits = []
        for row in rows:
            text = str(row["report_text"] or "")
            if not self._matches(f"{row['report_type']} {text}", terms):
                continue
            snippet = re.sub(r"\s+", " ", text).strip()[:260]
            hits.append(f"- AI-отчет #{row['id']} ({row['report_type']}, {row['created_at']}): {snippet}")
            if len(hits) >= 6:
                break
        if not hits:
            return ""
        return "#### AI-отчеты\n" + "\n".join(hits)

    def _search_ml_predictions(self, terms: list[str]) -> str:
        try:
            rows = self.conn.execute(
                """
                SELECT id, position_name, start_ts, end_ts, model_version, top_label,
                       top_probability, reasons_json, hotspots_json, created_at
                FROM ml_predictions
                ORDER BY created_at DESC, id DESC
                LIMIT 100
                """
            ).fetchall()
        except Exception:
            return ""
        hits = []
        for row in rows:
            hay = (
                f"{row['position_name']} {row['top_label']} {row['model_version']} "
                f"{row['reasons_json']} {row['hotspots_json']}"
            )
            if self._matches(hay, terms):
                hits.append(
                    f"- ML #{row['id']}: **{row['top_label']}** ({float(row['top_probability'] or 0):.2f}) | "
                    f"{row['position_name']} | {row['start_ts']} - {row['end_ts']}."
                )
            if len(hits) >= 6:
                break
        if not hits:
            return ""
        return "#### ML-прогнозы\n" + "\n".join(hits)

    def _search_targeting(self, terms: list[str]) -> str:
        if self.portal_conn is None or not self.user_id:
            return ""
        try:
            items = list_targeting(
                self.portal_conn,
                user_id=int(self.user_id),
                position_name=None if self.position_name == "__all__" else self.position_name,
                include_read=True,
            )
        except Exception:
            return ""
        hits = []
        for item in items:
            hay = f"{item.get('title')} {item.get('message')} {item.get('target_position')} {item.get('created_by')}"
            if self._matches(hay, terms):
                hits.append(
                    f"- **{item.get('title') or 'Без названия'}** ({item.get('created_at') or 'дата н/у'}): "
                    f"{item.get('message') or ''}"
                )
            if len(hits) >= 8:
                break
        if not hits:
            return ""
        return "#### Targeting / задачи\n" + "\n".join(hits)


def _row_key_for_search(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("date_time") or ""),
        str(row.get("frequency") or ""),
        str(row.get("group") or ""),
    )


def _format_project_search_answer(
    conn,
    *,
    position_name: str,
    question: str,
    portal_conn=None,
    user_id: int | None = None,
) -> str | None:
    return ProjectSearchTool(
        conn=conn,
        portal_conn=portal_conn,
        position_name=position_name,
        user_id=user_id,
    ).search(question)


def route_ai_question(
    *,
    conn,
    portal_conn=None,
    question: str,
    position_name: str,
    user_id: int | None = None,
    force_project_search: bool = False,
) -> str | None:
    """Return a deterministic, data-backed answer for known assistant intents.

    force_project_search: не отбрасывать запрос на финальном шаге, если вопрос не
    уложился в эвристики «нужен ли широкий поиск» — для свободного AI-чата.
    В этом случае вызывается ``_format_project_search_answer``; результат может
    быть None, если поиск не дал ни одного блока текста.
    """
    raw_q = str(question or "").strip()
    if not raw_q:
        return None
    q = normalize_user_search_question(raw_q)
    if not q:
        return None

    if has_explicit_project_search_prefix(raw_q):
        ans = _format_project_search_answer(
            conn,
            portal_conn=portal_conn,
            question=q,
            position_name=position_name,
            user_id=user_id,
        )
        if ans:
            return ans

    if _is_capability_question(q):
        return _format_capability_answer()
    if _is_unit_profile_query(q):
        unit_profile = _format_unit_profile_answer(conn, position_name=position_name, question=q)
        if unit_profile:
            return unit_profile
    if _is_targeting_query(q) and portal_conn is not None and user_id:
        return _format_targeting_answer(portal_conn, user_id=int(user_id), position_name=position_name)
    if _is_unknown_unit_assignment_query(q):
        unit_assignment = _format_unknown_unit_assignment_answer(conn, position_name=position_name, question=q)
        if unit_assignment:
            return unit_assignment
    if _is_id_profile_query(q):
        id_profile = _format_id_profile_answer(conn, position_name=position_name, question=q)
        if id_profile:
            return id_profile
    if _is_activity_query(q):
        return _format_activity_answer(conn, position_name=position_name, question=q)
    if _is_assignment_query(q):
        return _format_assignment_answer(conn, position_name=position_name, question=q)
    if _wants_text_mention_search(q):
        ans = _format_project_search_answer(
            conn,
            portal_conn=portal_conn,
            question=q,
            position_name=position_name,
            user_id=user_id,
        )
        if ans:
            return ans
    if _is_intercept_search_query(q) and not _has_sessions_words(q):
        ans = _format_project_search_answer(
            conn,
            portal_conn=portal_conn,
            question=q,
            position_name=position_name,
            user_id=user_id,
        )
        if ans:
            return ans
    if _is_sessions_query(q):
        return _format_sessions_answer(conn, position_name=position_name, question=q)
    if _is_intercept_search_query(q):
        ans = _format_intercept_search_answer(conn, position_name=position_name, question=q)
        if ans:
            return ans
    if _is_ml_query(q):
        return _format_ml_answer(conn, position_name=position_name)
    if _is_dictionary_query(q):
        return _format_dictionary_answer(conn, position_name=position_name, question=q)
    if not force_project_search and not _should_attempt_project_search(q):
        return None
    return _format_project_search_answer(
        conn,
        portal_conn=portal_conn,
        question=q,
        position_name=position_name,
        user_id=user_id,
    )
