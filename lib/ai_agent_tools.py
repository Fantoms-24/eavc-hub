from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from web_portal.lib.ai_client import generate_ai_text
from web_portal.lib.ai_project_scope import get_assistant_rag_scope_block
from web_portal.lib.ai_reports import run_shift_summary
from web_portal.lib.ai_router import route_ai_question
from web_portal.lib.ai_sessions import resolve_sessions_period, run_sessions_ai_analysis
from web_portal.lib.db import connect, get_intercept_session, list_intercept_sessions_ordered


RISK_READ = "read"
RISK_SAFE_WRITE = "safe_write"
RISK_BULK_WRITE = "bulk_write"
RISK_ADMIN_WRITE = "admin_write"


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    risk: str
    required_permission: str = ""
    handler: Callable[["ToolContext", dict[str, Any]], "ToolResult"] | None = None

    @property
    def writes(self) -> bool:
        return self.risk in {RISK_SAFE_WRITE, RISK_BULK_WRITE, RISK_ADMIN_WRITE}


@dataclass
class ToolContext:
    portal_conn: Any
    main_db_path: Path
    position_name: str
    user_id: int
    user_role: str
    created_by: str
    memory: Any
    can_use_position: Callable[[str], bool]


@dataclass
class ToolResult:
    tool: str
    title: str
    content: str
    actions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    changed: bool = False


_SCOPE_HINT = get_assistant_rag_scope_block()

_FREE_SYSTEM = (
    "Ты ассистент в чате EAVC Manager. Отвечай на русском, без вставок на других языках. "
    "Ориентир — последнее сообщение пользователя: не повторяй готовый ответ на прошлый вопрос, если сейчас "
    "задан новый (даты, окно часов, «открой карточку» и т.д.). "
    "Пойми суть и ответь по делу, без шаблонных разделов. Не выдумывай факты из БД портала. "
    "Вопросы о событиях, ID, подразделениях и упоминаниях требуют обращения к данным проекта "
    "(перехваты, сеансы, справочники, назначения, отчёты, ML, задачи) — не отвечай общими фразами без поиска. "
    "Просьба открыть вкладку/карточку в интерфейсе: из чата экран не открывается — скажи это кратко и по делу "
    "(например, в каком разделе портала пользователь обычно смотрит такие сведения), без длинных отмазок. "
    "Контекст чата используй для местоимений и связи тем, но не подменяй им новый вопрос."
)

_RAG_SYSTEM = (
    "Ты ассистент EAVC Manager. Ниже — результат поиска по порталу (одна выборка, не вся БД целиком). "
    f"{_SCOPE_HINT} "
    "Поиск по перехватам выполняется **по всем сменам в базе**, а не только по последней или выбранной в UI, "
    "если пользователь явно не просил одну конкретную смену. "
    "Поиск и анализ **сеансов связи** — по всей таблице сеансов в базе (активные + архив), "
    "если пользователь не указал конкретную дату или период. "
    "Ответ пиши на русском, без иероглифов и без вставок на других языках. "
    "Главное — последнее сообщение пользователя: не отвечай на предыдущий вопрос, если текущий другой "
    "(время суток, дата, «аномалии за вчера», карточка подразделений). "
    "Опирайся на факты из блока; цифры, ID, частоты, даты — только если они явно есть в тексте выдачи. "
    "Различай: (а) в этой выборке нет строк под узкий фильтр (например только 10–13 ч) — скажи честно, "
    "что именно в выдаче есть и чего в ней нет, не утверждай «в базе портала ничего нет» глобально; "
    "(б) выдача пустая — кратко опиши и не раздувай общие фразы «обратитесь к другим источникам». "
    "Не пиши «за выбранную смену», если в выдаче поиск идёт по всем сменам. "
    "Если в выдаче уже есть события по дате/подразделению, а пользователь уточняет только окно часов — "
    "сверь время в фрагментах; если в тексте нет попадания в окно, так и сформулируй. "
    "Стиль: ясно, по делу, без лишних извинений и консультационного блейда."
)
_MILITARY_REPORT_SYSTEM = (
    "Ты ассистент EAVC Manager. Пользователь просит оформить **военно-деловой доклад** "
    "по уже готовому тексту (обычно это ваш предыдущий ответ в чате). "
    "Пиши на русском, структурированно, без выдуманных фактов — только переработка исходника.\n"
    "Структура:\n"
    "1. **Основание** — откуда сведения (ответ ассистента / чат).\n"
    "2. **Краткая обстановка** — суть в 2–4 пунктах.\n"
    "3. **Основные выводы** — главное по делу.\n"
    "4. **Необходимо уточнить** — 2–4 пункта, если в исходнике есть пробелы.\n"
    "Не добавляй события, цифры и ID, которых нет в исходном тексте."
)

_ECHO_FAIL_TEXT = (
    "По этому сообщению не удалось сформировать ответ: повторена только формулировка вопроса. "
    "Переформулируйте запрос с явным **ID** и периодом (например: «ID 160 — в каких ещё подразделениях "
    "были сеансы за сегодня») или воспользуйтесь поиском / вкладкой «Сеансы» в портале."
)


def _looks_like_echo_user_block_only(text: str, question: str) -> bool:
    t = str(text or "").strip()
    q = str(question or "").strip()
    if not q:
        return False
    if t == q:
        return True
    if t == f"Сообщение пользователя:\n{q}":
        return True
    if t.startswith("Сообщение пользователя:") and q in t and len(t) <= len(q) + 40:
        return True
    return False


def _freeform_assistant_reply(
    ctx: ToolContext,
    *,
    question: str,
    portal_context: str = "",
    rag_synthesis: bool = False,
    style: str = "",
) -> str:
    memory_text = str(getattr(ctx.memory, "recent_text", "") or "")
    if style == "military_report" and (portal_context or "").strip():
        system = _MILITARY_REPORT_SYSTEM
        rag_synthesis = True
    else:
        system = _RAG_SYSTEM if rag_synthesis else _FREE_SYSTEM
    user_block = f"Сообщение пользователя:\n{question}"
    if (portal_context or "").strip() or rag_synthesis:
        source_label = (
            "Исходный текст для доклада:\n"
            if style == "military_report"
            else "Сырые данные поиска по порталу:\n"
        )
        user_block = (
            f"{source_label}"
            f"{(portal_context or '— выдача пуста или без релевантных фрагментов.').strip()[:14000]}\n\n"
            f"{user_block}"
        )
    extra = ""
    if rag_synthesis:
        extra = (
            "\n\nНапоминание: отвечай только на последнее сообщение пользователя выше; "
            "не дублируй ответ про прошлый запрос (например про 20 февраля 10–13), если новый запрос про другое."
        )
    text = str(
        generate_ai_text(
            system_prompt=system,
            user_prompt=f"Контекст чата:\n{memory_text[-4000:]}\n\n{user_block}{extra}",
            temperature=0.5 if rag_synthesis else 0.55,
            max_tokens=2200,
        )["text"]
        or ""
    ).strip()
    if (
        _looks_like_echo_user_block_only(text, question)
        and not (portal_context or "").strip()
        and not rag_synthesis
    ):
        mconn = connect(ctx.main_db_path)
        try:
            raw = route_ai_question(
                conn=mconn,
                portal_conn=ctx.portal_conn,
                question=question,
                position_name=ctx.position_name,
                user_id=ctx.user_id,
                force_project_search=True,
            )
        finally:
            mconn.close()
        if (raw or "").strip():
            return _freeform_assistant_reply(
                ctx,
                question=question,
                portal_context=str(raw or ""),
                rag_synthesis=True,
            )
        return _ECHO_FAIL_TEXT
    return text


def _norm_assistant(s: str) -> str:
    return str(s or "").strip().lower().replace("ё", "е")


def _coerce_positive_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def _coerce_non_negative_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _assert_intercept_session_access(ctx: ToolContext, mconn, session_id: int) -> None:
    if str(ctx.position_name or "").strip() in ("", "__all__"):
        return
    sess = get_intercept_session(mconn, int(session_id))
    if not sess:
        raise ValueError("Смена не найдена")
    sp = str(sess.get("position_name") or "").strip()
    want = str(ctx.position_name or "").strip()
    if sp and sp != want:
        raise ValueError("Нет доступа к выбранной смене")


def _parse_day_yyyy_mm_dd(text: str) -> str | None:
    m = re.search(
        r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b",
        str(text or ""),
    )
    if not m:
        return None
    d, mo, y_raw = int(m[1]), int(m[2]), m[3]
    if y_raw:
        y = int(y_raw)
        if len(str(y_raw)) <= 2:
            y = 2000 + y
    else:
        y = datetime.now().year
    try:
        return datetime(y, mo, d).date().isoformat()
    except ValueError:
        return None


def _session_overlaps_day(started: str, ended: str, ymd: str) -> bool:
    s10 = (started or "")[:10]
    e10 = (ended or "")[:10] or "9999-12-31"
    if not s10:
        return False
    return s10 <= ymd <= e10


def _pick_intercept_session_id_by_day(sessions: list[dict], ymd: str) -> int | None:
    for x in sessions:
        if (x.get("started_at") or "")[:10] == ymd:
            return int(x["id"])
    for x in sessions:
        if _session_overlaps_day(
            str(x.get("started_at") or ""),
            str(x.get("ended_at") or ""),
            ymd,
        ):
            return int(x["id"])
    return None


def _parse_shift_index_from_args_and_question(
    args: dict[str, Any], question: str
) -> int | None:
    si = _coerce_non_negative_int(args.get("shift_index"))
    if si is not None:
        return si
    q = _norm_assistant(question)
    if re.search(r"предыдущ", q) and "смен" in q:
        return 1
    if re.search(r"прошл(ой|ая|ую|ы[йх])?\s+смен", q):
        return 1
    m = re.search(r"(\d+)\s*смен\s*назад", q)
    if m:
        return int(m.group(1))
    return None


def _resolve_shift_session_id(
    mconn, ctx: ToolContext, args: dict[str, Any], question: str
) -> int | None:
    """
    session_id: явный id; иначе дата/смещение по списку смен.
    None — «последняя смена» (поведение run_shift_summary по умолчанию).
    """
    ex = _coerce_positive_int(args.get("session_id"))
    if ex is not None:
        _assert_intercept_session_access(ctx, mconn, ex)
        return ex

    pos = str(ctx.position_name or "").strip()
    sessions = list_intercept_sessions_ordered(mconn, pos, limit=100)
    if not sessions:
        return None

    df = str(args.get("date_from") or "").strip()
    d_to = str(args.get("date_to") or "").strip()
    ymd: str | None = None
    if df and re.match(r"^\d{4}-\d{2}-\d{2}", df):
        ymd = df[:10]
    if ymd is None:
        ymd = _parse_day_yyyy_mm_dd(f"{question} {df} {d_to}")

    if ymd and (not d_to or d_to[:10] == ymd or d_to == df):
        picked = _pick_intercept_session_id_by_day(sessions, ymd)
        if picked is not None:
            _assert_intercept_session_access(ctx, mconn, picked)
            return picked

    if df and d_to and re.match(r"^\d{4}-\d{2}-\d{2}", df) and re.match(
        r"^\d{4}-\d{2}-\d{2}", d_to
    ):
        a, b = df[:10], d_to[:10]
        if a <= b:
            for x in sessions:
                s0 = (x.get("started_at") or "")[:10]
                e0 = (x.get("ended_at") or "")[:10] or "9999-12-31"
                if s0 and a <= s0 <= b:
                    sid = int(x["id"])
                    _assert_intercept_session_access(ctx, mconn, sid)
                    return sid
            for x in sessions:
                s0 = (x.get("started_at") or "")[:10]
                e0 = (x.get("ended_at") or "")[:10] or "9999-12-31"
                if s0 and not (b < s0 or a > e0):
                    sid = int(x["id"])
                    _assert_intercept_session_access(ctx, mconn, sid)
                    return sid

    idx = _parse_shift_index_from_args_and_question(args, question)
    if idx is not None and 0 <= idx < len(sessions):
        sid = int(sessions[idx]["id"])
        _assert_intercept_session_access(ctx, mconn, sid)
        return sid
    return None


def _general_chat(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    canned = str(args.get("canned") or "").strip()
    if canned:
        return ToolResult(
            tool="general_chat", title="Ответ ассистента", content=canned
        )
    question = str(args.get("question") or "").strip()
    portal_context = str(args.get("portal_context") or "").strip()
    style = str(args.get("style") or "").strip()
    rag = bool(args.get("rag_synthesis")) or bool(portal_context)
    text = _freeform_assistant_reply(
        ctx,
        question=question,
        portal_context=portal_context,
        rag_synthesis=rag,
        style=style,
    )
    if not (text or "").strip():
        text = _ECHO_FAIL_TEXT
    title = "Военно-деловой доклад" if style == "military_report" else "Обычный AI-ответ"
    return ToolResult(tool="general_chat", title=title, content=text)


def _shift_summary(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    question = str(args.get("question") or "").strip()
    memory_text = str(getattr(ctx.memory, "recent_text", "") or "")
    focus_query = question
    qn = question.lower().replace("ё", "е")
    time_or_date_followup = bool(
        re.search(r"\d{1,2}[./]\d{1,2}", question)
        or re.search(r"\b(сегодня|вчера|завтра)\b", qn)
        or re.search(r"\bчас(а|ов|ы)?\b", qn)
        or re.search(r"\b\d{1,2}\s*[-–]\s*\d{1,2}\b", qn)
    )
    if memory_text and (
        any(term in qn for term in ("отчет", "отчёт", "доклад", "полный", "расшир"))
        or time_or_date_followup
        or any(term in qn for term in ("смен", "что было", "аномал", "подраздел", "скала", "ошп"))
    ):
        focus_query = f"{question}\n\nКонтекст предыдущих реплик в AI-чате (для уточнения дат/подразделений):\n{memory_text[-6000:]}"
    mconn = connect(ctx.main_db_path)
    try:
        try:
            session_id = _resolve_shift_session_id(mconn, ctx, args, question)
        except ValueError as e:
            return ToolResult(
                tool="shift_summary",
                title="Смена",
                content=str(e),
                warnings=[str(e)],
            )
        try:
            summary = run_shift_summary(
                mconn,
                position_name=ctx.position_name,
                session_id=session_id,
                focus_query=focus_query,
                created_by=ctx.created_by,
            )
        except Exception as e:
            return ToolResult(
                tool="shift_summary",
                title="Сводка смены",
                content=str(e) or "Не удалось сформировать сводку смены.",
                warnings=[str(e)],
            )
    finally:
        mconn.close()
    label = f"смена id {session_id}" if session_id else "последняя смена"
    return ToolResult(
        tool="shift_summary",
        title="Сводка смены",
        content=summary.get("report_text") or "Сводка сформирована, но текст пуст.",
        actions=[f"сводка по перехватам: {label}"],
    )


def _sessions_analysis(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    """AI-анализ таблицы сеансов (ID, дежурные, пересечения)."""
    question = str(args.get("question") or "").strip()
    period_question = str(
        args.get("message_text") or args.get("period_question") or question
    ).strip()
    mconn = connect(ctx.main_db_path)
    start = end = ""
    try:
        start, end = resolve_sessions_period(
            mconn,
            question=period_question,
            position_name=ctx.position_name,
            date_from=str(args.get("date_from") or ""),
            date_to=str(args.get("date_to") or ""),
        )
        out = run_sessions_ai_analysis(
            mconn,
            position_name=ctx.position_name,
            start_ts=start,
            end_ts=end,
            question=question or "Кратко опиши активность ID и дежурных за период.",
            created_by=ctx.created_by,
        )
    except Exception as e:
        return ToolResult(
            tool="sessions_analysis",
            title="Сеансы",
            content=str(e),
            warnings=[str(e)],
        )
    finally:
        mconn.close()
    return ToolResult(
        tool="sessions_analysis",
        title="AI-анализ сеансов",
        content=out.get("report_text") or "Отчёт пуст.",
        actions=[f"анализ сеансов {start} — {end} ({out.get('result', {}).get('rows_count', '?')} строк)"],
    )


def _route_project(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    question = str(args.get("question") or "").strip()
    if not question:
        for key in ("unit", "id", "query", "terms"):
            value = args.get(key)
            if isinstance(value, list):
                question = " ".join(str(x) for x in value)
            elif value:
                question = str(value)
            if question:
                break
    force = bool(args.get("force_project_search") or args.get("freeform_db"))
    # Свободный режим: один связный ответ (понять запрос + выдать суть), а не сырой дамп + вторая реплика
    synthesize = bool(args.get("synthesize", True))
    mconn = connect(ctx.main_db_path)
    try:
        answer = route_ai_question(
            conn=mconn,
            portal_conn=ctx.portal_conn,
            question=question,
            position_name=ctx.position_name,
            user_id=ctx.user_id,
            force_project_search=force,
        )
    finally:
        mconn.close()
    text = (answer or "").strip()
    if force and synthesize and question:
        text = _freeform_assistant_reply(
            ctx,
            question=question,
            portal_context=text,
            rag_synthesis=True,
        )
    if not text:
        text = (
            "По запросу не удалось получить данные из источников портала. "
            "Уточните ID, подразделение, смену или период — либо переформулируйте вопрос."
        )
    return ToolResult(
        tool="route_project",
        title="Поиск и анализ данных портала",
        content=text,
        actions=["проверил доступные источники данных портала"] if text else [],
    )


def _apply_unit_assignment(ctx: ToolContext, args: dict[str, Any]) -> ToolResult:
    # The concrete guarded write is implemented in route_ai_question, but this
    # tool is marked as safe_write so the agent guard can decide whether to call it.
    result = _route_project(ctx, args)
    result.tool = "apply_unit_assignment"
    result.title = "Запись подразделения в Unit"
    result.changed = "Автоматически записано" in result.content or "Что записано в Unit" in result.content
    if result.changed and "записал привязку подразделения" not in result.actions:
        result.actions.append("записал привязку подразделения в Unit")
    return result


TOOL_REGISTRY: dict[str, AgentTool] = {
    "general_chat": AgentTool(
        name="general_chat",
        description="Обычный ответ нейросети без обращения к данным портала.",
        risk=RISK_READ,
        handler=_general_chat,
    ),
    "shift_summary": AgentTool(
        name="shift_summary",
        description=(
            "Сводка/отчёт по бланкам перехватов для выбранной смены. "
            "По умолчанию — последняя смена; args: session_id (число), shift_index (0=последняя, 1=предыдущая), "
            "date_from/date_to (YYYY-MM-DD) или дата в вопросе (например 20.02) для привязки смены."
        ),
        risk=RISK_READ,
        handler=_shift_summary,
    ),
    "sessions_analysis": AgentTool(
        name="sessions_analysis",
        description=(
            "AI-анализ сеансов связи: ID, дежурные, пересечения по подразделениям, всплески и аномалии. "
            "args: question, опционально date_from и date_to. "
            "Без явной даты в вопросе — все сеансы в базе (активные + архив), не только сегодня."
        ),
        risk=RISK_READ,
        handler=_sessions_analysis,
    ),
    "route_project": AgentTool(
        name="route_project",
        description=(
            "Read-only поиск по **всему проекту**: перехваты (все смены), сеансы, справочники, "
            "назначения Unit, AI-отчёты, ML, targeting. Args: question; "
            "force_project_search или freeform_db — широкий обход источников; synthesize — связный ответ LLM."
        ),
        risk=RISK_READ,
        handler=_route_project,
    ),
    "search_project": AgentTool(
        name="search_project",
        description="Синоним route_project: свободный поиск по всем источникам данных проекта.",
        risk=RISK_READ,
        handler=_route_project,
    ),
    "unit_profile": AgentTool(
        name="unit_profile",
        description="Профиль подразделения из БД и документов.",
        risk=RISK_READ,
        handler=_route_project,
    ),
    "id_profile": AgentTool(
        name="id_profile",
        description="Профиль ID, сеансы и участники переговоров.",
        risk=RISK_READ,
        handler=_route_project,
    ),
    "sessions_cross_unit": AgentTool(
        name="sessions_cross_unit",
        description="Межподразделенческие связи и пересечения ID.",
        risk=RISK_READ,
        handler=_route_project,
    ),
    "dictionary_lookup": AgentTool(
        name="dictionary_lookup",
        description="Справочники, позывные, частоты, группы и подразделения.",
        risk=RISK_READ,
        handler=_route_project,
    ),
    "targeting_lookup": AgentTool(
        name="targeting_lookup",
        description="Просмотр задач и targeting.",
        risk=RISK_READ,
        handler=_route_project,
    ),
    "ml_lookup": AgentTool(
        name="ml_lookup",
        description="Просмотр ML-прогнозов и объяснений.",
        risk=RISK_READ,
        handler=_route_project,
    ),
    "apply_unit_assignment": AgentTool(
        name="apply_unit_assignment",
        description="Точечная ручная запись подразделения в Unit по явной команде пользователя.",
        risk=RISK_SAFE_WRITE,
        required_permission="edit_search",
        handler=_apply_unit_assignment,
    ),
}


def get_tool(name: str) -> AgentTool | None:
    return TOOL_REGISTRY.get(str(name or "").strip())


def run_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolResult:
    tool = get_tool(name)
    if not tool or not tool.handler:
        return ToolResult(
            tool=str(name or ""),
            title="Неизвестный инструмент",
            content=f"Инструмент `{name}` не найден.",
            warnings=[f"unknown tool: {name}"],
        )
    return tool.handler(ctx, args or {})
