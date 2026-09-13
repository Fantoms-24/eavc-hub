#!/usr/bin/env python3
"""
Перенос таблиц сеансов из main.sqlite в seans.sqlite.

Запуск (можно при остановленном HUB или через Админ → Настройки):
  python scripts/migrate_seans_to_separate_db.py
  python scripts/migrate_seans_to_separate_db.py --data-dir "C:\\path\\to\\data"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))


def _bootstrap_data_dir_from_args(data_dir_arg: str) -> None:
    if data_dir_arg:
        os.environ["WEB_PORTAL_DATA_DIR"] = str(Path(data_dir_arg).resolve())
        return
    if os.environ.get("WEB_PORTAL_DATA_DIR"):
        return
    hub_cfg = ROOT / "hub_config.json"
    if hub_cfg.is_file():
        return
    # Явный fallback для HUB без hub_config.json
    data_hub = (ROOT / "data-hub").resolve()
    if data_hub.is_dir():
        os.environ.setdefault("WEB_PORTAL_DATA_DIR", str(data_hub))


def main() -> None:
    ap = argparse.ArgumentParser(description="Migrate seans tables to seans.sqlite")
    ap.add_argument(
        "--data-dir",
        default="",
        help="WEB_PORTAL_DATA_DIR (для HUB: .../data-hub)",
    )
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    _bootstrap_data_dir_from_args(args.data_dir)

    from web_portal.config import DATA_DIR, detect_data_dir_mismatch_warning, hub_config_path
    from web_portal.lib.seans_migrate import run_seans_db_migration

    print("DATA_DIR:", DATA_DIR)
    print("hub_config:", hub_config_path())
    warn = detect_data_dir_mismatch_warning()
    if warn:
        print("WARNING:", warn)
    result = run_seans_db_migration(dry_run=bool(args.dry_run))
    if not result.get("ok"):
        print("FAILED:", result.get("error"))
        raise SystemExit(1)
    print(result.get("message") or "OK")
    if result.get("counts_main"):
        print("counts_main:", result["counts_main"])
    if result.get("counts_seans"):
        print("counts_seans:", result["counts_seans"])
    raise SystemExit(0)


if __name__ == "__main__":
    main()
