import pytest

from web_portal.application.analysis.ai_reports import (
    parse_optional_session_id,
    parse_period_report_range,
)
from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.application.analysis.full_report import resolve_full_report_period
from web_portal.application.intercepts.audio_arm_task_sync import (
    audio_task_freq_from_arm_task,
)


def test_parse_optional_session_id_none():
    assert parse_optional_session_id(None) is None
    assert parse_optional_session_id("") is None


def test_parse_optional_session_id_ok():
    assert parse_optional_session_id("42") == 42


def test_parse_optional_session_id_bad():
    with pytest.raises(AnalysisUseCaseHTTP) as exc:
        parse_optional_session_id("x")
    assert exc.value.status_code == 400


def test_parse_period_report_range_requires_both():
    with pytest.raises(AnalysisUseCaseHTTP):
        parse_period_report_range({"start": "a"})


def test_resolve_full_report_period_month():
    period = resolve_full_report_period({"report_month": "2026-04"})
    assert period.start_s == "2026-04-01 00:00:00"
    assert period.end_s.startswith("2026-04-30")
    assert period.report_month == "2026-04"


def test_resolve_full_report_period_bad_month():
    with pytest.raises(AnalysisUseCaseHTTP) as exc:
        resolve_full_report_period({"report_month": "not-a-month"})
    assert exc.value.status_code == 400


def test_audio_task_freq_from_arm_task():
    assert audio_task_freq_from_arm_task("145.5") == "145.5000"
    assert audio_task_freq_from_arm_task("") == ""
