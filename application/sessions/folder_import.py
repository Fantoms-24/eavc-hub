"""Фоновый импорт папки с сеансами."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from web_portal.lib.collect_seanses_from_dir import collect_seanses_from
from web_portal.lib.db import save_seans_entries
from web_portal.lib.seans_db import connect_seans_storage

_log = logging.getLogger("web_portal.sessions")


def execute_folder_import(
    *,
    import_id: str,
    folder_path: str,
    position_name: str,
    user_id: int,
    progress_set: Callable[[str, dict[str, Any]], None],
    log_event: Callable[..., None],
) -> None:
    progress_set(
        import_id,
        {
            "user_id": user_id,
            "phase": "running",
            "message": "Обработка файлов…",
            "done": False,
            "total_files": 0,
            "total_records": 0,
            "errors": None,
        },
    )
    log_event(
        level="INFO",
        category="import",
        action="folder_import_start",
        message=f"Импорт папки: {folder_path}",
        user_id=user_id,
        path="/api/sessions/process-folder",
        method="POST",
        details={"import_id": import_id, "position": position_name},
    )
    folder = Path(folder_path)
    total_files = 0
    total_records = 0
    errors: list[str] = []
    try:
        conn = connect_seans_storage()
        try:
            for seans_list in collect_seanses_from(folder):
                if seans_list:
                    try:
                        saved = save_seans_entries(
                            conn,
                            seans_list,
                            client_name=position_name,
                            commit=False,
                        )
                        total_files += 1
                        total_records += saved
                    except Exception as e:
                        errors.append(f"Ошибка сохранения: {e}")
                        _log.error("Error saving seans: %s", e)
            conn.commit()
        finally:
            conn.close()

        if total_records > 0:
            try:
                from web_portal.app_runtime_caches import (
                    _ANALYSIS_RESP_CACHE,
                    _ANALYSIS_RESP_CACHE_LOCK,
                    _ttl_cache_clear_prefix,
                )

                _ttl_cache_clear_prefix(
                    _ANALYSIS_RESP_CACHE, _ANALYSIS_RESP_CACHE_LOCK
                )
            except Exception:
                _log.debug("execute_folder_import: suppressed error", exc_info=True)

        progress_set(
            import_id,
            {
                "phase": "done",
                "message": "Готово",
                "done": True,
                "total_files": total_files,
                "total_records": total_records,
                "errors": errors if errors else None,
                "position_name": position_name,
            },
        )
        log_event(
            level="INFO",
            category="import",
            action="folder_import_done",
            message=f"Импорт завершён: файлов {total_files}, записей {total_records}",
            user_id=user_id,
            path="/api/sessions/process-folder",
            method="POST",
            details={
                "import_id": import_id,
                "total_files": total_files,
                "total_records": total_records,
                "errors": errors[:5] if errors else None,
            },
        )
    except Exception as e:
        _log.error("folder import job failed: %s", e)
        progress_set(
            import_id,
            {
                "phase": "error",
                "message": str(e),
                "done": True,
                "error": str(e),
            },
        )
        log_event(
            level="ERROR",
            category="import",
            action="folder_import_error",
            message=str(e),
            user_id=user_id,
            path="/api/sessions/process-folder",
            method="POST",
            details={"import_id": import_id},
        )
