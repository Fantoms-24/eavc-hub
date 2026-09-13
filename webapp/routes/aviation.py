"""Маршруты авиации (/aviation, /api/aviation/*), извлечены из app.py дословно.

Маршрут /api/aviation/export-word-job остаётся в app.py: он использует общую
export-job машинерию create_app (_submit_export_job и др.).
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime

from flask import jsonify, render_template, request
from flask_login import login_required

from web_portal.app_perf import perf_route as _perf_route
from web_portal.config import DEFAULT_DB_NAME, db_path
from web_portal.lib.aviation_db import (
    add_callsign_history_entry,
    create_aviation_callsign,
    create_aviation_frequency,
    create_or_update_aviation_intercept,
    delete_aviation_callsign,
    delete_aviation_frequency,
    ensure_callsign_exit_for_date,
    get_aviation_callsign_by_label,
    get_aviation_callsigns,
    get_aviation_frequencies,
    get_aviation_intercept_for_api,
    get_aviation_stats,
    get_callsign_history,
    get_callsign_stats_by_days,
    get_intercept_content_by_date,
    normalize_aviation_work_date,
    parse_aviation_content_for_callsigns,
    update_aviation_frequency,
    upsert_aviation_daily_intercept,
)
from web_portal.lib.aviation_db_sync import (
    get_aviation_callsign_sync_payload,
    get_aviation_frequency_sync_payload,
    get_aviation_intercept_sync_payload,
)
from web_portal.lib.db import connect, enqueue_sync_outbox, ensure_db
from web_portal.webapp.auth import require_tab
from web_portal.webapp.context import AppContext

_log = logging.getLogger("web_portal.webapp.routes.aviation")


def register_aviation_routes(app, ctx: AppContext):
    """Регистрирует маршруты авиации через AppContext. Код перенесён из create_app дословно."""

    @app.get("/aviation")
    @login_required
    @require_tab("tab_aviation")
    def aviation():
        return render_template("aviation.html")

    @app.get("/api/aviation/frequencies")
    @login_required
    def api_aviation_frequencies():
        date = request.args.get("date") or None
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            frequencies = get_aviation_frequencies(conn, date=date)
            return jsonify({"ok": True, "frequencies": frequencies})
        finally:
            conn.close()

    @app.post("/api/aviation/frequency/create")
    @login_required
    def api_aviation_frequency_create():
        data = request.get_json(silent=True) or {}
        frequency = str(data.get("frequency") or "").replace(",", ".").strip()
        aviation_type = data.get("aviation_type") or "Армейская авиация"

        if not frequency:
            return jsonify({"ok": False, "error": "Частота обязательна"}), 400

        if aviation_type not in ["Армейская авиация", "Тактическая авиация", "н/у", "ЯК", "F-16"]:
            return jsonify({"ok": False, "error": "Неверный тип авиации"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            freq_id = create_aviation_frequency(
                conn, frequency=frequency, aviation_type=aviation_type
            )
            # Синхронизация
            if ctx.is_sync_hub():
                try:
                    payload = get_aviation_frequency_sync_payload(
                        conn, frequency_id=freq_id
                    )
                    enqueue_sync_outbox(
                        conn, kind="aviation:frequency", payload=payload
                    )
                    # Почти realtime: сразу отправить outbox на сервер
                    try:
                        from web_portal.lib.sync_agent import (
                            sync_push_once,
                        )  # noqa: E402

                        def _push_bg():
                            try:
                                sync_push_once(
                                    upstream_base=app.config.get("SYNC_UPSTREAM") or "",
                                    sync_key=app.config.get("SYNC_KEY") or "",
                                )
                            except Exception:
                                _log.debug("_push_bg: suppressed error", exc_info=True)

                        threading.Thread(target=_push_bg, daemon=True).start()
                    except Exception:
                        _log.debug("api_aviation_frequency_create: suppressed error", exc_info=True)
                except Exception:
                    _log.debug("api_aviation_frequency_create: suppressed error", exc_info=True)
            return jsonify({"ok": True, "frequency_id": freq_id})
        finally:
            conn.close()

    @app.post("/api/aviation/frequency/update")
    @login_required
    def api_aviation_frequency_update():
        data = request.get_json(silent=True) or {}
        frequency_id = int(data.get("frequency_id") or 0)
        aviation_type = (data.get("aviation_type") or "").strip()

        if not frequency_id:
            return jsonify({"ok": False, "error": "frequency_id обязателен"}), 400
        if aviation_type not in ["Армейская авиация", "Тактическая авиация", "н/у", "ЯК", "F-16"]:
            return jsonify({"ok": False, "error": "Неверный тип авиации"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            updated = update_aviation_frequency(
                conn, frequency_id=frequency_id, aviation_type=aviation_type
            )
            if not updated:
                return jsonify({"ok": False, "error": "Частота не найдена"}), 404
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/aviation/frequency/delete")
    @login_required
    def api_aviation_frequency_delete():
        data = request.get_json(silent=True) or {}
        frequency_id = int(data.get("frequency_id") or 0)

        if not frequency_id:
            return jsonify({"ok": False, "error": "frequency_id обязателен"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            # для синка: забираем UUID до удаления
            row = None
            try:
                row = conn.execute(
                    """
                    SELECT uuid, frequency, aviation_type
                    FROM aviation_frequencies
                    WHERE id=?
                    """,
                    (frequency_id,),
                ).fetchone()
            except Exception:
                row = None
            if not row:
                return jsonify({"ok": False, "error": "Частота не найдена"}), 404

            deleted = delete_aviation_frequency(conn, frequency_id=frequency_id)
            if not deleted:
                return jsonify({"ok": False, "error": "Частота не найдена"}), 404

            # sync: отправляем событие удаления
            if ctx.is_sync_hub():
                try:
                    payload = {
                        "uuid": str(row["uuid"] or "").strip(),
                        "frequency": str(row["frequency"] or ""),
                        "aviation_type": str(row["aviation_type"] or ""),
                    }
                    enqueue_sync_outbox(
                        conn, kind="aviation:frequency_delete", payload=payload
                    )
                    # "почти realtime": сразу отправить outbox на сервер
                    try:
                        from web_portal.lib.sync_agent import (
                            sync_push_once,
                        )  # noqa: E402

                        def _push_bg():
                            try:
                                sync_push_once(
                                    upstream_base=app.config.get("SYNC_UPSTREAM") or "",
                                    sync_key=app.config.get("SYNC_KEY") or "",
                                )
                            except Exception:
                                _log.debug("_push_bg: suppressed error", exc_info=True)

                        threading.Thread(target=_push_bg, daemon=True).start()
                    except Exception:
                        _log.debug("api_aviation_frequency_delete: suppressed error", exc_info=True)
                except Exception:
                    _log.debug("api_aviation_frequency_delete: suppressed error", exc_info=True)

            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/aviation/reset")
    @login_required
    def api_aviation_reset():
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            rows = []
            try:
                rows = conn.execute(
                    """
                    SELECT id, uuid, frequency, aviation_type
                    FROM aviation_frequencies
                    ORDER BY id
                    """
                ).fetchall()
            except Exception:
                rows = []

            deleted = 0
            for row in rows:
                frequency_id = int(row["id"] or 0)
                if not frequency_id:
                    continue
                ok = delete_aviation_frequency(conn, frequency_id=frequency_id)
                if not ok:
                    continue
                deleted += 1
                if ctx.is_sync_hub():
                    try:
                        payload = {
                            "uuid": str(row["uuid"] or "").strip(),
                            "frequency": str(row["frequency"] or ""),
                            "aviation_type": str(row["aviation_type"] or ""),
                        }
                        enqueue_sync_outbox(
                            conn, kind="aviation:frequency_delete", payload=payload
                        )
                    except Exception:
                        _log.debug("api_aviation_reset: suppressed error", exc_info=True)

            if deleted and ctx.is_sync_hub():
                try:
                    from web_portal.lib.sync_agent import sync_push_once  # noqa: E402

                    def _push_bg():
                        try:
                            sync_push_once(
                                upstream_base=app.config.get("SYNC_UPSTREAM") or "",
                                sync_key=app.config.get("SYNC_KEY") or "",
                            )
                        except Exception:
                            _log.debug("_push_bg: suppressed error", exc_info=True)

                    threading.Thread(target=_push_bg, daemon=True).start()
                except Exception:
                    _log.debug("api_aviation_reset: suppressed error", exc_info=True)

            return jsonify({"ok": True, "deleted": deleted})
        finally:
            conn.close()

    @app.get("/api/aviation/intercept")
    @login_required
    def api_aviation_intercept():
        frequency_id = request.args.get("frequency_id", 0, type=int)
        date = request.args.get("date") or None
        if not frequency_id:
            return jsonify({"ok": False, "error": "frequency_id обязателен"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            bundle = get_aviation_intercept_for_api(
                conn, frequency_id=frequency_id, work_date=date
            )
            if not bundle:
                return jsonify({"ok": True, "intercept": None})
            return jsonify({"ok": True, "intercept": bundle})
        finally:
            conn.close()

    @app.post("/api/aviation/intercept/update")
    @login_required
    def api_aviation_intercept_update():
        data = request.get_json(silent=True) or {}
        frequency_id = int(data.get("frequency_id") or 0)
        content = data.get("content") or ""

        if not frequency_id:
            return jsonify({"ok": False, "error": "frequency_id обязателен"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            work_date = str(data.get("work_date") or "").strip()
            wd = normalize_aviation_work_date(work_date)
            if wd:
                intercept_id = upsert_aviation_daily_intercept(
                    conn, frequency_id=frequency_id, work_date=wd, content=content
                )
            else:
                intercept_id = create_or_update_aviation_intercept(
                    conn, frequency_id=frequency_id, content=content
                )
            # Синхронизация (как прежде — только общий бланк aviation_intercepts)
            if ctx.is_sync_hub() and not wd:
                try:
                    payload = get_aviation_intercept_sync_payload(
                        conn, intercept_id=intercept_id
                    )
                    enqueue_sync_outbox(
                        conn, kind="aviation:intercept", payload=payload
                    )
                    # Почти realtime: сразу отправить outbox на сервер
                    try:
                        from web_portal.lib.sync_agent import (
                            sync_push_once,
                        )  # noqa: E402

                        def _push_bg():
                            try:
                                sync_push_once(
                                    upstream_base=app.config.get("SYNC_UPSTREAM") or "",
                                    sync_key=app.config.get("SYNC_KEY") or "",
                                )
                            except Exception:
                                _log.debug("_push_bg: suppressed error", exc_info=True)

                        threading.Thread(target=_push_bg, daemon=True).start()
                    except Exception:
                        _log.debug("api_aviation_intercept_update: suppressed error", exc_info=True)
                except Exception:
                    _log.debug("api_aviation_intercept_update: suppressed error", exc_info=True)
            return jsonify({"ok": True, "intercept_id": intercept_id})
        finally:
            conn.close()

    @app.get("/api/aviation/callsigns")
    @login_required
    def api_aviation_callsigns():
        # Без frequency_id или frequency_id=0 — общий список всех позывных; иначе — по частоте
        raw = request.args.get("frequency_id")
        try:
            frequency_id = int(raw) if raw is not None and str(raw).strip() else None
        except (TypeError, ValueError):
            frequency_id = None
        if frequency_id == 0:
            frequency_id = None

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            callsigns = get_aviation_callsigns(conn, frequency_id=frequency_id)
            return jsonify({"ok": True, "callsigns": callsigns})
        finally:
            conn.close()

    @app.post("/api/aviation/callsign/create")
    @login_required
    def api_aviation_callsign_create():
        data = request.get_json(silent=True) or {}
        frequency_id = int(data.get("frequency_id") or 0) or None
        label = (data.get("label") or "").strip()
        card_type = data.get("card_type") or "НПУ"
        work_date = (data.get("work_date") or data.get("date") or "").strip() or None

        if not label:
            return jsonify({"ok": False, "error": "Позывной обязателен"}), 400

        if card_type not in ["НПУ", "Борт"]:
            return jsonify({"ok": False, "error": "Неверный тип карточки"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            existing = get_aviation_callsign_by_label(
                conn, label=label, frequency_id=frequency_id
            )
            if existing:
                callsign_id = existing["id"]
            else:
                callsign_id = create_aviation_callsign(
                    conn,
                    frequency_id=frequency_id,
                    label=label,
                    card_type=card_type,
                )
            # Вариант А: добавление позывного к частоте = один выход на эту дату
            if work_date and frequency_id:
                ensure_callsign_exit_for_date(
                    conn,
                    callsign_id=callsign_id,
                    frequency_id=frequency_id,
                    date_str=work_date,
                )
            # Синхронизация (только при создании новой записи)
            if ctx.is_sync_hub() and not existing:
                try:
                    payload = get_aviation_callsign_sync_payload(
                        conn, callsign_id=callsign_id
                    )
                    enqueue_sync_outbox(conn, kind="aviation:callsign", payload=payload)
                    # Почти realtime: сразу отправить outbox на сервер
                    try:
                        from web_portal.lib.sync_agent import (
                            sync_push_once,
                        )  # noqa: E402

                        def _push_bg():
                            try:
                                sync_push_once(
                                    upstream_base=app.config.get("SYNC_UPSTREAM") or "",
                                    sync_key=app.config.get("SYNC_KEY") or "",
                                )
                            except Exception:
                                _log.debug("_push_bg: suppressed error", exc_info=True)

                        threading.Thread(target=_push_bg, daemon=True).start()
                    except Exception:
                        _log.debug("api_aviation_callsign_create: suppressed error", exc_info=True)
                except Exception:
                    _log.debug("api_aviation_callsign_create: suppressed error", exc_info=True)
            return jsonify({"ok": True, "callsign_id": callsign_id})
        finally:
            conn.close()

    @app.post("/api/aviation/callsign/delete")
    @login_required
    def api_aviation_callsign_delete():
        data = request.get_json(silent=True) or {}
        label = (data.get("label") or "").strip()
        frequency_id = int(data.get("frequency_id") or 0) or None

        if not label:
            return jsonify({"ok": False, "error": "label обязателен"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            # для синка: забираем UUID до удаления
            rows = []
            try:
                if frequency_id:
                    rows = conn.execute(
                        """
                        SELECT uuid, label, frequency_id
                        FROM aviation_callsigns
                        WHERE label=? AND frequency_id=?
                        """,
                        (label, frequency_id),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT uuid, label, frequency_id
                        FROM aviation_callsigns
                        WHERE label=?
                        """,
                        (label,),
                    ).fetchall()
            except Exception:
                rows = []

            if not rows:
                return jsonify({"ok": False, "error": "Позывной не найден"}), 404

            deleted = delete_aviation_callsign(
                conn, label=label, frequency_id=frequency_id
            )
            if not deleted:
                return jsonify({"ok": False, "error": "Позывной не найден"}), 404

            # sync: отправляем события удаления для всех найденных позывных
            if ctx.is_sync_hub():
                try:
                    for row in rows:
                        # Получаем frequency_uuid
                        freq_uuid = None
                        if row["frequency_id"]:
                            freq_row = conn.execute(
                                "SELECT uuid FROM aviation_frequencies WHERE id=?",
                                (row["frequency_id"],),
                            ).fetchone()
                            if freq_row:
                                freq_uuid = str(freq_row["uuid"] or "")

                        payload = {
                            "uuid": str(row["uuid"] or "").strip(),
                            "label": str(row["label"] or ""),
                            "frequency_uuid": freq_uuid,
                        }
                        enqueue_sync_outbox(
                            conn, kind="aviation:callsign_delete", payload=payload
                        )
                    # "почти realtime": сразу отправить outbox на сервер
                    try:
                        from web_portal.lib.sync_agent import (
                            sync_push_once,
                        )  # noqa: E402

                        def _push_bg():
                            try:
                                sync_push_once(
                                    upstream_base=app.config.get("SYNC_UPSTREAM") or "",
                                    sync_key=app.config.get("SYNC_KEY") or "",
                                )
                            except Exception:
                                _log.debug("_push_bg: suppressed error", exc_info=True)

                        threading.Thread(target=_push_bg, daemon=True).start()
                    except Exception:
                        _log.debug("api_aviation_callsign_delete: suppressed error", exc_info=True)
                except Exception:
                    _log.debug("api_aviation_callsign_delete: suppressed error", exc_info=True)

            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.get("/api/aviation/callsign/history")
    @login_required
    def api_aviation_callsign_history():
        label = (request.args.get("label") or "").strip()
        frequency_id = request.args.get("frequency_id", 0, type=int) or None

        if not label:
            return jsonify({"ok": False, "error": "label обязателен"}), 400

        date = request.args.get("date") or None

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            history = get_callsign_history(
                conn, label=label, frequency_id=frequency_id, date=date
            )
            return jsonify({"ok": True, "history": history})
        finally:
            conn.close()

    @app.post("/api/aviation/parse-content")
    @login_required
    def api_aviation_parse_content():
        data = request.get_json(silent=True) or {}
        frequency_id = int(data.get("frequency_id") or 0)
        content = data.get("content") or ""

        if not frequency_id:
            return jsonify({"ok": False, "error": "frequency_id обязателен"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            # Получаем все позывные для этой частоты
            all_callsigns = get_aviation_callsigns(conn, frequency_id=frequency_id)

            # Парсим контент и находим позывные по их названиям
            callsigns_found = parse_aviation_content_for_callsigns(
                content, known_callsigns=all_callsigns
            )

            # Обновляем историю для найденных позывных
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            enqueued_callsign_sync = False

            for item in callsigns_found:
                label = item.get("label", "").strip()
                if label:
                    before = get_aviation_callsign_by_label(
                        conn, label=label, frequency_id=frequency_id
                    )
                    add_callsign_history_entry(
                        conn,
                        label=label,
                        frequency_id=frequency_id,
                        timestamp=item.get("time") or now,
                        content_snippet=item.get("snippet"),
                    )
                    if ctx.is_sync_hub() and not before:
                        try:
                            created = get_aviation_callsign_by_label(
                                conn, label=label, frequency_id=frequency_id
                            )
                            if created and created.get("id"):
                                payload = get_aviation_callsign_sync_payload(
                                    conn, callsign_id=int(created["id"])
                                )
                                enqueue_sync_outbox(
                                    conn, kind="aviation:callsign", payload=payload
                                )
                                enqueued_callsign_sync = True
                        except Exception:
                            _log.debug("api_aviation_parse_content: suppressed error", exc_info=True)

            if enqueued_callsign_sync:
                try:
                    from web_portal.lib.sync_agent import (
                        sync_push_once,
                    )  # noqa: E402

                    def _push_bg():
                        try:
                            sync_push_once(
                                upstream_base=app.config.get("SYNC_UPSTREAM") or "",
                                sync_key=app.config.get("SYNC_KEY") or "",
                            )
                        except Exception:
                            _log.debug("_push_bg: suppressed error", exc_info=True)

                    threading.Thread(target=_push_bg, daemon=True).start()
                except Exception:
                    _log.debug("api_aviation_parse_content: suppressed error", exc_info=True)

            return jsonify({"ok": True, "found": len(callsigns_found)})
        finally:
            conn.close()

    @app.get("/api/aviation/export-word")
    @_perf_route("api/aviation/export-word")
    @login_required
    def api_aviation_export_word():
        """Deprecated: используйте POST /api/aviation/export-word-job."""
        return (
            jsonify(
                {
                    "ok": False,
                    "error": "Экспорт переведён в фон. Используйте /api/aviation/export-word-job",
                    "use_job": True,
                }
            ),
            410,
        )


    @app.get("/api/aviation/stats")
    @login_required
    def api_aviation_stats():
        aviation_type = request.args.get("aviation_type") or None
        date = request.args.get("date") or None

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            stats = get_aviation_stats(conn, aviation_type=aviation_type, date=date)
            return jsonify({"ok": True, "stats": stats})
        finally:
            conn.close()

    @app.get("/api/aviation/callsign/stats")
    @login_required
    def api_aviation_callsign_stats():
        label = (request.args.get("label") or "").strip()
        frequency_id = request.args.get("frequency_id", 0, type=int) or None

        if not label:
            return jsonify({"ok": False, "error": "label обязателен"}), 400

        date = request.args.get("date") or None

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            stats = get_callsign_stats_by_days(
                conn, label=label, frequency_id=frequency_id, date=date
            )
            return jsonify({"ok": True, "stats": stats})
        finally:
            conn.close()

    @app.get("/api/aviation/intercept/by-date")
    @login_required
    def api_aviation_intercept_by_date():
        frequency_id = request.args.get("frequency_id", 0, type=int)
        date = request.args.get("date") or ""
        if not frequency_id or not date:
            return (
                jsonify({"ok": False, "error": "frequency_id и date обязательны"}),
                400,
            )

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            content = get_intercept_content_by_date(
                conn, frequency_id=frequency_id, date=date
            )
            return jsonify({"ok": True, "content": content or ""})
        finally:
            conn.close()
