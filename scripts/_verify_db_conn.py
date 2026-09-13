import importlib.util
import sqlite3
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root.parent))
bs = root / "_pkg_bootstrap.py"
spec = importlib.util.spec_from_file_location("_pkg_bootstrap", bs)
m = importlib.util.module_from_spec(spec)
sys.modules["_pkg_bootstrap"] = m
assert spec.loader
spec.loader.exec_module(m)

from web_portal.lib.db import (
    _SCHEMA_READY_PATHS,
    connect,
    create_ai_job,
    enqueue_sync_outbox,
    init_db,
)
from web_portal.lib.db.connection import connect as c2
from web_portal.lib.db.connection import init_db as i2

print("modules", connect.__module__, init_db.__module__, c2 is connect, i2 is init_db)
c = sqlite3.connect(":memory:")
c.row_factory = sqlite3.Row
init_db(c)
names = [
    r[0]
    for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY 1"
    ).fetchall()
]
print("tables", names[:10])
print("ai", create_ai_job(c, task_type="t", params={}))
print("outbox", enqueue_sync_outbox(c, kind="k", payload={}))
print("schema_paths", type(_SCHEMA_READY_PATHS).__name__)

from web_portal.app import create_app

app = create_app()
print("app OK", len(list(app.url_map.iter_rules())))
