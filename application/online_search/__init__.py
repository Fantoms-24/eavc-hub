"""Сценарии домена «Поиск онлайн»."""

from web_portal.application.online_search.battalion_spectrum import (
    assemble_online_search_battalion_spectrum_payload,
)
from web_portal.application.online_search.errors import OnlineSearchUseCaseHTTP
from web_portal.application.online_search.import_xlsx import execute_online_search_import_xlsx
from web_portal.application.online_search.media_urls import (
    AVATAR_FILE_RE,
    HERO_BANNER_FILE_RE,
    avatar_url_for_file,
    collect_family_unit_keys,
    parse_hero_payload,
    resolve_family_avatar_url,
)
from web_portal.application.online_search.unit_detail import (
    assemble_online_search_unit_detail_payload,
)
from web_portal.application.online_search.unit_parent import (
    assemble_online_search_unit_parent_payload,
)
from web_portal.application.online_search.units_list import (
    assemble_online_search_units_list_payload,
)
from web_portal.application.online_search.validation import (
    validate_battalion_key,
    validate_parent_key,
    validate_unit_key,
)

__all__ = [
    "AVATAR_FILE_RE",
    "HERO_BANNER_FILE_RE",
    "OnlineSearchUseCaseHTTP",
    "assemble_online_search_battalion_spectrum_payload",
    "assemble_online_search_unit_detail_payload",
    "assemble_online_search_unit_parent_payload",
    "assemble_online_search_units_list_payload",
    "avatar_url_for_file",
    "collect_family_unit_keys",
    "execute_online_search_import_xlsx",
    "parse_hero_payload",
    "resolve_family_avatar_url",
    "validate_battalion_key",
    "validate_parent_key",
    "validate_unit_key",
]
