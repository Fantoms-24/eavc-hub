from __future__ import annotations

import logging
import os
import queue
import threading
from dataclasses import dataclass
from typing import Callable

_LOG = logging.getLogger("web_portal.background_jobs")


@dataclass(frozen=True)
class BackgroundJob:
    name: str
    run: Callable[[], None]


class BackgroundJobRunner:
    """Small bounded in-process queue for long portal tasks."""

    def __init__(self, *, workers: int = 2, maxsize: int = 64) -> None:
        self._queue: queue.Queue[BackgroundJob] = queue.Queue(maxsize=maxsize)
        self._started = False
        self._lock = threading.Lock()
        self._workers = max(1, int(workers or 1))

    def start(self) -> None:
        with self._lock:
            if self._started:
                return
            self._started = True
            for idx in range(self._workers):
                thread = threading.Thread(
                    target=self._worker,
                    name=f"wp-bg-job-{idx + 1}",
                    daemon=True,
                )
                thread.start()

    def submit(self, name: str, run: Callable[[], None]) -> bool:
        self.start()
        try:
            self._queue.put_nowait(BackgroundJob(name=str(name or "job"), run=run))
            return True
        except queue.Full:
            return False

    def _worker(self) -> None:
        while True:
            job = self._queue.get()
            try:
                job.run()
            except Exception:
                _LOG.exception("Background job failed: %s", job.name)
            finally:
                self._queue.task_done()


def _runner_workers_from_env() -> int:
    raw = os.environ.get("WEB_PORTAL_BG_WORKERS") or "2"
    try:
        return max(1, min(8, int(raw)))
    except Exception:
        return 2


default_runner = BackgroundJobRunner(workers=_runner_workers_from_env())
