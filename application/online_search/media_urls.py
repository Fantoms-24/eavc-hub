"""Сборка URL аватаров и hero-баннеров без Flask (через callback из маршрута)."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

AVATAR_FILE_RE = re.compile(r"^[a-fA-F0-9]{32}\.[A-Za-z0-9]{2,5}$")
HERO_BANNER_FILE_RE = re.compile(r"^h[a-fA-F0-9]{32}\.[A-Za-z0-9]{2,5}$", re.I)


def avatar_url_for_file(
    filename: str | None,
    *,
    build_url: Callable[[str], str],
) -> str | None:
    if not filename or not AVATAR_FILE_RE.match(str(filename)):
        return None
    return build_url(str(filename))


def resolve_family_avatar_url(
    fam: dict[str, Any],
    av_files: dict[str, str],
    *,
    build_url: Callable[[str], str],
) -> str | None:
    pk = str(fam.get("parent_key") or "").strip()
    if pk and pk != "__none__":
        url = avatar_url_for_file(av_files.get(pk), build_url=build_url)
        if url:
            return url
    for ch in fam.get("children") or []:
        u = str(ch.get("unit_key") or "").strip()
        url = avatar_url_for_file(av_files.get(u) if u else None, build_url=build_url)
        if url:
            return url
    return None


def collect_family_unit_keys(families: list[dict[str, Any]]) -> list[str]:
    ukeys: list[str] = []
    for fam in families:
        pk = str(fam.get("parent_key") or "").strip()
        if pk and pk != "__none__":
            ukeys.append(pk)
        for ch in fam.get("children") or []:
            u = str(ch.get("unit_key") or "").strip()
            if u:
                ukeys.append(u)
    return ukeys


def parse_hero_payload(
    hero_json: str | None,
    *,
    build_banner_url: Callable[[str], str],
) -> dict[str, Any] | None:
    hj = str(hero_json or "").strip()
    if not hj:
        return None
    try:
        ho = json.loads(hj)
    except json.JSONDecodeError:
        return None
    if not isinstance(ho, dict):
        return None
    bn = ho.get("banner")
    if bn and isinstance(bn, str) and HERO_BANNER_FILE_RE.match(bn):
        return {**ho, "banner_url": build_banner_url(bn)}
    return ho
