from __future__ import annotations

import logging
import os
import socket
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))
# Регистрируем эту директорию как пакет web_portal независимо от имени папки.
_bootstrap_py = BASE_DIR / "_pkg_bootstrap.py"
if not getattr(sys, "frozen", False) and _bootstrap_py.exists():
    import importlib.util as _ilu

    _bs_spec = _ilu.spec_from_file_location("_pkg_bootstrap", _bootstrap_py)
    if _bs_spec is not None and _bs_spec.loader is not None:
        _bs_mod = _ilu.module_from_spec(_bs_spec)
        sys.modules.setdefault("_pkg_bootstrap", _bs_mod)
        _bs_spec.loader.exec_module(_bs_mod)

from web_portal.config import DEFAULT_DB_NAME, db_path  # noqa: E402
from web_portal.lib.db import connect, ensure_db  # noqa: E402
from web_portal.lib.export_job_builders import build_export_job_result  # noqa: E402
from web_portal.lib.export_jobs import (  # noqa: E402
    claim_next_export_job,
    complete_claimed_export_job,
    fail_claimed_export_job,
    init_export_jobs,
)


LOG = logging.getLogger("web_portal.jobs_worker")


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def run_once(*, worker_id: str) -> bool:
    p = db_path(DEFAULT_DB_NAME)
    ensure_db(p)
    conn = connect(p)
    try:
        init_export_jobs(conn)
        job = claim_next_export_job(conn, worker_id=worker_id)
        if not job:
            return False
    finally:
        conn.close()

    job_id = int(job.get("id") or 0)
    try:
        result = build_export_job_result(BASE_DIR, job)
        conn = connect(p)
        try:
            complete_claimed_export_job(conn, job_id, result=result)
        finally:
            conn.close()
        LOG.info("completed export job %s (%s)", job_id, job.get("job_type"))
        return True
    except Exception as exc:
        conn = connect(p)
        try:
            fail_claimed_export_job(conn, job_id, error_text=str(exc), retry=True)
        finally:
            conn.close()
        LOG.exception("failed export job %s (%s)", job_id, job.get("job_type"))
        return True


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    worker_id = _worker_id()
    LOG.info("jobs worker started: %s", worker_id)
    idle_sleep = float(os.environ.get("WEB_PORTAL_JOBS_IDLE_SLEEP") or "1.5")
    while True:
        did_work = run_once(worker_id=worker_id)
        if not did_work:
            time.sleep(max(0.2, idle_sleep))


if __name__ == "__main__":
    raise SystemExit(main())
