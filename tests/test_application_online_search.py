"""Unit tests for application/online_search use cases."""

from __future__ import annotations

import pytest

from web_portal.application.online_search.errors import OnlineSearchUseCaseHTTP
from web_portal.application.online_search.media_urls import (
    avatar_url_for_file,
    parse_hero_payload,
    resolve_family_avatar_url,
)
from web_portal.application.online_search.validation import (
    validate_battalion_key,
    validate_parent_key,
    validate_unit_key,
)


def test_validate_unit_key_rejects_empty() -> None:
    with pytest.raises(OnlineSearchUseCaseHTTP) as exc:
        validate_unit_key("")
    assert exc.value.status_code == 400
    assert exc.value.payload["error"] == "key обязателен"


def test_validate_unit_key_rejects_too_long() -> None:
    with pytest.raises(OnlineSearchUseCaseHTTP) as exc:
        validate_unit_key("x" * 4001)
    assert exc.value.status_code == 400


def test_validate_parent_key_rejects_empty() -> None:
    with pytest.raises(OnlineSearchUseCaseHTTP) as exc:
        validate_parent_key("")
    assert exc.value.payload["error"] == "p обязателен"


def test_validate_battalion_key_rejects_empty() -> None:
    with pytest.raises(OnlineSearchUseCaseHTTP) as exc:
        validate_battalion_key("")
    assert exc.value.payload["error"] == "k обязателен"


def test_avatar_url_for_file_validates_and_builds() -> None:
    fn = "a" * 32 + ".png"
    url = avatar_url_for_file(fn, build_url=lambda f: f"/avatars/{f}")
    assert url == f"/avatars/{fn}"
    assert avatar_url_for_file("bad.png", build_url=lambda f: f"/avatars/{f}") is None


def test_parse_hero_payload_adds_banner_url() -> None:
    banner = "h" + ("a" * 32) + ".jpg"
    payload = parse_hero_payload(
        f'{{"mode":"banner","banner":"{banner}"}}',
        build_banner_url=lambda f: f"/hero/{f}",
    )
    assert payload is not None
    assert payload["banner_url"] == f"/hero/{banner}"


def test_resolve_family_avatar_url_prefers_parent() -> None:
    fn = "b" * 32 + ".webp"
    fam = {"parent_key": "parent-1", "children": [{"unit_key": "child-1"}]}
    av_files = {"parent-1": fn}
    url = resolve_family_avatar_url(
        fam, av_files, build_url=lambda f: f"/avatars/{f}"
    )
    assert url == f"/avatars/{fn}"
