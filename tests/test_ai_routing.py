"""Smoke/unit-тесты маршрутизации поиска AI (без запуска сервера)."""

from web_portal.lib.ai_router import (
    has_explicit_project_search_prefix,
    normalize_user_search_question,
    _wants_text_mention_search,
)


def test_normalize_user_search_prefixes():
    assert normalize_user_search_question("поиск:  спартан нгу") == "спартан нгу"
    assert normalize_user_search_question("search:foo") == "foo"
    q = normalize_user_search_question('только перехваты: 3 бон "Спартан"')
    assert "3 бон" in q
    assert "приоритет перехватам" in q.lower() or "перехватам" in q.lower()


def test_explicit_prefix_detection():
    assert has_explicit_project_search_prefix("поиск: x") is True
    assert has_explicit_project_search_prefix("x") is False


def test_wants_text_mention_variants():
    assert _wants_text_mention_search(
        "Найди все вхождения в перехватах фразы Спартан"
    )
    assert _wants_text_mention_search(
        "где в бланке сказано про воду"
    )
    assert not _wants_text_mention_search("погода в москве")
