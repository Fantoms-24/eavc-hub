"""Корневой conftest для pytest.

Решает две проблемы запуска тестов «из коробки»:

1. Проект импортируется как пакет ``web_portal`` (см. импорты в app.py и tests/),
   но каталог репозитория может называться иначе. Здесь мы либо добавляем
   родительский каталог в ``sys.path`` (если папка называется ``web_portal``),
   либо создаём алиас пакета вручную.

2. ``config.py`` на импорте вычисляет ``DATA_DIR`` и создаёт каталоги/БД.
   Чтобы тесты не трогали рабочие данные, подставляем временный каталог,
   если ``WEB_PORTAL_DATA_DIR`` не задан явно.
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent

# --- 1. Делаем проект импортируемым как пакет web_portal ---
if _ROOT.name == "web_portal":
    _parent = str(_ROOT.parent)
    if _parent not in sys.path:
        sys.path.insert(0, _parent)
elif "web_portal" not in sys.modules:
    _pkg = types.ModuleType("web_portal")
    _pkg.__path__ = [str(_ROOT)]  # type: ignore[attr-defined]
    _init = _ROOT / "__init__.py"
    if _init.is_file():
        _pkg.__file__ = str(_init)
    sys.modules["web_portal"] = _pkg

# --- 2. Изолируем данные тестов во временном каталоге ---
if not (os.environ.get("WEB_PORTAL_DATA_DIR") or "").strip():
    os.environ["WEB_PORTAL_DATA_DIR"] = tempfile.mkdtemp(
        prefix="web_portal_test_data_"
    )
