from __future__ import annotations

import logging
import queue
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from web_portal.lib.asr.registry import get_asr_dir

_LOG = logging.getLogger("web_portal.asr.runtime")

DEFAULT_WHISPER_MODEL = "small"


def get_whisper_download_dir() -> Path:
    out = get_asr_dir() / "whisper_weights"
    out.mkdir(parents=True, exist_ok=True)
    return out


def resolve_whisper_short_name(model_name: str) -> str:
    raw = str(model_name or DEFAULT_WHISPER_MODEL).strip().lower()
    if not raw:
        return DEFAULT_WHISPER_MODEL
    if "/" in raw:
        raw = raw.rsplit("/", 1)[-1]
    if raw.startswith("whisper-"):
        raw = raw[len("whisper-") :]
    allowed = {"tiny", "base", "small", "medium", "large", "large-v2", "large-v3"}
    return raw if raw in allowed else DEFAULT_WHISPER_MODEL


def has_internet(timeout_sec: float = 4.0) -> bool:
    for url in (
        "https://huggingface.co",
        "https://openaipublic.azureedge.net",
    ):
        try:
            with urllib.request.urlopen(url, timeout=timeout_sec) as resp:
                if int(getattr(resp, "status", 200) or 200) < 500:
                    return True
        except Exception:
            continue
    return False


def _ready_marker(model_short: str) -> Path:
    return get_whisper_download_dir() / f".ready_{model_short}"


def is_model_ready(model_name: str) -> bool:
    short = resolve_whisper_short_name(model_name)
    return _ready_marker(short).is_file()


@dataclass
class _AsrTask:
    fn: Callable[[], Any]
    done: threading.Event
    result: Any = None
    error: BaseException | None = None
    wait: bool = True


class AsrRuntime:
    """Один фоновый поток для Whisper — не блокирует Flask и не грузит CPU параллельными инференсами."""

    def __init__(self) -> None:
        self._queue: queue.Queue[_AsrTask | None] = queue.Queue(maxsize=32)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._model_short: str | None = None
        self._model: Any = None
        self.bootstrap: dict[str, Any] = {
            "state": "idle",
            "model": DEFAULT_WHISPER_MODEL,
            "ready": False,
            "message": "",
            "internet": None,
        }

    def ensure_started(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(
                target=self._worker_loop,
                name="wp-asr-worker",
                daemon=True,
            )
            self._thread.start()

    def submit_async(self, fn: Callable[[], Any]) -> None:
        self.ensure_started()
        self._queue.put(_AsrTask(fn=fn, done=threading.Event(), wait=False))

    def run(self, fn: Callable[[], Any], *, timeout_sec: float = 1800.0) -> Any:
        self.ensure_started()
        done = threading.Event()
        task = _AsrTask(fn=fn, done=done, wait=True)
        self._queue.put(task)
        if not done.wait(timeout=max(5.0, float(timeout_sec))):
            raise TimeoutError("ASR: превышено время ожидания")
        if task.error is not None:
            raise task.error
        return task.result

    def schedule_bootstrap(self, model_name: str | None = None) -> None:
        short = resolve_whisper_short_name(model_name or DEFAULT_WHISPER_MODEL)

        def _bootstrap() -> None:
            self.bootstrap.update(
                model=short,
                state="checking",
                message="Проверка сети…",
                ready=is_model_ready(short),
            )
            if self.bootstrap.get("ready"):
                self.bootstrap.update(state="ready", message="Модель уже загружена")
                return
            if not has_internet():
                self.bootstrap.update(
                    state="offline",
                    message="Нет интернета — модель загрузится при появлении сети",
                    internet=False,
                    ready=False,
                )
                return
            self.bootstrap.update(
                state="downloading",
                message=f"Загрузка Whisper {short}…",
                internet=True,
            )
            try:
                self._load_model(short, download_only=True)
                _ready_marker(short).write_text("ok", encoding="utf-8")
                self.bootstrap.update(
                    state="ready",
                    ready=True,
                    message=f"Whisper {short} готова",
                )
            except ModuleNotFoundError as exc:
                # whisper/torch не установлены — это штатная опциональная зависимость.
                # Логируем как предупреждение без пугающего stack trace.
                _LOG.warning(
                    "ASR отключён: пакет '%s' не установлен (транскрипция недоступна)",
                    exc.name or "whisper",
                )
                self.bootstrap.update(
                    state="unavailable",
                    ready=False,
                    message=f"Модуль {exc.name or 'whisper'} не установлен — транскрипция недоступна",
                )
            except Exception as exc:
                _LOG.exception("ASR bootstrap failed")
                self.bootstrap.update(
                    state="error",
                    ready=False,
                    message=str(exc) or "Ошибка загрузки модели",
                )

        self.submit_async(_bootstrap)

    def get_model(self, model_name: str) -> Any:
        short = resolve_whisper_short_name(model_name)
        if self._model is not None and self._model_short == short:
            return self._model
        return self._load_model(short)

    def _load_model(self, short: str, *, download_only: bool = False) -> Any:
        import os

        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")
        import whisper

        download_root = str(get_whisper_download_dir())
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
        model = whisper.load_model(short, device=device, download_root=download_root)
        if not download_only:
            self._model_short = short
            self._model = model
        return model

    def _worker_loop(self) -> None:
        while True:
            task = self._queue.get()
            if task is None:
                break
            try:
                task.result = task.fn()
                task.error = None
            except BaseException as exc:
                task.result = None
                task.error = exc
                if task.wait:
                    _LOG.exception("ASR task failed")
                else:
                    _LOG.warning("ASR background task failed: %s", exc)
            finally:
                task.done.set()
                self._queue.task_done()


asr_runtime = AsrRuntime()
