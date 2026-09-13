"""Применение настроек AI (Ollama / OpenAI-совместимый API) из JSON-конфига или окружения."""
from __future__ import annotations

import os
from typing import Any, Mapping


def _truthy(val: Any) -> bool | None:
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        s = val.strip().lower()
        if s in {"1", "true", "yes", "on"}:
            return True
        if s in {"0", "false", "no", "off"}:
            return False
    return None


def apply_ai_env_from_config(cfg: Mapping[str, Any] | None) -> None:
    """
    Читает блок ``ai`` из hub_config.json / server_config.json (или плоские ключи)
    и выставляет WEB_PORTAL_AI_* через setdefault (не перетирает уже заданные env).
    """
    if not cfg:
        return
    block: dict[str, Any] = {}
    raw_ai = cfg.get("ai")
    if isinstance(raw_ai, dict):
        block.update(raw_ai)
    # Плоские ключи в корне конфига (обратная совместимость)
    for key in (
        "ai_provider",
        "ai_base_url",
        "ai_model",
        "ai_embed_model",
        "ai_timeout_sec",
        "ai_api_key",
        "ai_enabled",
    ):
        if key in cfg and cfg[key] is not None:
            block[key.replace("ai_", "", 1)] = cfg[key]

    if not block:
        return

    mapping = {
        "provider": "WEB_PORTAL_AI_PROVIDER",
        "base_url": "WEB_PORTAL_AI_BASE_URL",
        "model": "WEB_PORTAL_AI_MODEL",
        "embed_model": "WEB_PORTAL_AI_EMBED_MODEL",
        "timeout_sec": "WEB_PORTAL_AI_TIMEOUT_SEC",
        "api_key": "WEB_PORTAL_AI_API_KEY",
        "enabled": "WEB_PORTAL_AI_ENABLED",
    }
    for src, env_key in mapping.items():
        if src not in block or block[src] is None:
            continue
        val = block[src]
        if src == "enabled":
            t = _truthy(val)
            if t is None:
                continue
            val = "1" if t else "0"
        else:
            val = str(val).strip()
            if not val and src != "api_key":
                continue
        os.environ.setdefault(env_key, str(val))
