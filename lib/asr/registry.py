from __future__ import annotations

from pathlib import Path
from datetime import datetime

from web_portal.config import DATA_DIR


def get_asr_dir() -> Path:
    out = DATA_DIR / "asr"
    out.mkdir(parents=True, exist_ok=True)
    return out


def get_asr_models_dir() -> Path:
    out = get_asr_dir() / "models"
    out.mkdir(parents=True, exist_ok=True)
    return out


def new_asr_model_version() -> str:
    return "asr-" + datetime.utcnow().strftime("%Y%m%d%H%M%S")


def artifact_path_for(version: str) -> Path:
    return get_asr_models_dir() / f"{version}.json"

