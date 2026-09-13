from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# PyInstaller: хотим хранить data рядом с exe, а не внутри _internal
if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent

HUB_CONFIG_NAME = "hub_config.json"
DEFAULT_HUB_DATA_DIR = "data-hub"
LEGACY_DATA_DIR = "data"
UPDATE_DIR_NAME = "Update"


def hub_config_path() -> Path:
    return (BASE_DIR / HUB_CONFIG_NAME).resolve()


def _read_hub_config_data_dir() -> Path | None:
    cfg = hub_config_path()
    if not cfg.is_file():
        return None
    try:
        raw = json.loads(cfg.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        dd = str(raw.get("data_dir") or DEFAULT_HUB_DATA_DIR).strip() or DEFAULT_HUB_DATA_DIR
        p = Path(dd)
        if not p.is_absolute():
            p = (BASE_DIR / dd).resolve()
        return p
    except Exception:
        return None


def _score_data_directory(path: Path) -> int:
    if not path.is_dir():
        return 0
    score = 0
    if (path / "main.sqlite").is_file():
        score += 100
    seans_p = path / "seans.sqlite"
    if seans_p.is_file():
        score += 50
        try:
            if seans_p.stat().st_size > 512_000:
                score += 40
        except OSError:
            pass
    if (path / "portal.sqlite").is_file():
        score += 10
    if (path / "seans_db_migrated.flag").is_file():
        score += 20
    return score


def _data_dir_candidates() -> list[Path]:
    return [
        (BASE_DIR / DEFAULT_HUB_DATA_DIR).resolve(),
        (BASE_DIR / LEGACY_DATA_DIR).resolve(),
    ]


def _pick_best_existing_data_dir(candidates: list[Path]) -> Path | None:
    scored = [( _score_data_directory(p), p) for p in candidates]
    scored = [(s, p) for s, p in scored if s > 0]
    if not scored:
        return None
    scored.sort(key=lambda item: (-item[0], str(item[1])))
    return scored[0][1]


def resolve_data_dir() -> Path:
    """
    Папка данных SQLite и служебных JSON.

    Приоритет:
    1) WEB_PORTAL_DATA_DIR
    2) hub_config.json → data_dir (для HUB по умолчанию data-hub)
    3) существующая папка с main.sqlite (data-hub или data)
    4) data-hub для HUB-проектов, иначе data
    """
    env = (os.environ.get("WEB_PORTAL_DATA_DIR") or "").strip()
    if env:
        return Path(env).resolve()

    candidates = _data_dir_candidates()
    best_existing = _pick_best_existing_data_dir(candidates)

    from_hub = _read_hub_config_data_dir()
    if from_hub is not None:
        preferred = from_hub.resolve()
        if best_existing is not None and best_existing != preferred:
            pref_score = _score_data_directory(preferred)
            best_score = _score_data_directory(best_existing)
            # hub_config → data-hub, а сеансы лежат в data/ — типичная причина «пустой» таблицы
            if best_score >= pref_score + 40:
                return best_existing
        return preferred

    if best_existing is not None:
        return best_existing

    if hub_config_path().is_file() or (BASE_DIR / "hub_main.py").is_file():
        return (BASE_DIR / DEFAULT_HUB_DATA_DIR).resolve()

    return (BASE_DIR / LEGACY_DATA_DIR).resolve()


def detect_data_dir_mismatch_warning() -> str | None:
    """
    Предупреждение, если реальные БД лежат в другой data*/ папке (типичная ошибка HUB).
    """
    current = resolve_data_dir().resolve()
    alts: list[tuple[int, Path]] = []
    for name in (DEFAULT_HUB_DATA_DIR, LEGACY_DATA_DIR):
        p = (BASE_DIR / name).resolve()
        if p == current or not p.is_dir():
            continue
        score = _score_data_directory(p)
        if score > _score_data_directory(current):
            alts.append((score, p))
    if not alts:
        return None
    alts.sort(key=lambda item: (-item[0], str(item[1])))
    best = alts[0][1]
    return (
        f"Активная папка данных: {current}. "
        f"Но более полные БД найдены в {best}. "
        f"Проверьте hub_config.json -> data_dir (для HUB обычно «{DEFAULT_HUB_DATA_DIR}»)."
    )


DATA_DIR = resolve_data_dir()
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_DB_NAME = "main.sqlite"
PORTAL_DB_NAME = "portal.sqlite"  # пользователи/роли
SEARCH_ONLINE_DB_NAME = "search_online.sqlite"  # отдельная БД для поиска онлайн
SEANSES_DB_NAME = "seans.sqlite"  # сеансы + автопоиск (отдельно от перехватов)
ALLOWED_DB_EXTENSIONS = {".sqlite", ".db"}


def safe_db_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return DEFAULT_DB_NAME
    # запрещаем вложенные пути/диски
    name = name.replace("\\", "/")
    if "/" in name or ":" in name:
        raise ValueError("Недопустимое имя БД")
    if not any(name.lower().endswith(ext) for ext in ALLOWED_DB_EXTENSIONS):
        name = f"{name}.sqlite"
    return name


def db_path(db_name: str) -> Path:
    return (DATA_DIR / safe_db_name(db_name)).resolve()


def portal_db_path() -> Path:
    return (DATA_DIR / PORTAL_DB_NAME).resolve()


def search_online_db_path() -> Path:
    """Путь к отдельной БД для поиска онлайн."""
    return (DATA_DIR / SEARCH_ONLINE_DB_NAME).resolve()


def seans_db_path() -> Path:
    """Путь к отдельной БД сеансов (см. lib/seans_db.py)."""
    return (DATA_DIR / SEANSES_DB_NAME).resolve()


def seans_watch_stop_path() -> Path:
    """Файл-флаг остановки фонового автопоиска сеансов (отдельный процесс)."""
    return (DATA_DIR / "seans_watch_stop.request").resolve()


def seans_watch_status_path() -> Path:
    """JSON со статусом автопоиска (пишет воркер-процесс)."""
    return (DATA_DIR / "seans_watch_status.json").resolve()


def seans_watch_autostart_path() -> Path:
    """JSON: автозапуск автопоиска при старте приложения (папка, позиция, интервал)."""
    return (DATA_DIR / "seans_watch_autostart.json").resolve()


def deploy_announce_path() -> Path:
    """
    JSON с уведомлением «доступно обновление» для открытых вкладок в ЛВС.
    По умолчанию: data/deploy_announce.json рядом с данными.
    Переопределение: переменная WEB_PORTAL_DEPLOY_ANNOUNCE_PATH (в т.ч. UNC \\\\share\\...)
    """
    raw = (os.environ.get("WEB_PORTAL_DEPLOY_ANNOUNCE_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (DATA_DIR / "deploy_announce.json").resolve()


def updates_dir() -> Path:
    """Каталог опубликованных пакетов обновления HUB на центральном SERVER.

    Путь можно переопределить через ``WEB_PORTAL_UPDATE_DIR`` (например,
    отдельным диском), но по умолчанию это папка ``Update`` рядом с SERVER.exe.
    Она намеренно не лежит в ``data-central``: обновления — это дистрибутивы,
    а не рабочие данные портала.
    """
    raw = (os.environ.get("WEB_PORTAL_UPDATE_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (BASE_DIR / UPDATE_DIR_NAME).resolve()
