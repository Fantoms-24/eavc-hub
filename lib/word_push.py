from __future__ import annotations

import json
import os
import re
from datetime import datetime

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    # fallback на urllib если requests нет
    from urllib import request as urlrequest


def load_word_push_config(config_path: str) -> dict:
    """
    Загружает конфиг отправки в Парсер WORD.
    Формат как в config/word_push_config.example.json:
      { "enabled": true, "server_url": "http://ip:5000", "client_name": "..." }
    """
    p = str(config_path or "").strip()
    if not p:
        return {}
    try:
        if not os.path.exists(p):
            return {}
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def build_word_new_content(
    *,
    position_name: str,
    unit_name: str,
    frequency: str,
    group_code: str,
    delta_text: str,
) -> str:
    """
    Формирует текст в том же стиле, что Парсер WORD отправляет в new_content:
    [метаданные блока]\n\n[содержимое]

    По твоему формату:
      [unit]
      [frequency]
      ID
      [group_code]

      [НОВЫЕ СТРОКИ начиная с нового времени]
    """
    u = (unit_name or "").strip() or "н/у"
    freq = (frequency or "").strip()
    grp = (group_code or "").strip()

    meta = [u]
    if freq:
        meta.append(freq)
    meta.append("ID")
    meta.append(grp)

    body = str(delta_text or "").strip()
    if not body:
        return ""
    return "\n".join([*meta, "", body]).strip() + "\n"


def post_to_word_server(
    *,
    server_url: str,
    client_name: str,
    document: str,
    new_content: str,
    document_path: str = "",
    timeout_sec: float = 6.0,
) -> tuple[bool, str]:
    """
    Отправляет payload на сервер Парсер WORD (/api/upload).
    Использует тот же формат, что и Парсер WORD/auto_monitor.py ServerSender.send_data().
    Возвращает (ok, error_message).
    """
    base = str(server_url or "").strip().rstrip("/")
    if not base:
        return (False, "empty server_url")
    url = f"{base}/api/upload"
    payload = {
        "timestamp": datetime.now().isoformat(),
        "document": str(document or "web_intercepts.txt"),
        "document_path": str(document_path or ""),
        "client_name": str(client_name or "Web Portal"),
        "new_content": str(new_content or ""),
        "content_length": int(len(str(new_content or ""))),
    }
    
    # Используем requests как в Парсер WORD
    if HAS_REQUESTS:
        try:
            response = requests.post(
                url, json=payload, timeout=float(timeout_sec or 6.0)
            )
            if response.status_code == 200:
                return (True, "")
            return (False, f"HTTP {response.status_code}: {response.text[:200]}")
        except requests.exceptions.ConnectionError as e:
            return (False, f"Connection error: {str(e)}")
        except requests.exceptions.Timeout as e:
            return (False, f"Timeout: {str(e)}")
        except Exception as e:
            return (False, str(e))
    else:
        # Fallback на urllib если requests нет
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urlrequest.Request(
            url=url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlrequest.urlopen(req, timeout=float(timeout_sec or 6.0)) as resp:
                if 200 <= int(resp.status) < 300:
                    return (True, "")
                return (False, f"HTTP {int(resp.status)}")
        except Exception as e:
            return (False, str(e))


def safe_filename(s: str) -> str:
    x = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(s or "").strip())
    x = x.strip("._-") or "web_intercepts"
    return x[:80]


def default_document_name(position_name: str) -> str:
    pos = safe_filename(position_name)
    return f"intercepts_{pos}.txt"


_CORR_CODE_RE = re.compile(r"\((\d{1,10})\)")


def extract_correspondent_codes(text: str) -> list[str]:
    """ID корреспондентов из текста бланка в порядке первого появления."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _CORR_CODE_RE.finditer(str(text or "")):
        code = str(m.group(1) or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out


def lookup_callsigns_for_forward(
    conn,
    *,
    position_name: str,
    frequency: str,
    group_code: str,
    codes: list[str],
) -> list[dict[str, str]]:
    """
    Позывные для отправки в чат: только запись текущей частоты/группы.
    Если позывной не задан — label = «н/у».
    """
    pos = str(position_name or "").strip()
    freq = str(frequency or "").strip()
    grp = str(group_code or "").strip()
    ordered = [str(c or "").strip() for c in (codes or []) if str(c or "").strip()]
    if not ordered:
        return []
    label_by_code: dict[str, str] = {}
    if pos and freq and grp:
        try:
            placeholders = ",".join("?" for _ in ordered)
            rows = conn.execute(
                f"""
                SELECT code, label
                FROM intercept_callsigns
                WHERE position_name=?
                  AND frequency=?
                  AND group_code=?
                  AND code IN ({placeholders})
                """,
                (pos, freq, grp, *ordered),
            ).fetchall()
            for r in rows or []:
                code = str(r["code"] if hasattr(r, "keys") else r[0] or "").strip()
                label = str(r["label"] if hasattr(r, "keys") else r[1] or "").strip()
                if code:
                    label_by_code[code] = label
        except Exception:
            label_by_code = {}
    return [
        {"code": code, "label": (label_by_code.get(code) or "").strip() or "н/у"}
        for code in ordered
    ]
