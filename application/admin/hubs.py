"""Hub activity для админки (без Flask)."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def build_hub_activity_status(
    last_seen_str: str,
    *,
    now: datetime,
) -> tuple[str, str, int | None]:
    try:
        last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d %H:%M:%S")
        delta = now - last_seen
        minutes_ago = int(delta.total_seconds() / 60)

        if minutes_ago < 2:
            status = "online"
            status_text = "онлайн"
        elif minutes_ago < 5:
            status = "recent"
            status_text = f"был {minutes_ago} мин назад"
        elif minutes_ago < 30:
            status = "idle"
            status_text = f"был {minutes_ago} мин назад"
        else:
            status = "offline"
            status_text = f"был {minutes_ago} мин назад"
        return status, status_text, minutes_ago
    except Exception:
        return "unknown", "неизвестно", None


def assemble_admin_hubs_payload(
    hubs: list[dict[str, Any]],
    *,
    now: datetime,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for hub in hubs:
        last_seen_str = hub.get("last_seen") or ""
        status, status_text, minutes_ago = build_hub_activity_status(
            last_seen_str,
            now=now,
        )
        enriched = dict(hub)
        enriched["status"] = status
        enriched["status_text"] = status_text
        enriched["minutes_ago"] = minutes_ago
        result.append(enriched)
    return result
