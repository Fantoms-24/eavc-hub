from __future__ import annotations

import threading
import time

from web_portal.lib.heavy_workers import _SingleSlotPool


def test_pool_allows_configured_parallelism_without_queueing() -> None:
    pool = _SingleSlotPool(thread_prefix="test-sync-pull", workers=2)
    release = threading.Event()
    started = threading.Event()
    active = 0
    active_lock = threading.Lock()

    def job() -> None:
        nonlocal active
        with active_lock:
            active += 1
            if active == 2:
                started.set()
        release.wait(timeout=2)

    assert pool.submit_async(job) is True
    assert pool.submit_async(job) is True
    assert started.wait(timeout=1)
    # Третий запрос не ставится в скрытую очередь и не съедает поток Waitress.
    assert pool.submit_async(job) is False
    release.set()
    time.sleep(0.05)
    assert pool.submit_async(lambda: None) is True
