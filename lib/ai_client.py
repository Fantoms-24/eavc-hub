from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any
from urllib import error, request


class AIClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class AIClientConfig:
    provider: str
    base_url: str
    model: str
    timeout_sec: int
    api_key: str = ""

    @classmethod
    def from_env(cls) -> "AIClientConfig":
        provider = (os.environ.get("WEB_PORTAL_AI_PROVIDER") or "ollama").strip().lower()
        default_url = "http://127.0.0.1:11434" if provider == "ollama" else "http://127.0.0.1:8000"
        return cls(
            provider=provider,
            base_url=(os.environ.get("WEB_PORTAL_AI_BASE_URL") or default_url).strip().rstrip("/"),
            model=(os.environ.get("WEB_PORTAL_AI_MODEL") or "qwen2.5:7b-instruct-q4_K_M").strip(),
            timeout_sec=int(os.environ.get("WEB_PORTAL_AI_TIMEOUT_SEC") or "240"),
            api_key=(os.environ.get("WEB_PORTAL_AI_API_KEY") or "").strip(),
        )


def current_ai_config() -> AIClientConfig:
    return AIClientConfig.from_env()


def _post_json(url: str, payload: dict[str, Any], *, timeout: int, api_key: str = "") -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise AIClientError(f"AI endpoint вернул HTTP {exc.code}: {raw[:500]}") from exc
    except Exception as exc:
        raise AIClientError(f"AI endpoint недоступен: {exc}") from exc
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError as exc:
        raise AIClientError(f"AI endpoint вернул не JSON: {raw[:500]}") from exc
    if not isinstance(data, dict):
        raise AIClientError("AI endpoint вернул неожиданный формат ответа")
    return data


def generate_ai_text(
    *,
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1400,
    config: AIClientConfig | None = None,
) -> dict[str, Any]:
    cfg = config or current_ai_config()
    if cfg.provider == "ollama":
        payload = {
            "model": cfg.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": float(temperature),
                "num_predict": int(max_tokens),
            },
        }
        data = _post_json(f"{cfg.base_url}/api/chat", payload, timeout=cfg.timeout_sec)
        msg = data.get("message") if isinstance(data.get("message"), dict) else {}
        text = str(msg.get("content") or "").strip()
        if not text:
            raise AIClientError("Модель вернула пустой ответ")
        return {"text": text, "model": cfg.model, "provider": cfg.provider, "raw": data}

    payload = {
        "model": cfg.model,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    data = _post_json(
        f"{cfg.base_url}/v1/chat/completions",
        payload,
        timeout=cfg.timeout_sec,
        api_key=cfg.api_key,
    )
    choices = data.get("choices") if isinstance(data.get("choices"), list) else []
    first = choices[0] if choices else {}
    msg = first.get("message") if isinstance(first, dict) else {}
    text = str((msg or {}).get("content") or "").strip()
    if not text:
        raise AIClientError("Модель вернула пустой ответ")
    return {"text": text, "model": cfg.model, "provider": cfg.provider, "raw": data}


def embed_text(
    *,
    text: str,
    model: str | None = None,
    config: AIClientConfig | None = None,
) -> list[float]:
    """
    Векторизация текста для RAG/поиска. Ollama: POST /api/embeddings; OpenAI-совместимый: /v1/embeddings.
    Модель по умолчанию: WEB_PORTAL_AI_EMBED_MODEL или nomic-embed-text.
    """
    raw_t = (text or "").strip()
    if not raw_t:
        raise AIClientError("Пустой текст для эмбеддинга")
    cfg = config or current_ai_config()
    model_name = (model or os.environ.get("WEB_PORTAL_AI_EMBED_MODEL") or "nomic-embed-text").strip()
    if cfg.provider == "ollama":
        data = _post_json(
            f"{cfg.base_url}/api/embeddings",
            {"model": model_name, "prompt": raw_t},
            timeout=min(cfg.timeout_sec, 120),
            api_key=cfg.api_key,
        )
        emb = data.get("embedding")
        if not isinstance(emb, list) or not emb:
            raise AIClientError("Ollama /api/embeddings: нет валидного поля embedding")
        return [float(x) for x in emb]
    # OpenAI-совместимый эндпоинт
    data = _post_json(
        f"{cfg.base_url}/v1/embeddings",
        {"model": model_name, "input": raw_t},
        timeout=min(cfg.timeout_sec, 120),
        api_key=cfg.api_key,
    )
    arr = data.get("data") if isinstance(data.get("data"), list) else []
    if not arr or not isinstance(arr[0], dict):
        raise AIClientError("v1/embeddings: нет data[0]")
    emb2 = arr[0].get("embedding")
    if not isinstance(emb2, list):
        raise AIClientError("v1/embeddings: нет embedding")
    return [float(x) for x in emb2]
