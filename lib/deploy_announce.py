from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def read_announce(path: Path) -> dict[str, Any]:
    """Возвращает revision (пусто = не показывать баннер), message, updated_at."""
    if not path.exists():
        return {"revision": "", "message": "", "updated_at": ""}
    try:
        raw = path.read_text(encoding="utf-8")
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        return {"revision": "", "message": "", "updated_at": ""}
    if not isinstance(data, dict):
        return {"revision": "", "message": "", "updated_at": ""}
    rev = str(data.get("revision") or "").strip()
    msg = str(data.get("message") or "").strip()
    upd = str(data.get("updated_at") or "").strip()
    return {"revision": rev, "message": msg, "updated_at": upd}


def bump_deploy_revision(prefix: str = "") -> str:
    return str(prefix or "") + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def write_announce(path: Path, revision: str, message: str = "") -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    obj = {
        "revision": str(revision or "").strip(),
        "message": str(message or "").strip(),
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    return obj
