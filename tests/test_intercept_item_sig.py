"""Подпись содержимого бланка: сравнение клиента и сервера.

Подпись включает хвост содержимого, а нормализованный бланк всегда заканчивается
переводом строки. Если одну сторону сравнения обрезать, а другую нет, ответ
`unchanged` не срабатывает никогда: клиент перестаёт использовать долгий опрос и
начинает непрерывно перезагружать бланк, перетирая правки оператора.
"""

from __future__ import annotations

import urllib.parse

from web_portal.app_runtime_caches import (
    intercept_item_live_bump,
    intercept_item_live_wait,
)
from web_portal.application.intercepts.state_sig import (
    compute_intercept_item_content_sig,
    normalize_intercept_item_content_sig,
)

UPDATED_AT = "2026-07-30 08:29:37"
CONTENT = "11.00\n-TEST. (123)\n"


def _through_query_string(sig: str) -> str:
    """Как подпись доезжает до сервера: urlencode на клиенте, разбор во Flask."""
    query = urllib.parse.urlencode({"item_sig": sig})
    return urllib.parse.parse_qs(query, keep_blank_values=True)["item_sig"][0]


def test_sig_of_normalized_content_ends_with_newline() -> None:
    """Условие, из-за которого дефект был незаметен на пустых бланках."""
    sig = compute_intercept_item_content_sig(UPDATED_AT, CONTENT)
    assert sig.endswith("\n")


def test_sig_survives_transport_when_both_sides_normalized() -> None:
    client_sig = compute_intercept_item_content_sig(UPDATED_AT, CONTENT)
    delivered = _through_query_string(client_sig)
    server_sig = compute_intercept_item_content_sig(UPDATED_AT, CONTENT)

    assert normalize_intercept_item_content_sig(
        delivered
    ) == normalize_intercept_item_content_sig(server_sig)


def test_normalizing_only_one_side_breaks_comparison() -> None:
    """Регресс: именно так подпись и расходилась (обрезали только запрос)."""
    sig = compute_intercept_item_content_sig(UPDATED_AT, CONTENT)
    assert normalize_intercept_item_content_sig(sig) != sig


def test_empty_content_matched_even_with_old_behaviour() -> None:
    """Пустой бланк совпадал и раньше — поэтому дефект выглядел плавающим."""
    sig = compute_intercept_item_content_sig(UPDATED_AT, "")
    assert normalize_intercept_item_content_sig(sig) == sig


def test_changed_content_still_differs_after_normalization() -> None:
    """Обрезка пробелов не должна выдавать разное содержимое за одинаковое."""
    a = compute_intercept_item_content_sig(UPDATED_AT, CONTENT)
    b = compute_intercept_item_content_sig(
        UPDATED_AT, "11.00\n-TEST. (123)\n-SECOND. (456)\n"
    )
    assert normalize_intercept_item_content_sig(a) != normalize_intercept_item_content_sig(b)


def test_same_length_different_tail_still_differs() -> None:
    """Длина входит в подпись, но и хвост должен различать содержимое."""
    a = compute_intercept_item_content_sig(UPDATED_AT, "11.00\n-AAA. (1)\n")
    b = compute_intercept_item_content_sig(UPDATED_AT, "11.00\n-BBB. (1)\n")
    assert normalize_intercept_item_content_sig(a) != normalize_intercept_item_content_sig(b)


def test_live_wait_does_not_report_change_for_same_content() -> None:
    """Долгий опрос обязан ждать, а не отвечать `changed` мгновенно."""
    item_id = 987654
    stored = normalize_intercept_item_content_sig(
        compute_intercept_item_content_sig(UPDATED_AT, CONTENT)
    )
    intercept_item_live_bump(item_id, item_sig=stored, updated_at=UPDATED_AT)

    client_sig = normalize_intercept_item_content_sig(
        _through_query_string(compute_intercept_item_content_sig(UPDATED_AT, CONTENT))
    )
    result = intercept_item_live_wait(item_id, client_sig, timeout_sec=0.5)

    assert result == {"changed": False}


def test_live_wait_reports_change_for_new_content() -> None:
    item_id = 987655
    intercept_item_live_bump(
        item_id,
        item_sig=normalize_intercept_item_content_sig(
            compute_intercept_item_content_sig(UPDATED_AT, CONTENT)
        ),
        updated_at=UPDATED_AT,
    )

    stale_client_sig = normalize_intercept_item_content_sig(
        compute_intercept_item_content_sig("2026-07-30 08:29:00", "11.00\n-OLD. (1)\n")
    )
    result = intercept_item_live_wait(item_id, stale_client_sig, timeout_sec=0.5)

    assert result.get("changed") is True
