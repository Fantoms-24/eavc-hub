"""Extract remaining _impl domains: intensity, analysis, asr, map; move add_ai_feedback to ai."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMPL = ROOT / "lib" / "db" / "_impl.py"
AI = ROOT / "lib" / "db" / "ai.py"
MISC = ROOT / "lib" / "db" / "misc.py"
STATS = ROOT / "lib" / "db" / "stats.py"

GROUPS: dict[str, list[str]] = {
    "network_intensity": [
        "_finalize_intensity_cluster_map",
        "_merge_intensity_agg_row",
        "get_network_intensity_clusters",
        "get_network_intensity_clusters_dual",
        "_dt_time_part",
        "_is_calendar_day_start",
        "_is_calendar_day_end",
        "_date_only_window",
        "_network_prev_daily_window",
        "get_network_intensity_clusters_dual_daily",
    ],
    "analysis_data": [
        "_parse_duty_codes",
        "_format_duty_codes",
        "get_analysis_assignments",
        "set_analysis_assignment",
        "list_analysis_assignments_since",
    ],
    "asr": [
        "add_asr_train_sample",
        "list_asr_train_samples",
        "create_asr_training_run",
        "finish_asr_training_run",
        "upsert_asr_model",
        "list_asr_models",
        "activate_asr_model",
        "get_active_asr_model",
        "get_asr_settings",
        "set_asr_settings",
        "add_asr_feedback",
        "count_asr_feedback",
    ],
    "map_shared": [
        "get_map_shared_objects",
        "get_map_shared_objects_all",
        "save_map_shared_objects",
    ],
}

HEADERS = {
    "network_intensity": '''"""Кластеры интенсивности сетей (физически из ``_impl``)."""
from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db
from web_portal.lib.db.units import (
    _build_unit_name_map_for_pairs,
    _is_unknown_intensity_unit_name,
    _sql_freq_zone_expr,
    canonical_intensity_unit_key,
)


''',
    "analysis_data": '''"""Analysis assignments (физически из ``_impl``)."""
from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db
from web_portal.lib.db.sql_util import _in_clause


''',
    "asr": '''"""ASR train/models/feedback (физически из ``_impl``)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db


''',
    "map_shared": '''"""Общие объекты карты (физически из ``_impl``)."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db


''',
}


def src_of(src: str, node: ast.AST) -> str:
    seg = ast.get_source_segment(src, node)
    if seg is None:
        raise RuntimeError("no source")
    return seg.rstrip() + "\n"


def main() -> None:
    src = IMPL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    nodes = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    # move add_ai_feedback into ai.py
    if "add_ai_feedback" not in nodes:
        raise SystemExit("add_ai_feedback missing")
    ai_fn = src_of(src, nodes["add_ai_feedback"])
    # inject init_db import inside function if not at ai module level
    ai_text = AI.read_text(encoding="utf-8")
    if "def add_ai_feedback" not in ai_text:
        # ensure init_db available
        if "from web_portal.lib.db.connection import init_db" not in ai_text:
            ai_text = ai_text.replace(
                "import sqlite3\n",
                "import sqlite3\n\nfrom web_portal.lib.db.connection import init_db\n",
                1,
            )
        # insert before __all__ if present else append
        if "\n__all__" in ai_text:
            ai_text = ai_text.replace("\n__all__", "\n" + ai_fn + "\n__all__", 1)
            ai_text = ai_text.replace(
                "__all__ = [",
                '__all__ = [\n    "add_ai_feedback",',
                1,
            )
        else:
            ai_text = ai_text.rstrip() + "\n\n" + ai_fn
        AI.write_text(ai_text, encoding="utf-8")
        ast.parse(AI.read_text(encoding="utf-8"))
        print("moved add_ai_feedback -> ai.py")

    remove: set[int] = set()
    remove.update(
        range(
            nodes["add_ai_feedback"].lineno,
            (nodes["add_ai_feedback"].end_lineno or nodes["add_ai_feedback"].lineno)
            + 1,
        )
    )

    reexports: list[str] = []

    for mod_name, names in GROUPS.items():
        missing = [n for n in names if n not in nodes]
        if missing:
            raise SystemExit(f"{mod_name} missing {missing}")
        parts = [HEADERS[mod_name]]
        for name in names:
            parts.append(src_of(src, nodes[name]))
            parts.append("")
            n = nodes[name]
            remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
        public = [n for n in names if not n.startswith("_")]
        parts.append("__all__ = [")
        for n in public:
            parts.append(f'    "{n}",')
        parts.append("]")
        parts.append("")
        out = ROOT / "lib" / "db" / f"{mod_name}.py"
        out.write_text("\n".join(parts).rstrip() + "\n", encoding="utf-8")
        ast.parse(out.read_text(encoding="utf-8"))
        print("wrote", out.name, sum(1 for _ in out.open(encoding="utf-8")), "lines")
        ix = "\n".join(f"    {n}," for n in sorted(names))
        reexports.append(
            f"\n# --- {mod_name} (physically extracted) ---\n"
            f"from web_portal.lib.db.{mod_name} import (  # noqa: E402,F401\n"
            f"{ix}\n)\n"
        )

    # also remove dead helpers if present
    for dead in ("_json_dump_compact", "_json_load_object", "_frequency_sort_key"):
        if dead in nodes:
            n = nodes[dead]
            remove.update(range(n.lineno, (n.end_lineno or n.lineno) + 1))
            print("drop dead", dead)

    # keep _get_last_recorded_by_freq_group in _impl for now (legacy)
    lines = src.splitlines(keepends=True)
    text = "".join(ln for i, ln in enumerate(lines, 1) if i not in remove)
    while "\n\n\n\n" in text:
        text = text.replace("\n\n\n\n", "\n\n\n")

    # Drop unused heavy imports from _impl if no longer needed
    # Keep minimal header
    # Append reexports before first existing domain reexport or at end
    block = "\n".join(reexports) + "\n# --- ai.add_ai_feedback ---\nfrom web_portal.lib.db.ai import add_ai_feedback  # noqa: E402,F401\n"
    if "# --- sql_util" in text:
        text = text.replace("# --- sql_util", block + "\n# --- sql_util")
    else:
        text = text.rstrip() + "\n" + block

    IMPL.write_text(text.rstrip() + "\n", encoding="utf-8")
    ast.parse(IMPL.read_text(encoding="utf-8"))
    print("updated _impl.py", sum(1 for _ in IMPL.open(encoding="utf-8")), "lines")

    # stats: _date_only_window from network_intensity
    stats = STATS.read_text(encoding="utf-8")
    stats = stats.replace(
        "from web_portal.lib.db._impl import _date_only_window",
        "from web_portal.lib.db.network_intensity import _date_only_window",
    )
    STATS.write_text(stats, encoding="utf-8")
    print("updated stats.py")

    # rewrite misc facade
    MISC.write_text(
        '''"""Прочие операции данных — фасад над физическими доменами."""
from __future__ import annotations

from web_portal.lib.db.ai import add_ai_feedback  # noqa: F401
from web_portal.lib.db.network_intensity import (  # noqa: F401
    get_network_intensity_clusters,
    get_network_intensity_clusters_dual,
    get_network_intensity_clusters_dual_daily,
)
from web_portal.lib.db.analysis_data import (  # noqa: F401
    get_analysis_assignments,
    set_analysis_assignment,
    list_analysis_assignments_since,
)
from web_portal.lib.db.online_search import (  # noqa: F401
    merge_families_by_manual_groups,
    list_archive_freq_by_note,
)
from web_portal.lib.db.seans_write import (  # noqa: F401
    was_processed,
    mark_processed,
    save_all_from_dir,
    import_folder,
    import_folder_with_client,
    import_folder_incremental,
)
from web_portal.lib.db.stats import format_ids  # noqa: F401
from web_portal.lib.db.asr import (  # noqa: F401
    add_asr_train_sample,
    list_asr_train_samples,
    create_asr_training_run,
    finish_asr_training_run,
    upsert_asr_model,
    list_asr_models,
    activate_asr_model,
    get_active_asr_model,
    get_asr_settings,
    set_asr_settings,
    add_asr_feedback,
    count_asr_feedback,
)
from web_portal.lib.db.map_shared import (  # noqa: F401
    get_map_shared_objects,
    get_map_shared_objects_all,
    save_map_shared_objects,
)

__all__ = [
    "add_ai_feedback",
    "get_network_intensity_clusters",
    "get_network_intensity_clusters_dual",
    "get_network_intensity_clusters_dual_daily",
    "get_analysis_assignments",
    "set_analysis_assignment",
    "list_analysis_assignments_since",
    "was_processed",
    "mark_processed",
    "save_all_from_dir",
    "import_folder",
    "import_folder_with_client",
    "import_folder_incremental",
    "format_ids",
    "add_asr_train_sample",
    "list_asr_train_samples",
    "create_asr_training_run",
    "finish_asr_training_run",
    "upsert_asr_model",
    "list_asr_models",
    "activate_asr_model",
    "get_active_asr_model",
    "get_asr_settings",
    "set_asr_settings",
    "add_asr_feedback",
    "count_asr_feedback",
    "get_map_shared_objects",
    "get_map_shared_objects_all",
    "save_map_shared_objects",
    "merge_families_by_manual_groups",
    "list_archive_freq_by_note",
]
''',
        encoding="utf-8",
    )
    print("updated misc.py")

    init_py = ROOT / "lib" / "db" / "__init__.py"
    init_py.write_text(
        '''"""Пакет доступа к данным (SQLite).

Доменные модули (физически вынесены):

    from web_portal.lib.db.intercepts import list_intercept_catalog
    from web_portal.lib.db.connection import connect

``_impl`` оставлен как тонкий re-export / legacy glue
(``_get_last_recorded_by_freq_group`` и т.п.).
"""
from __future__ import annotations

from . import _impl as _impl

for _name in dir(_impl):
    if _name.startswith("__"):
        continue
    globals()[_name] = getattr(_impl, _name)

__all__ = [n for n in dir(_impl) if not n.startswith("__")]
''',
        encoding="utf-8",
    )
    print("updated __init__.py")


if __name__ == "__main__":
    main()
