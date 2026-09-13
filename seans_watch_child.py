"""
Отдельный процесс автопоиска сеансов (result0.txt).
Запуск: python seans_watch_child.py --position ... --folder ... --interval 5
Или из сборки: SERVER.exe --seans-watch-worker --position ... (см. server_main.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from datetime import datetime
from pathlib import Path

_pkg = Path(__file__).resolve().parent
if str(_pkg.parent) not in sys.path:
    sys.path.insert(0, str(_pkg.parent))

from web_portal.config import DATA_DIR, seans_watch_status_path, seans_watch_stop_path
from web_portal.lib.seans_watch_core import (
    run_seans_watch_loop,
    wait_interruptible_seconds,
)

_log = logging.getLogger("web_portal.seans_watch_child")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    ap = argparse.ArgumentParser(description="Фоновый автопоиск сеансов (отдельный процесс)")
    ap.add_argument("--position", required=True, help="Имя позиции (клиент)")
    ap.add_argument("--folder", required=True, help="Корневая папка с result0")
    ap.add_argument("--interval", type=float, default=5.0, help="Интервал опроса, сек")
    args = ap.parse_args()

    logging.getLogger("web_portal.seans_watch").info(
        "Старт воркера автопоиска: DATA_DIR=%s позиция=%s папка=%s",
        DATA_DIR,
        args.position,
        args.folder,
    )

    stop_path = seans_watch_stop_path()
    try:
        stop_path.unlink(missing_ok=True)
    except Exception:
        _log.debug("main: suppressed error", exc_info=True)

    status: dict[str, object] = {
        "running": True,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "mode": "subprocess",
        "position_name": args.position,
        "folder_path": args.folder,
        "watch_folder": args.folder,
        "interval_sec": args.interval,
        "last_check_at": None,
        "last_message": "Воркер автопоиска сеансов",
        "last_error": "",
        "files_seen": 0,
        "files_processed": 0,
        "rows_parsed": 0,
        "freq_dirs_scanned": 0,
        "time_dirs_scanned": 0,
        "result0_found": 0,
        "skipped_unchanged": 0,
        "skipped_already_in_db": 0,
        "seeded_freqs": 0,
        "last_cycle_ms": 0,
        "scan_in_progress": False,
        "scan_progress_pct": 0,
        "scan_freq_done": 0,
        "scan_freq_total": 0,
        "scan_time_done": 0,
        "scan_time_total": 0,
        "scan_current_freq": "",
    }
    lock = threading.Lock()
    st_path = seans_watch_status_path()

    def should_stop() -> bool:
        return stop_path.exists()

    def wait_secs(s: float) -> None:
        wait_interruptible_seconds(s, should_stop)

    run_seans_watch_loop(
        position_name=args.position,
        folder_path=args.folder,
        interval_sec=float(args.interval),
        should_stop=should_stop,
        wait_secs=wait_secs,
        status=status,
        status_lock=lock,
        persist_status_path=st_path,
    )


if __name__ == "__main__":
    main()
