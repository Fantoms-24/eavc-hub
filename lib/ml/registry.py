from __future__ import annotations

from pathlib import Path
from typing import Any
import json
from datetime import datetime

from web_portal.config import DATA_DIR


def get_ml_dir() -> Path:
    out = DATA_DIR / "ml"
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_models_dir() -> Path:
    out = get_ml_dir() / "models"
    out.mkdir(parents=True, exist_ok=True)
    return out


def new_model_version() -> str:
    return "gevn-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")


def artifact_path_for(model_version: str) -> Path:
    return get_models_dir() / f"{model_version}.pt"


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

