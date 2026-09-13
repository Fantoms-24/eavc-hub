"""Единый контекст зависимостей для регистраторов маршрутов.

Все доменные ``register_*_routes(app, ctx)`` получают один ``AppContext``.
Фабрика ``create_app`` собирает контекст один раз и передаёт его дальше —
без разрозненных kwargs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class AppContext:
    """Зависимости HTTP-слоя, общие для доменов."""

    base_dir: Path
    sync_key: str
    sync_upstream: str

    # Job / AI runtime (замыкания из create_app)
    ai_created_by: Callable[[], str] | None = None
    create_ai_job_record: Callable[..., int] | None = None
    submit_ai_job: Callable[..., tuple[dict[str, Any], int]] | None = None
    create_export_job_record: Callable[..., int] | None = None
    submit_export_job: Callable[..., tuple[dict[str, Any], int]] | None = None
    now_ts: Callable[[], str] | None = None

    # Intercepts / sync runtime
    build_intercepts_docx_export_result: Callable[..., Any] | None = None
    bump_intercept_item_live: Callable[..., Any] | None = None
    bump_intercept_item_live_from_sync: Callable[..., Any] | None = None
    forward_intercept_payload_async: Callable[..., Any] | None = None
    intercepts_state_cache_clear: Callable[[], None] | None = None

    # Export job helpers
    can_view_export_position: Callable[[str], bool] | None = None
    resubmit_export_job_if_possible: Callable[[dict[str, object]], bool] | None = None
    build_sessions_word_export_result: Callable[..., dict[str, object]] | None = None
    build_sessions_excel_export_result: Callable[..., dict[str, object]] | None = None
    build_aviation_word_export_result: Callable[..., dict[str, object]] | None = None

    # Auth / portal events
    login_rate_limiter: Any | None = None
    log_portal_event: Callable[..., None] | None = None

    def is_sync_hub(self) -> bool:
        """HUB: есть upstream и ключ синхронизации."""
        return bool(self.sync_upstream and self.sync_key)
