from datetime import datetime

import pytest

from web_portal.application.admin.ai_agent import parse_llm_training_export_params
from web_portal.application.admin.ai_vector_index import parse_ai_vector_index_params
from web_portal.application.admin.db_health import (
    parse_db_health_params,
    parse_seanses_multi_channel_day_params,
)
from web_portal.application.admin.errors import AdminUseCaseHTTP
from web_portal.application.admin.export_sessions_excel import resolve_export_sessions_folder
from web_portal.application.admin.hubs import build_hub_activity_status
from web_portal.application.admin.positions import parse_positions_map_assignments
from web_portal.application.admin.seans_archive import parse_archive_seanses_to_file_params


def test_parse_db_health_params_defaults():
    params = parse_db_health_params({})
    assert params.db_name
    assert params.aes_followup_mode == "calendar_day"
    assert params.aes_followup_hours == 24
    assert params.aes_after_id_hours == 0
    assert params.correspondent_id is None


def test_parse_db_health_params_clamps_hours():
    params = parse_db_health_params(
        {
            "aes_followup_hours": "999",
            "aes_after_id_hours": "-5",
            "aes_followup_mode": "rolling",
        }
    )
    assert params.aes_followup_mode == "rolling"
    assert params.aes_followup_hours == 168
    assert params.aes_after_id_hours == 0


def test_parse_db_health_params_invalid_db():
    with pytest.raises(AdminUseCaseHTTP) as exc:
        parse_db_health_params({"db": "../etc/passwd"})
    assert exc.value.status_code == 400
    assert exc.value.payload["ok"] is False


def test_parse_seanses_multi_channel_day_requires_date():
    with pytest.raises(AdminUseCaseHTTP) as exc:
        parse_seanses_multi_channel_day_params({"db": "main"})
    assert exc.value.status_code == 400


def test_parse_seanses_multi_channel_day_ok():
    params = parse_seanses_multi_channel_day_params(
        {"date": "2026-04-21", "correspondent_id": " 42 "}
    )
    assert params.calendar_date == "2026-04-21"
    assert params.only_id == "42"


def test_parse_archive_seanses_to_file_rejects_path_traversal():
    with pytest.raises(AdminUseCaseHTTP) as exc:
        parse_archive_seanses_to_file_params({"before_date": "2026-01-01", "filename": "../x.sqlite"})
    assert exc.value.status_code == 400


def test_build_hub_activity_status_online():
    now = datetime(2026, 4, 21, 12, 0, 0)
    status, text, minutes = build_hub_activity_status("2026-04-21 11:59:30", now=now)
    assert status == "online"
    assert text == "онлайн"
    assert minutes == 0


def test_build_hub_activity_status_offline():
    now = datetime(2026, 4, 21, 12, 0, 0)
    status, text, minutes = build_hub_activity_status("2026-04-21 10:00:00", now=now)
    assert status == "offline"
    assert minutes == 120
    assert "120" in text


def test_parse_ai_vector_index_params_rejects_mode():
    with pytest.raises(AdminUseCaseHTTP) as exc:
        parse_ai_vector_index_params({"mode": "bogus"})
    assert exc.value.status_code == 400


def test_parse_ai_vector_index_params_clamps():
    params = parse_ai_vector_index_params(
        {"mode": "incremental", "max_intercepts": 0, "max_seanses": "9999999"}
    )
    assert params.mode == "incremental"
    assert params.max_intercepts == 1
    assert params.max_seanses == 200_000


def test_parse_llm_training_export_params():
    params = parse_llm_training_export_params(
        {"only_rated": "true", "only_positive": "1", "min_user_len": "0"}
    )
    assert params.only_rated is True
    assert params.only_positive is True
    assert params.min_user_len == 1


def test_resolve_export_sessions_folder_empty():
    with pytest.raises(AdminUseCaseHTTP) as exc:
        resolve_export_sessions_folder("  ")
    assert exc.value.status_code == 400


def test_parse_positions_map_assignments():
    tokens = parse_positions_map_assignments(
        {"Москва": "chief", "Рязань": "weird", "": "operator"}
    )
    assert tokens == ["Москва:chief", "Рязань:operator"]
