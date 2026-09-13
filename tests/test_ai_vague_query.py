"""Расширение нечётких запросов планировщика (без сети)."""

import pytest

from web_portal.lib import ai_assistant as aa


@pytest.mark.parametrize(
    "q, want_substr",
    [
        ("Покажи интересные события за сегодня", "релевантно: необычные"),
        ("Что за аномалии в эфире?", "релевантно: нестандартные"),
        ("Самое важное за сутки", "релевантно: критичные"),
        ("странные выходы ID", "релевантно: нетипичное"),
        ("подозрительные фразы", "релевантно: риск"),
    ],
)
def test_expand_vague_query_adds_hints(q, want_substr):
    out = aa._expand_vague_query(q)
    assert want_substr in out


def test_expand_vague_query_noop_for_concrete():
    t = "позывной 12115 сегодня"
    assert aa._expand_vague_query(t) == t


def test_query_has_vague_term():
    assert aa._query_has_vague_term("интересное за вчера")
    assert not aa._query_has_vague_term("частота 143.0 группа 4")


def test_sanitize_planner_args_expands_route_project():
    out = aa._sanitize_planner_args(
        "route_project",
        {"question": "аномальные выходы", "force_project_search": True, "synthesize": True},
        "ignored",
    )
    assert "релевантно" in out["question"]


def test_sanitize_planner_args_expands_shift_summary():
    out = aa._sanitize_planner_args("shift_summary", {"question": "интересное за смену"}, "x")
    assert "релевантно" in out["question"]


def test_parse_low_conf_vague_triggers_fallback_clarify():
    obj = {
        "goal": "тест",
        "confidence": 0.4,
        "tool": "route_project",
        "args": {"question": "важные моменты"},
    }
    plan = aa._parse_dynamic_planner_object(obj, "важные моменты")
    assert plan is not None
    assert plan.metadata.get("source") == "vague_term_fallback"
    assert plan.steps[0].tool == "general_chat"
    assert "canned" in plan.steps[0].args


def test_id_cross_unit_routes_to_route_project():
    from web_portal.lib.ai_assistant import _wants_id_cross_unit_data_lookup

    assert _wants_id_cross_unit_data_lookup(
        "Проверить наличие других событий с ID 160 в других подразделениях."
    )
    assert not _wants_id_cross_unit_data_lookup("привет")
    assert not _wants_id_cross_unit_data_lookup("425 ошп скала что известно")


def test_parse_high_conf_vague_still_routes_and_expands():
    obj = {
        "goal": "тест",
        "confidence": 0.9,
        "tool": "route_project",
        "args": {
            "question": "интересные бланки",
            "force_project_search": True,
            "synthesize": True,
        },
    }
    plan = aa._parse_dynamic_planner_object(obj, "интересные бланки")
    assert plan is not None
    assert plan.steps[0].tool == "route_project"
    q = plan.steps[0].args.get("question") or ""
    assert "релевантно" in q
