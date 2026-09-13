"""Маршруты фоновых задач экспорта и AI-анализа. Извлечено из app.py дословно."""

from __future__ import annotations

import logging
from pathlib import Path

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from web_portal.application.sessions import build_sessions_export_datetime_window
from web_portal.app_perf import perf_route as _perf_route, perf_span as _perf_span
from web_portal.config import DEFAULT_DB_NAME, db_path
from web_portal.lib.ai_sessions import run_sessions_ai_analysis
from web_portal.lib.aviation_db import normalize_aviation_work_date
from web_portal.lib.db import connect, ensure_db, update_ai_job
from web_portal.lib.export_jobs import (
    export_job_max_queue_sec as _export_job_max_queue_sec,
    export_job_max_runtime_sec as _export_job_max_runtime_sec,
    get_export_job as _get_export_job,
    update_export_job as _update_export_job,
)
from web_portal.positions import get_selected_position, require_position_role
from web_portal.webapp.auth import require_tab
from web_portal.webapp.context import AppContext

_log = logging.getLogger("web_portal.webapp.routes.jobs")


def register_jobs_routes(app, ctx: AppContext):
    """Регистрирует маршруты export/AI jobs. Код перенесён из create_app дословно."""

    @app.get("/api/export-jobs/<int:job_id>")
    @_perf_route("api/export-jobs/status")
    @login_required
    def api_export_job_status(job_id: int):
        import datetime as _dt

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            job = _get_export_job(conn, job_id)
            if not job:
                return jsonify({"ok": False, "error": "Задача экспорта не найдена"}), 404
            if not ctx.can_view_export_position(str(job.get("position_name") or "")):
                return jsonify({"ok": False, "error": "Нет доступа к задаче экспорта"}), 403
            ctx.resubmit_export_job_if_possible(job)
            job = _get_export_job(conn, job_id) or job
            status = str(job.get("status") or "").lower()
            if status == "pending":
                anchor_raw = str(job.get("created_at") or "").strip()
                limit_sec = _export_job_max_queue_sec()
            elif status == "running":
                anchor_raw = str(job.get("started_at") or "").strip()
                limit_sec = _export_job_max_runtime_sec()
            else:
                anchor_raw = ""
                limit_sec = 0
            if status in {"pending", "running"} and anchor_raw and limit_sec > 0:
                try:
                    started = _dt.datetime.fromisoformat(anchor_raw.replace(" ", "T"))
                    if (_dt.datetime.now() - started).total_seconds() > limit_sec:
                        hours = max(1, int(round(limit_sec / 3600)))
                        _update_export_job(
                            conn,
                            job_id,
                            status="failed",
                            error_text=(
                                f"Экспорт не завершился за допустимое время ({hours} ч). "
                                "Сузьте период или запустите повторно."
                            ),
                        )
                        job = _get_export_job(conn, job_id) or job
                except Exception:
                    _log.debug("api_export_job_status: suppressed error", exc_info=True)
            return jsonify({"ok": True, "job": job})
        finally:
            conn.close()

    @app.get("/api/export-jobs/<int:job_id>/download")
    @_perf_route("api/export-jobs/download")
    @login_required
    def api_export_job_download(job_id: int):
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            job = _get_export_job(conn, job_id)
            if not job:
                return jsonify({"ok": False, "error": "Задача экспорта не найдена"}), 404
            if not ctx.can_view_export_position(str(job.get("position_name") or "")):
                return jsonify({"ok": False, "error": "Нет доступа к задаче экспорта"}), 403
            if str(job.get("status") or "") != "completed":
                return jsonify({"ok": False, "error": "Экспорт еще не готов"}), 409
            result = job.get("result") if isinstance(job.get("result"), dict) else {}
            path = str(result.get("path") or "")
            filename = str(result.get("filename") or "export.bin")
            mimetype = str(result.get("mimetype") or "application/octet-stream")
            if not path or not Path(path).exists():
                return jsonify({"ok": False, "error": "Файл экспорта устарел"}), 404
            return send_file(path, as_attachment=True, download_name=filename, mimetype=mimetype)
        finally:
            conn.close()

    @app.post("/api/sessions/export-word-job")
    @_perf_route("api/sessions/export-word-job")
    @login_required
    def api_sessions_export_word_job():
        data = request.get_json(silent=True) or {}
        window = build_sessions_export_datetime_window(
            date_from=str(data.get("date_from") or "").strip(),
            time_from=str(data.get("time_from") or "00:00").strip(),
            date_to=str(data.get("date_to") or "").strip(),
            time_to=str(data.get("time_to") or "23:59").strip(),
        )
        date_from = window.date_from
        date_to = window.date_to
        datetime_from = window.datetime_from
        datetime_to = window.datetime_to
        pos = get_selected_position()
        position_key = "__all__" if current_user.role == "admin" and not pos else str(pos or "")
        if position_key != "__all__":
            if not position_key:
                return jsonify({"ok": False, "error": "Позиция не выбрана"}), 400
            if not require_position_role(position_key, "export"):
                return jsonify({"ok": False, "error": "Нет прав на экспорт"}), 403
        favorites_only = data.get("favorites_only")
        if favorites_only is None:
            favorites_only = True
        else:
            favorites_only = bool(favorites_only)
        unit_name = str(data.get("unit_name") or data.get("unit_filter") or "").strip()
        params = {
            "date_from": date_from,
            "date_to": date_to,
            "datetime_from": datetime_from,
            "datetime_to": datetime_to,
            "position_name": position_key,
            "user_id": int(current_user.id),
            "favorites_only": favorites_only,
            "unit_name": unit_name,
        }
        job_id = ctx.create_export_job_record(
            job_type="sessions_word",
            position_name=position_key,
            params=params,
            created_by=ctx.ai_created_by(),
        )

        def _build() -> dict[str, object]:
            return ctx.build_sessions_word_export_result(job_id, params)

        payload, status = ctx.submit_export_job(
            job_id,
            "sessions-word-export",
            _build,
        )
        return jsonify(payload), status

    @app.post("/api/sessions/export-excel-job")
    @_perf_route("api/sessions/export-excel-job")
    @login_required
    def api_sessions_export_excel_job():
        data = request.get_json(silent=True) or {}
        window = build_sessions_export_datetime_window(
            date_from=str(data.get("date_from") or "").strip(),
            time_from=str(data.get("time_from") or "00:00").strip(),
            date_to=str(data.get("date_to") or "").strip(),
            time_to=str(data.get("time_to") or "23:59").strip(),
        )
        date_from = window.date_from
        date_to = window.date_to
        datetime_from = window.datetime_from
        datetime_to = window.datetime_to
        pos = get_selected_position()
        position_key = "__all__" if current_user.role == "admin" and not pos else str(pos or "")
        if position_key != "__all__":
            if not position_key:
                return jsonify({"ok": False, "error": "Позиция не выбрана"}), 400
            if not require_position_role(position_key, "export"):
                return jsonify({"ok": False, "error": "Нет прав на экспорт"}), 403
        unit_name = str(data.get("unit_name") or data.get("unit_filter") or "").strip()
        params = {
            "date_from": date_from,
            "date_to": date_to,
            "datetime_from": datetime_from,
            "datetime_to": datetime_to,
            "position_name": position_key,
            "unit_name": unit_name,
        }
        job_id = ctx.create_export_job_record(
            job_type="sessions_excel",
            position_name=position_key,
            params=params,
            created_by=ctx.ai_created_by(),
        )

        def _build() -> dict[str, object]:
            return ctx.build_sessions_excel_export_result(job_id, params)

        payload, status = ctx.submit_export_job(
            job_id,
            "sessions-excel-export",
            _build,
        )
        return jsonify(payload), status

    @app.post("/api/aviation/export-word-job")
    @_perf_route("api/aviation/export-word-job")
    @login_required
    def api_aviation_export_word_job():
        data = request.get_json(silent=True) or {}
        try:
            frequency_id = int(data.get("frequency_id") or request.args.get("frequency_id") or 0)
        except Exception:
            return jsonify({"ok": False, "error": "frequency_id обязателен"}), 400
        if not frequency_id:
            return jsonify({"ok": False, "error": "frequency_id обязателен"}), 400
        work_day = normalize_aviation_work_date(data.get("date") or request.args.get("date"))
        pos = get_selected_position() or "__aviation__"
        params = {"frequency_id": frequency_id, "date": work_day or ""}
        job_id = ctx.create_export_job_record(
            job_type="aviation_word",
            position_name=str(pos),
            params=params,
            created_by=ctx.ai_created_by(),
        )

        def _build() -> dict[str, object]:
            return ctx.build_aviation_word_export_result(job_id, params)

        payload, status = ctx.submit_export_job(
            job_id,
            "aviation-word-export",
            _build,
        )
        return jsonify(payload), status

    @app.post("/api/sessions/ai/analyze")
    @_perf_route("api/sessions/ai/analyze")
    @login_required
    @require_tab("tab_sessions")
    def api_sessions_ai_analyze():
        """AI-анализ сеансов: пересечения ID между подразделениями и взаимодействия."""
        data = request.get_json(silent=True) or {}
        start = str(data.get("start") or "").strip()
        end = str(data.get("end") or "").strip()
        question = str(data.get("question") or "").strip()
        if not start or not end:
            return jsonify({"ok": False, "error": "Укажите начало и конец периода"}), 400

        pos = get_selected_position()
        if not pos and current_user.role == "admin":
            pos = "__all__"
        elif not pos:
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        elif not require_position_role(pos, "view"):
            return jsonify({"ok": False, "error": "Нет доступа к позиции"}), 403

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        created_by = ctx.ai_created_by()
        job_id = ctx.create_ai_job_record(
            task_type="sessions_ai_analysis",
            position_name=str(pos or ""),
            params={"start": start, "end": end, "question": question},
            created_by=created_by,
        )

        def _run() -> None:
            bg_conn = None
            try:
                bg_conn = connect(p)
                with _perf_span("ai/sessions-analyze/run"):
                    run_sessions_ai_analysis(
                        bg_conn,
                        position_name=str(pos or ""),
                        start_ts=start,
                        end_ts=end,
                        question=question,
                        created_by=created_by,
                        job_id=job_id,
                    )
            except Exception as exc:
                fail_conn = connect(p)
                try:
                    update_ai_job(fail_conn, job_id, status="failed", error_text=str(exc))
                finally:
                    fail_conn.close()
                raise
            finally:
                if bg_conn is not None:
                    bg_conn.close()

        payload, status = ctx.submit_ai_job(job_id, "ai-sessions-analyze", _run)
        return jsonify(payload), status
