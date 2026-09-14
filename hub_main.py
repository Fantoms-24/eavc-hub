from __future__ import annotations

import json
import os
import sys
from pathlib import Path
import logging

_log = logging.getLogger("web_portal.hub_main")

def _ensure_import_path_for_web_portal() -> None:
    """Регистрирует текущий каталог как ``web_portal`` при запуске исходников.

    Рабочая папка может называться как угодно (например, ``Copy``), поэтому
    одного добавления родительского пути в ``sys.path`` недостаточно.
    """
    root = Path(__file__).resolve().parent
    parent = root.parent
    if str(parent) not in sys.path:
        sys.path.insert(0, str(parent))
    bootstrap = root / "_pkg_bootstrap.py"
    if getattr(sys, "frozen", False) or not bootstrap.exists():
        return
    import importlib.util as importlib_util

    spec = importlib_util.spec_from_file_location("_pkg_bootstrap", bootstrap)
    if spec is not None and spec.loader is not None:
        module = importlib_util.module_from_spec(spec)
        sys.modules.setdefault("_pkg_bootstrap", module)
        spec.loader.exec_module(module)


def _root_dir() -> Path:
    # В PyInstaller (onedir) хотим держать конфиги/данные рядом с HUB.exe
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_or_create_config(cfg_path: Path) -> dict:
    default_cfg = {
        # Куда биндим сервер. Можно указать конкретный IP адаптера (например "192.168.1.100")
        # или оставить "0.0.0.0", чтобы быть доступным по всем IP компьютера.
        "bind_host": "0.0.0.0",
        "port": 5000,
        "debug": False,
        # Потоки Waitress для одновременных операторов на одном Хабе
        "wsgi_threads": 8,
        # SQLite: кэш страниц (MB). На ПК с 12+ GB RAM можно 128–256 для ускорения.
        "sqlite_cache_mb": 24,
        "sqlite_mmap_mb": 64,
        # Автопоиск: интервал между полными проходами по сетевой папке (сек).
        "seans_watch_interval_sec": 10,
        # Сколько папок-частот обрабатывать параллельно за цикл.
        "seans_watch_freq_parallel": 5,
        # Интервал синхронизации с центральным сервером (сек). 5 с не создаёт
        # постоянную нагрузку на SERVER при трёх позициях.
        "sync_interval_sec": 5.0,
        # Папка данных (SQLite/конфиги) рядом с HUB.exe
        "data_dir": "data-hub",
        # Папка с тайлами карты (z/x/y.png) — по умолчанию "tiles" в корне с exe
        "tiles_dir": "tiles",
        # Адрес центрального сервера для синхронизации (например "http://192.168.1.10:5000")
        # Оставьте пустым, если Hub работает автономно
        "sync_upstream": "",
        # Секретный ключ для синхронизации (должен совпадать с ключом на центральном сервере)
        "sync_key": "",
        # Позиции для синхронизации (через запятую). Пусто = все позиции.
        "sync_positions": "",
        # Синхронизировать seanses (таблица сеансов). false = только перехваты.
        "sync_seanses": True,
        # Каталог с Tempfinder*.xml задания поста (ArmTask) или путь к одному XML.
        # Пусто — только переменная окружения WEB_PORTAL_ARM_TASK_XML_DIR или путь в БД (админ).
        "arm_task_xml_dir": "",
        # EAVC Manager (Ollama): модель должна быть установлена (ollama list)
        "ai": {
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "qwen2.5:7b-instruct-q4_K_M",
            "embed_model": "nomic-embed-text",
            "timeout_sec": 240,
            "enabled": True,
        },
    }
    try:
        if not cfg_path.exists():
            cfg_path.write_text(
                json.dumps(default_cfg, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return dict(default_cfg)
        data = json.loads(cfg_path.read_text(encoding="utf-8") or "{}") or {}
        if not isinstance(data, dict):
            return dict(default_cfg)
        merged = dict(default_cfg)
        merged.update({k: v for k, v in data.items() if v is not None})
        return merged
    except Exception:
        return dict(default_cfg)


def main() -> None:
    """
    Entrypoint для сборки HUB в EXE.
    На офлайн-ПК можно просто запустить HUB.exe — данные будут храниться рядом, в папке data-hub/.
    """
    _ensure_import_path_for_web_portal()
    root = _root_dir()
    cfg_path = (root / "hub_config.json").resolve()
    cfg = _load_or_create_config(cfg_path)

    if getattr(sys, "frozen", False):
        os.environ.setdefault("WEB_PORTAL_EXE_ROOT", str(root.resolve()))

    try:
        from web_portal.lib.network_summary_export import apply_intensity_template_env

        apply_intensity_template_env(root)
    except Exception:
        _log.debug("main: suppressed error", exc_info=True)

    os.environ.setdefault("WEB_PORTAL_PORT", str(cfg.get("port", 5000)))
    os.environ.setdefault("WEB_PORTAL_DEBUG", "1" if cfg.get("debug") else "0")
    data_dir = str(cfg.get("data_dir") or "data-hub")
    if not os.path.isabs(data_dir):
        data_dir = str((root / data_dir).resolve())
    os.environ.setdefault("WEB_PORTAL_DATA_DIR", data_dir)

    # Папка с тайлами: tiles_dir из конфига или по умолчанию "Карта", затем "tiles"
    tiles_dir = str(cfg.get("tiles_dir") or "").strip()
    if not tiles_dir:
        for name in ("Карта", "tiles"):
            candidate = root / name
            if candidate.exists() and candidate.is_dir():
                tiles_dir = name
                break
        if not tiles_dir:
            tiles_dir = "tiles"
    if tiles_dir:
        tiles_path = Path(tiles_dir)
        if not tiles_path.is_absolute():
            tiles_path = (root / tiles_dir).resolve()
        if tiles_path.exists() and tiles_path.is_dir():
            os.environ.setdefault("WEB_PORTAL_MAP_TILES_DIR", str(tiles_path))

    # Настройка синхронизации с центральным сервером
    sync_upstream = str(cfg.get("sync_upstream") or "").strip()
    sync_key = str(cfg.get("sync_key") or "").strip()
    sync_positions = str(
        cfg.get("sync_positions") or cfg.get("sync_position") or ""
    ).strip()
    sync_seanses = cfg.get("sync_seanses")
    sync_seanses_flag = None
    if isinstance(sync_seanses, bool):
        sync_seanses_flag = "1" if sync_seanses else "0"
    elif isinstance(sync_seanses, (int, float)):
        sync_seanses_flag = "1" if int(sync_seanses) else "0"
    elif isinstance(sync_seanses, str):
        s = sync_seanses.strip().lower()
        if s in {"1", "true", "yes", "on"}:
            sync_seanses_flag = "1"
        elif s in {"0", "false", "no", "off"}:
            sync_seanses_flag = "0"
    if sync_upstream:
        os.environ.setdefault("WEB_PORTAL_SYNC_UPSTREAM", sync_upstream)
    if sync_key:
        os.environ.setdefault("WEB_PORTAL_SYNC_KEY", sync_key)
    if sync_positions:
        os.environ.setdefault("WEB_PORTAL_SYNC_POSITIONS", sync_positions)
    if sync_seanses_flag is not None:
        os.environ.setdefault("WEB_PORTAL_SYNC_SEANSES", sync_seanses_flag)

    arm_task_dir = str(cfg.get("arm_task_xml_dir") or "").strip()
    if arm_task_dir:
        os.environ.setdefault("WEB_PORTAL_ARM_TASK_XML_DIR", arm_task_dir)

    from web_portal.lib.ai_env import apply_ai_env_from_config

    apply_ai_env_from_config(cfg)

    sync_interval_sec = cfg.get("sync_interval_sec")
    if sync_interval_sec is not None:
        os.environ.setdefault("WEB_PORTAL_SYNC_INTERVAL_SEC", str(sync_interval_sec))

    wsgi_threads = int(cfg.get("wsgi_threads") or 8)
    os.environ.setdefault("WEB_PORTAL_WSGI_THREADS", str(wsgi_threads))

    sqlite_cache = cfg.get("sqlite_cache_mb")
    if sqlite_cache is not None:
        os.environ.setdefault("WEB_PORTAL_SQLITE_CACHE_MB", str(int(sqlite_cache)))
    sqlite_mmap = cfg.get("sqlite_mmap_mb")
    if sqlite_mmap is not None:
        os.environ.setdefault("WEB_PORTAL_SQLITE_MMAP_MB", str(int(sqlite_mmap)))
    watch_interval = cfg.get("seans_watch_interval_sec")
    if watch_interval is not None:
        os.environ.setdefault(
            "WEB_PORTAL_SEANS_WATCH_INTERVAL_SEC", str(float(watch_interval))
        )
    watch_parallel = cfg.get("seans_watch_freq_parallel")
    if watch_parallel is not None:
        os.environ.setdefault(
            "WEB_PORTAL_SEANS_WATCH_FREQ_PARALLEL", str(int(watch_parallel))
        )

    from app import create_app
    from web_portal.lib.wsgi_server import run_wsgi_server

    app = create_app()
    port = int(os.environ.get("WEB_PORTAL_PORT", "5000"))
    debug = (os.environ.get("WEB_PORTAL_DEBUG") or "").strip() == "1"
    bind_host = str(cfg.get("bind_host") or "0.0.0.0").strip() or "0.0.0.0"
    run_wsgi_server(app, host=bind_host, port=port, debug=debug, threads=wsgi_threads)


if __name__ == "__main__":
    # Дочерний процесс автопоиска: иначе HUB.exe с флагом поднимал бы второй Flask, а не цикл result0.
    if len(sys.argv) > 1 and sys.argv[1] == "--seans-watch-worker":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        _ensure_import_path_for_web_portal()
        root = _root_dir()
        cfg_path = (root / "hub_config.json").resolve()
        cfg = _load_or_create_config(cfg_path)
        if getattr(sys, "frozen", False):
            os.environ.setdefault("WEB_PORTAL_EXE_ROOT", str(root.resolve()))
        data_dir = str(cfg.get("data_dir") or "data-hub")
        if not os.path.isabs(data_dir):
            data_dir = str((root / data_dir).resolve())
        os.environ["WEB_PORTAL_DATA_DIR"] = data_dir
        from web_portal.seans_watch_child import main as _seans_watch_main

        _seans_watch_main()
        raise SystemExit(0)
    main()
