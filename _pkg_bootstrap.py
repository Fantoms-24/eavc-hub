"""Регистрация директории проекта как пакета ``web_portal``.

Зачем: точки входа (``python app.py``, ``python server_main.py`` и т.д.)
импортируют модули как ``web_portal.*``. Раньше это работало только если
папка проекта называлась ровно ``web_portal`` — при копировании проекта в
папку с другим именем (например, ``Copy``) Python находил в родительской
директории СТАРУЮ копию ``web_portal`` и импортировал её, что приводило к
ошибкам вида ``ModuleNotFoundError: No module named 'web_portal.webapp'``.

Этот модуль явно регистрирует ТЕКУЩУЮ директорию как пакет ``web_portal``,
поэтому проект можно запускать из папки с любым именем, а случайные старые
копии рядом не мешают.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def ensure_web_portal_package() -> None:
    """Гарантирует, что ``web_portal`` в sys.modules указывает на эту директорию."""
    if getattr(sys, "frozen", False):
        # PyInstaller: модули уже упакованы в бандл, вмешиваться не нужно.
        return

    mod = sys.modules.get("web_portal")
    if mod is not None:
        paths = []
        for p in getattr(mod, "__path__", None) or []:
            try:
                paths.append(Path(p).resolve())
            except OSError:
                continue
        if BASE_DIR in paths:
            return  # уже корректно импортирован (например, python -m web_portal.app)
        # Импортирована чужая/старая копия — выгружаем её и все подмодули.
        stale = [n for n in sys.modules if n == "web_portal" or n.startswith("web_portal.")]
        for name in stale:
            del sys.modules[name]

    init_py = BASE_DIR / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "web_portal",
        init_py,
        submodule_search_locations=[str(BASE_DIR)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - защитная ветка
        raise ImportError(f"Не удалось создать spec для пакета web_portal из {init_py}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["web_portal"] = module
    spec.loader.exec_module(module)


ensure_web_portal_package()
