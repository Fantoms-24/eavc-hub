from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Отдельный процесс автопоиска сеансов (до тяжёлого import app)
if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "--seans-watch-worker":
    sys.argv = [sys.argv[0]] + sys.argv[2:]
    _root = Path(__file__).resolve().parent
    if str(_root.parent) not in sys.path:
        sys.path.insert(0, str(_root.parent))
    # Регистрируем эту директорию как пакет web_portal независимо от имени папки.
    _bs = _root / "_pkg_bootstrap.py"
    if not getattr(sys, "frozen", False) and _bs.exists():
        import importlib.util as _ilu

        _spec = _ilu.spec_from_file_location("_pkg_bootstrap", _bs)
        if _spec is not None and _spec.loader is not None:
            _m = _ilu.module_from_spec(_spec)
            sys.modules.setdefault("_pkg_bootstrap", _m)
            _spec.loader.exec_module(_m)
    from web_portal.seans_watch_child import main as _seans_watch_main

    _seans_watch_main()
    raise SystemExit(0)

def _root_dir() -> Path:
    # В PyInstaller (onedir) хотим держать конфиги/данные рядом с SERVER.exe
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


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


def _load_or_create_config(cfg_path: Path) -> dict:
    default_cfg = {
        # Куда биндим сервер. Можно указать конкретный IP адаптера (например "192.168.1.10")
        # или оставить "0.0.0.0", чтобы быть доступным по всем IP компьютера.
        "bind_host": "0.0.0.0",
        "port": 5000,
        "debug": False,
        # Потоки Waitress для одновременных операторов (Flask dev server — один поток)
        "wsgi_threads": 8,
        # Одновременные тяжёлые pull-запросы от HUB. Для трёх позиций — 3.
        "sync_pull_workers": 3,
        # Папка данных (SQLite/конфиги) рядом с SERVER.exe
        "data_dir": "data-central",
        # Папка ZIP-пакетов HUB рядом с SERVER.exe. Пакеты публикуются из админки.
        "update_dir": "Update",
        # Папка с тайлами карты (z/x/y.png) — по умолчанию "tiles" в корне с exe
        "tiles_dir": "tiles",
        # Секретный ключ для синхронизации (должен совпадать с ключом на Hub)
        # Оставьте пустым, если синхронизация не нужна
        "sync_key": "",
        # Адрес ПК-получателя новых перехватов (например "http://192.168.1.50:8787")
        "intercepts_forward_url": "",
        # Ключ авторизации для отправки перехватов на получатель (опционально)
        "intercepts_forward_key": "",
        # Таймаут HTTP-отправки в секундах
        "intercepts_forward_timeout_sec": 6,
        # Каталог с Tempfinder*.xml (задание поста) или один файл XML.
        "arm_task_xml_dir": "",
        "ai": {
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "qwen2.5:7b-instruct-q3_k_m",
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
    Entrypoint для сборки центрального сервера в EXE.
    На сервере можно просто запустить SERVER.exe — данные будут храниться рядом, в папке data-central/.
    """
    _ensure_import_path_for_web_portal()
    root = _root_dir()
    cfg_path = (root / "server_config.json").resolve()
    cfg = _load_or_create_config(cfg_path)

    # Корень рядом с EXE — чтобы карта из папки "Карта" рядом с exe находилась
    if getattr(sys, "frozen", False):
        os.environ.setdefault("WEB_PORTAL_EXE_ROOT", str(root.resolve()))

    os.environ.setdefault("WEB_PORTAL_PORT", str(cfg.get("port", 5000)))
    os.environ.setdefault("WEB_PORTAL_DEBUG", "1" if cfg.get("debug") else "0")
    os.environ.setdefault("WEB_PORTAL_SYNC_PULL_WORKERS", str(cfg.get("sync_pull_workers", 3)))
    data_dir = str(cfg.get("data_dir") or "data-central")
    if not os.path.isabs(data_dir):
        data_dir = str((root / data_dir).resolve())
    os.environ.setdefault("WEB_PORTAL_DATA_DIR", data_dir)
    update_dir = str(cfg.get("update_dir") or "Update")
    if not os.path.isabs(update_dir):
        update_dir = str((root / update_dir).resolve())
    os.environ.setdefault("WEB_PORTAL_UPDATE_DIR", update_dir)
    # Папка нужна оператору сразу после первого запуска SERVER, а не после
    # первого открытия админ-вкладки.
    Path(update_dir).mkdir(parents=True, exist_ok=True)

    # Папка с тайлами карты (z/x/y.png): tiles_dir из конфига или по умолчанию "Карта", затем "tiles"
    tiles_dir = str(cfg.get("tiles_dir") or "").strip()
    if not tiles_dir:
        # Сначала проверяем папку "Карта" рядом с exe, затем "tiles"
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

    # Настройка синхронизации (только ключ, без upstream - это только для Hub)
    sync_key = str(cfg.get("sync_key") or "").strip()
    if sync_key:
        os.environ.setdefault("WEB_PORTAL_SYNC_KEY", sync_key)
    intercepts_forward_url = str(cfg.get("intercepts_forward_url") or "").strip()
    intercepts_forward_key = str(cfg.get("intercepts_forward_key") or "").strip()
    intercepts_forward_timeout_sec = cfg.get("intercepts_forward_timeout_sec")
    if intercepts_forward_url:
        os.environ.setdefault(
            "WEB_PORTAL_INTERCEPT_FORWARD_URL", intercepts_forward_url
        )
    if intercepts_forward_key:
        os.environ.setdefault(
            "WEB_PORTAL_INTERCEPT_FORWARD_KEY", intercepts_forward_key
        )
    if intercepts_forward_timeout_sec is not None:
        os.environ.setdefault(
            "WEB_PORTAL_INTERCEPT_FORWARD_TIMEOUT_SEC",
            str(intercepts_forward_timeout_sec),
        )

    arm_task_dir = str(cfg.get("arm_task_xml_dir") or "").strip()
    if arm_task_dir:
        os.environ.setdefault("WEB_PORTAL_ARM_TASK_XML_DIR", arm_task_dir)

    from web_portal.lib.ai_env import apply_ai_env_from_config

    apply_ai_env_from_config(cfg)

    wsgi_threads = int(cfg.get("wsgi_threads") or 8)
    os.environ.setdefault("WEB_PORTAL_WSGI_THREADS", str(wsgi_threads))

    # Импорт только после установки переменных окружения. Иначе config.py успевал
    # выбрать data-hub до чтения server_config.json, и SERVER подхватывал данные HUB.
    from app import create_app

    app = create_app()
    port = int(os.environ.get("WEB_PORTAL_PORT", "5000"))
    debug = (os.environ.get("WEB_PORTAL_DEBUG") or "").strip() == "1"
    bind_host = str(cfg.get("bind_host") or "0.0.0.0").strip() or "0.0.0.0"
    from web_portal.lib.wsgi_server import run_wsgi_server

    run_wsgi_server(app, host=bind_host, port=port, debug=debug, threads=wsgi_threads)


if __name__ == "__main__":
    main()
