from __future__ import annotations

from web_portal.lib.asr.model import (
    build_operator_blank,
    format_operator_time_header,
    operator_line_with_id,
)


def test_operator_line_with_id() -> None:
    assert operator_line_with_id("сиди в укрытии", "1341839") == "-Сиди в укрытии (1341839)."


def test_format_operator_time_header() -> None:
    assert format_operator_time_header("2025-06-05 10:26:23") == "10.26"


def test_build_operator_blank() -> None:
    out = build_operator_blank(
        recorded_at="2025-06-05 10:26:23",
        segment_lines=[
            "-Привет (1231).",
            "-Ответ (1241).",
        ],
    )
    assert out.splitlines() == ["10.26", "-Привет (1231).", "-Ответ (1241)."]
