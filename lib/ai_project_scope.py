"""
Единое описание области данных EAVC Manager для AI-планировщика и поиска.

Используется в ai_assistant (выбор инструментов), ai_agent_tools (синтез ответа),
ai_router (план широкого поиска, справка «что умею»).
"""

from __future__ import annotations

# Источники, которые обходит ProjectSearchTool.search()
PROJECT_SEARCH_SOURCE_IDS: frozenset[str] = frozenset(
    {
        "intercepts",
        "sessions",
        "dictionaries",
        "assignments",
        "ai_reports",
        "ml_predictions",
        "targeting",
    }
)

PROJECT_DATA_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "intercepts",
        "Бланки перехватов (intercept_items): текст эфира по всем сменам позиции, "
        "частота, группа, подразделение, ссылки на бланк.",
    ),
    (
        "sessions",
        "Сеансы связи (seanses): ID корреспондентов, частоты, группы, подразделения, "
        "дежурные, пересечения по сетям; активные и архивные строки.",
    ),
    (
        "dictionaries",
        "Справочники: частоты, группы, подразделения, позывные (dict_*).",
    ),
    (
        "assignments",
        "Назначения Unit / analysis_assignments: привязка подразделения к паре частота+группа.",
    ),
    (
        "ai_reports",
        "Ранее сохранённые AI-отчёты и сводки по сменам/периодам.",
    ),
    (
        "ml_predictions",
        "ML-прогнозы и пояснения (ml_predictions).",
    ),
    (
        "targeting",
        "Задачи и нацеливания (targeting) в auth-БД портала.",
    ),
)

_PLANNER_MISSION = """
Миссия ассистента по данным портала:
- Любой вопрос о фактах, событиях, ID, подразделениях, частотах, упоминаниях, рисках, "
  "жалобах, потерях, снабжении — сначала искать по **всем релевантным источникам проекта**, "
  "а не отвечать «из головы» и не ограничиваться одной вкладкой UI.
- «По всему проекту / везде / пройдись / что есть в базе» — широкий поиск "
  "`route_project` с `force_project_search: true` и `synthesize: true` (все источники ниже).
- Перехваты: по **всем сменам** в БД, если не указана одна конкретная смена.
- Сеансы: по **всей таблице** (архив + активные), если не указан узкий период.
- Различай: бланки перехватов (одна смена → `shift_summary`) vs таблица сеансов (`sessions_analysis`).
- Запись в Unit — только при явной команде пользователя (`apply_unit_assignment`).
""".strip()


def _sources_block(*, for_search_planner: bool) -> str:
    lines = ["Источники данных проекта (read-only поиск):"]
    for sid, desc in PROJECT_DATA_SOURCES:
        if for_search_planner:
            lines.append(f"- {sid}: {desc}")
        else:
            lines.append(f"- **{sid}** — {desc}")
    return "\n".join(lines)


def get_planner_scope_block() -> str:
    """Блок для system_prompt динамического планировщика (ai_assistant)."""
    return f"{_PLANNER_MISSION}\n\n{_sources_block(for_search_planner=False)}"


def get_search_planner_scope_block() -> str:
    """Блок для _ai_project_search_plan (ai_router)."""
    ids = ", ".join(sorted(PROJECT_SEARCH_SOURCE_IDS))
    return (
        f"{_PLANNER_MISSION}\n\n"
        f"{_sources_block(for_search_planner=True)}\n\n"
        f"Допустимые значения sources в JSON: {ids}. "
        "При сомнении включай intercepts и sessions; для справочных вопросов — dictionaries; "
        "для «по всему проекту» — все перечисленные sources."
    )


def get_assistant_rag_scope_block() -> str:
    """Напоминание для синтеза ответа после route_project (ai_agent_tools)."""
    return (
        "Область портала: ответ строится по выдаче поиска по проекту — перехваты (все смены, "
        "если не оговорена одна), сеансы связи, справочники, назначения Unit, AI-отчёты, "
        "ML и задачи targeting. Это одна выборка, не гарантия полноты всей БД; если в блоке "
        "нет фрагмента — не утверждай, что его нигде нет, сформулируй: «в этой выдаче не найдено»."
    )


def get_capability_answer() -> str:
    """Текст для вопросов «что ты умеешь / где ищешь»."""
    examples = (
        "#### Примеры запросов\n"
        "- Найди по всему проекту упоминания «эвакуация».\n"
        "- Были ли жалобы на снабжение в перехватах или сеансах?\n"
        "- Проверь ID 191500 в других подразделениях.\n"
        "- Что известно про 425 ошп «Скала»?\n"
        "- Аномалии за вчера — в сеансах, не в бланках.\n"
        "- Сводка по перехватам за смену 20.02.\n\n"
        "Префиксы для явного поиска: `поиск: …`, `по проекту: …`, `только перехваты: …`.\n"
    )
    return (
        "### Что я могу делать\n\n"
        "Я работаю с **данными всего проекта** EAVC Manager: сначала подбираю источники и термины, "
        "затем ищу факты и отвечаю по-русски, без выдуманных цифр и событий.\n\n"
        f"{examples}"
        f"{_sources_block(for_search_planner=False)}\n\n"
        "Для широкого вопроса без уточнения вкладки используйте формулировки вроде "
        "«по всему проекту», «найди везде», «поиск: …»."
    )


def wants_broad_project_scan(question: str) -> bool:
    """Запрос явно требует обхода всех источников, а не узкого среза."""
    src = str(question or "").strip().lower().replace("ё", "е")
    if not src:
        return False
    markers = (
        "по всему проекту",
        "по всему порталу",
        "по всему проекте",
        "по всей базе",
        "по всем данным",
        "по всем разделам",
        "по всем источникам",
        "везде в проекте",
        "везде в базе",
        "пройдись по",
        "пройди по",
        "посмотри везде",
        "что есть в проекте",
        "что есть в базе",
        "по проекту:",
        "по проекту ",
    )
    return any(m in src for m in markers)
