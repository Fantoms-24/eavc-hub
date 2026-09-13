"""Парсинг параметров GET /api/intercepts/audio/list."""

from __future__ import annotations

from web_portal.application.intercepts.audio_list import parse_intercepts_audio_list_params


def test_parse_audio_list_params_defaults() -> None:
    params = parse_intercepts_audio_list_params(
        {"folder_path": "/data/audio\n/backup"},
        current_username="op1",
    )
    assert params.folder_paths == ["/data/audio", "/backup"]
    assert params.tasks_only is False
    assert params.limit == 300
    assert params.full_scan is False
    assert params.quick_scan is False
    assert params.cache_flag is True
    assert params.layout_param == "auto"
    assert params.current_username == "op1"


def test_parse_audio_list_params_flags_and_caps() -> None:
    params = parse_intercepts_audio_list_params(
        {
            "folder_path": "/x",
            "tasks_only": "true",
            "full_scan": "1",
            "quick": "yes",
            "limit": "99999",
            "debug": "true",
            "cache": "0",
            "layout": "bundle",
            "is_running": "false",
            "client_id": "c1",
        }
    )
    assert params.tasks_only is True
    assert params.full_scan is True
    assert params.quick_scan is True
    assert params.limit == 50000
    assert params.debug_flag is True
    assert params.cache_flag is False
    assert params.layout_param == "bundle"
    assert params.req_is_running is False
    assert params.req_client_id == "c1"


def test_parse_audio_list_limit_capped_without_full_scan() -> None:
    params = parse_intercepts_audio_list_params({"folder_path": "/x", "limit": "800"})
    assert params.limit == 600

    quick = parse_intercepts_audio_list_params(
        {"folder_path": "/x", "limit": "800", "quick": "1"}
    )
    assert quick.limit == 200
