"""Лёгкие перф-метрики по endpoint (rolling window). Используется из create_app."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager

PERF_MAX_SAMPLES = 200
PERF_LOCK = threading.Lock()
PERF_STATS: dict[str, deque[float]] = defaultdict(
    lambda: deque(maxlen=PERF_MAX_SAMPLES)
)


@contextmanager
def perf_span(name: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        with PERF_LOCK:
            PERF_STATS[name].append(ms)


def perf_snapshot() -> dict[str, dict[str, float | int]]:
    out: dict[str, dict[str, float | int]] = {}
    with PERF_LOCK:
        for key, arr in PERF_STATS.items():
            vals = list(arr)
            if not vals:
                continue
            vals_sorted = sorted(vals)
            p95_idx = max(
                0, min(len(vals_sorted) - 1, int(len(vals_sorted) * 0.95) - 1)
            )
            out[key] = {
                "count": len(vals_sorted),
                "avg_ms": round(sum(vals_sorted) / len(vals_sorted), 2),
                "p95_ms": round(vals_sorted[p95_idx], 2),
                "max_ms": round(vals_sorted[-1], 2),
            }
    return out


def perf_route(name: str):
    def _deco(fn):
        def _wrapped(*args, **kwargs):
            with perf_span(name):
                return fn(*args, **kwargs)

        _wrapped.__name__ = fn.__name__
        return _wrapped

    return _deco
