"""Безопасные операции с путями (UNC/сеть) с таймаутом — без бесконечного resolve/stat."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from dataclasses import dataclass
from pathlib import Path

_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="wp-safe-path")


def _timeout_sec() -> float:
    raw = (os.environ.get("WEB_PORTAL_PATH_IO_TIMEOUT_SEC") or "").strip()
    if raw:
        try:
            return max(0.5, min(float(raw), 30.0))
        except ValueError:
            pass
    return 3.0


@dataclass(frozen=True)
class PathProbeResult:
    ok: bool
    exists: bool = False
    is_dir: bool = False
    is_file: bool = False
    resolved: str = ""
    error: str = ""
    timed_out: bool = False


def _norm_parts(p: Path) -> tuple[str, ...]:
    return Path(os.path.normpath(str(p))).parts


def _is_under_base(base: Path, target: Path) -> bool:
    try:
        bp = _norm_parts(base)
        tp = _norm_parts(target)
        if len(tp) < len(bp):
            return False
        return tp[: len(bp)] == bp
    except Exception:
        return False


def _probe_path_sync(path: Path) -> PathProbeResult:
    try:
        resolved = path.resolve()
        exists = resolved.exists()
        return PathProbeResult(
            ok=True,
            exists=bool(exists),
            is_dir=bool(resolved.is_dir()) if exists else False,
            is_file=bool(resolved.is_file()) if exists else False,
            resolved=str(resolved),
        )
    except Exception as e:
        return PathProbeResult(ok=False, error=str(e))


def probe_path(path: str | Path, *, timeout_sec: float | None = None) -> PathProbeResult:
    p = Path(str(path or "").strip())
    if not str(p):
        return PathProbeResult(ok=False, error="empty path")
    limit = float(timeout_sec if timeout_sec is not None else _timeout_sec())
    fut = _POOL.submit(_probe_path_sync, p)
    try:
        return fut.result(timeout=limit)
    except FuturesTimeoutError:
        return PathProbeResult(
            ok=False,
            timed_out=True,
            error=f"таймаут доступа к пути ({limit:.1f} с)",
        )


def run_path_io(
    fn,
    *,
    timeout_sec: float | None = None,
    timeout_message: str = "таймаут доступа к пути",
):
    """Выполнить блокирующую файловую операцию в пуле с ограничением по времени."""
    limit = float(timeout_sec if timeout_sec is not None else _timeout_sec())
    fut = _POOL.submit(fn)
    try:
        return fut.result(timeout=limit), None
    except FuturesTimeoutError:
        return None, PathProbeResult(
            ok=False,
            timed_out=True,
            error=f"{timeout_message} ({limit:.1f} с)",
        )


def probe_audio_file(
    folder_path: str,
    file_rel: str,
    *,
    timeout_sec: float | None = None,
) -> PathProbeResult:
    base = Path(str(folder_path or "").strip())
    rel = str(file_rel or "").strip().replace("\\", "/")
    if not str(base) or not rel:
        return PathProbeResult(ok=False, error="folder_path и file_rel обязательны")
    if rel.startswith("/") or ".." in Path(rel).parts:
        return PathProbeResult(ok=False, error="Недопустимый file_rel")

    def _work() -> PathProbeResult:
        try:
            combined = base / rel
            if not _is_under_base(base, combined):
                return PathProbeResult(ok=False, error="Недопустимый путь")
            if not str(combined).lower().endswith(".wav"):
                return PathProbeResult(ok=False, error="Только .wav")
            exists = combined.exists()
            is_file = combined.is_file() if exists else False
            return PathProbeResult(
                ok=True,
                exists=bool(exists),
                is_file=bool(is_file),
                resolved=str(combined),
            )
        except Exception as e:
            return PathProbeResult(ok=False, error=str(e))

    limit = float(timeout_sec if timeout_sec is not None else _timeout_sec())
    fut = _POOL.submit(_work)
    try:
        return fut.result(timeout=limit)
    except FuturesTimeoutError:
        return PathProbeResult(
            ok=False,
            timed_out=True,
            error=f"таймаут доступа к файлу ({limit:.1f} с)",
        )
