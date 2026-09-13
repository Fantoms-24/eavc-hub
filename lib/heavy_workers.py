from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from typing import Callable, TypeVar

_LOG = logging.getLogger("web_portal.heavy_workers")

T = TypeVar("T")


class _SingleSlotPool:
    """
    Не более ``workers`` тяжёлых задач одновременно на пул.
    Пока задача выполняется, новые submit получают busy без постановки в очередь Waitress.
    """

    def __init__(self, *, thread_prefix: str, workers: int = 1) -> None:
        self._prefix = str(thread_prefix or "wp-heavy")
        self._workers = max(1, int(workers or 1))
        self._slot = threading.Semaphore(self._workers)
        self._pool = ThreadPoolExecutor(
            max_workers=self._workers,
            thread_name_prefix=self._prefix,
        )

    def try_run_blocking(
        self,
        fn: Callable[[], T],
        *,
        timeout_sec: float,
    ) -> tuple[str, T | None]:
        if not self._slot.acquire(blocking=False):
            return ("busy", None)
        fut = self._pool.submit(fn)
        release_in_background = False
        try:
            result = fut.result(timeout=max(1.0, float(timeout_sec)))
            return ("ok", result)
        except FuturesTimeoutError:
            release_in_background = True
            _LOG.warning(
                "%s: HTTP wait timed out after %.1fs (worker continues, slot held)",
                self._prefix,
                timeout_sec,
            )

            def _release_when_done() -> None:
                try:
                    fut.result()
                except Exception:
                    _LOG.exception("%s: background task failed after HTTP timeout", self._prefix)
                finally:
                    self._slot.release()

            threading.Thread(
                target=_release_when_done,
                name=f"{self._prefix}-release",
                daemon=True,
            ).start()
            return ("timeout", None)
        except Exception:
            _LOG.exception("%s: task failed", self._prefix)
            raise
        finally:
            if not release_in_background:
                # Без finally успешный return из try не заходил в else, и single-slot
                # пул навсегда оставался "busy" после первого удачного sync/pull.
                self._slot.release()

    def submit_async(self, fn: Callable[[], None]) -> bool:
        if not self._slot.acquire(blocking=False):
            return False

        def _wrapped() -> None:
            try:
                fn()
            except Exception:
                _LOG.exception("%s: async task failed", self._prefix)
            finally:
                self._slot.release()

        self._pool.submit(_wrapped)
        return True


def _sync_pull_timeout_sec() -> float:
    raw = (os.environ.get("WEB_PORTAL_SYNC_PULL_WORKER_TIMEOUT") or "").strip()
    if raw:
        try:
            return max(15.0, min(float(raw), 300.0))
        except ValueError:
            pass
    return 120.0


def _sync_pull_workers() -> int:
    """Три HUB могут получить pull параллельно, не копя очередь Waitress."""
    raw = (os.environ.get("WEB_PORTAL_SYNC_PULL_WORKERS") or "3").strip()
    try:
        return max(1, min(int(raw), 4))
    except ValueError:
        return 3


sync_pull_pool = _SingleSlotPool(thread_prefix="wp-sync-pull", workers=_sync_pull_workers())
folder_import_pool = _SingleSlotPool(thread_prefix="wp-folder-import", workers=1)


def run_sync_pull_blocking(fn: Callable[[], T]) -> tuple[str, T | None]:
    return sync_pull_pool.try_run_blocking(fn, timeout_sec=_sync_pull_timeout_sec())


def submit_folder_import(fn: Callable[[], None]) -> bool:
    return folder_import_pool.submit_async(fn)
