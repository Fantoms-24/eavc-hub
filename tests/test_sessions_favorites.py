from web_portal.lib.db import (
    build_sessions_favorite_match_set,
    sessions_favorite_matches_row,
    sessions_row_is_favorite,
)


def test_sessions_favorite_matches_row_by_freq_zone():
    fav = {"frequency": "123.450", "group": "100"}
    assert sessions_favorite_matches_row("123.456", "100", fav) is True
    assert sessions_favorite_matches_row("123.456", "200", fav) is False


def test_sessions_row_is_favorite_uses_zone_keys():
    favorites = [{"frequency": "123.450", "group": "100"}]
    keys = build_sessions_favorite_match_set(favorites)
    assert sessions_row_is_favorite("123.456", "100", keys) is True
    assert sessions_row_is_favorite("124.100", "100", keys) is False
