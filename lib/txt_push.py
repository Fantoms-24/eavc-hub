from __future__ import annotations

import json
from datetime import datetime
from urllib import request as urlrequest


def post_plain_text(
    *,
    server_url: str,
    endpoint_path: str = "/api/intercepts/txt",
    text: str,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 6.0,
) -> tuple[bool, str]:
    """
    Отправляет TXT (text/plain) на удалённый сервер.
    Возвращает (ok, error_message).
    """
    base = str(server_url or "").strip().rstrip("/")
    if not base:
        return (False, "empty server_url")
    ep = str(endpoint_path or "/api/intercepts/txt").strip()
    if not ep.startswith("/"):
        ep = "/" + ep
    url = f"{base}{ep}"

    body = str(text or "")
    data = body.encode("utf-8")
    h = {"Content-Type": "text/plain; charset=utf-8"}
    for k, v in (headers or {}).items():
        kk = str(k or "").strip()
        if not kk:
            continue
        h[kk] = str(v or "")
    req = urlrequest.Request(url=url, data=data, method="POST", headers=h)
    try:
        with urlrequest.urlopen(req, timeout=float(timeout_sec or 6.0)) as resp:
            if 200 <= int(resp.status) < 300:
                return (True, "")
            return (False, f"HTTP {int(resp.status)}")
    except Exception as e:
        return (False, str(e))


def post_json_text(
    *,
    server_url: str,
    endpoint_path: str,
    payload: dict,
    headers: dict[str, str] | None = None,
    timeout_sec: float = 6.0,
) -> tuple[bool, str]:
    """
    Альтернатива: отправка JSON (если на вашей стороне приёмник ожидает JSON).
    """
    base = str(server_url or "").strip().rstrip("/")
    if not base:
        return (False, "empty server_url")
    ep = str(endpoint_path or "").strip()
    if not ep:
        return (False, "empty endpoint_path")
    if not ep.startswith("/"):
        ep = "/" + ep
    url = f"{base}{ep}"
    p = dict(payload or {})
    p.setdefault("timestamp", datetime.now().isoformat())
    data = json.dumps(p, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    for k, v in (headers or {}).items():
        kk = str(k or "").strip()
        if not kk:
            continue
        req_headers[kk] = str(v or "")
    req = urlrequest.Request(url=url, data=data, method="POST", headers=req_headers)
    try:
        with urlrequest.urlopen(req, timeout=float(timeout_sec or 6.0)) as resp:
            if 200 <= int(resp.status) < 300:
                return (True, "")
            return (False, f"HTTP {int(resp.status)}")
    except Exception as e:
        return (False, str(e))


