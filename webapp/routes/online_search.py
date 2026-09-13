"""Маршруты поиска онлайн (/api/online-search/*), извлечены из app.py дословно."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import unquote

from flask import (
    abort,
    jsonify,
    request,
    send_file,
    send_from_directory,
    url_for,
)
from flask_login import current_user, login_required
from openpyxl import Workbook

from web_portal.application.online_search import (
    OnlineSearchUseCaseHTTP,
    assemble_online_search_battalion_spectrum_payload,
    assemble_online_search_unit_detail_payload,
    assemble_online_search_unit_parent_payload,
    assemble_online_search_units_list_payload,
    execute_online_search_import_xlsx,
)
from web_portal.app_runtime_caches import (
    online_import_progress_get as _online_import_progress_get,
    online_import_progress_set as _online_import_progress_set,
)
from web_portal.config import DEFAULT_DB_NAME, db_path, search_online_db_path
from web_portal.lib.db import (
    apply_search_note_to_unit,
    connect,
    delete_online_search_row,
    enqueue_sync_outbox,
    ensure_db,
    get_online_search_headers,
    get_online_search_meta,
    get_online_search_unit_profile,
    list_distinct_seans_frequency_groups,
    list_intercept_callsigns_for_unit_pair,
    list_online_search,
    list_online_search_ids_for_note_pair,
    list_seanses_ids_for_unit_pair,
    seanses_datetime_extremes_for_unit_pair,
    set_online_search_unit_avatar,
    sync_units_from_online_search,
    update_online_search_note,
    upsert_online_search_row,
    upsert_online_search_unit_profile,
)
from web_portal.webapp.auth import require_perm
from web_portal.webapp.context import AppContext
from web_portal.webapp.timeutils import _utc_now

_log = logging.getLogger("web_portal.webapp.routes.online_search")


def register_online_search_routes(app, ctx: AppContext):
    """Регистрирует маршруты поиска онлайн через AppContext. Код перенесён из create_app дословно."""

    @app.get("/api/online-search")
    @login_required
    def api_online_search_list():
        # Используем отдельную БД для поиска онлайн
        q = request.args.get("q", "")
        sort_by = request.args.get("sort_by", "frequency")
        sort_dir = request.args.get("sort_dir", "desc")
        limit = request.args.get("limit", 200, type=int)
        offset = request.args.get("offset", 0, type=int)

        # Собираем фильтры из параметров запроса
        filters = {}
        for key, value in request.args.items():
            if key.startswith("filter_") and value:
                filter_col = key.replace("filter_", "")
                filters[filter_col] = value

        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            data = list_online_search(
                conn,
                q=q,
                sort_by=sort_by,
                sort_dir=sort_dir,
                limit=limit,
                offset=offset,
                filters=filters if filters else None,
            )
            headers = get_online_search_headers(conn)
            meta = get_online_search_meta(conn)
            return jsonify({"ok": True, "headers": headers, "meta": meta, **data})
        finally:
            conn.close()

    @app.get("/api/online-search/units")
    @login_required
    def api_online_search_units_list():
        """Все подразделения (note) + число строк — без детализации по записям."""
        q_filter = (request.args.get("q") or "").strip()
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            payload = assemble_online_search_units_list_payload(
                conn,
                q_filter=q_filter,
                build_avatar_url=lambda fn: url_for(
                    "api_online_search_unit_avatar_file", filename=fn
                ),
            )
            return jsonify(payload)
        finally:
            conn.close()

    @app.get("/api/online-search/unit-parent")
    @login_required
    def api_online_search_unit_parent():
        pkey = (request.args.get("p") or request.args.get("parent_key") or "").strip()
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            payload = assemble_online_search_unit_parent_payload(
                conn,
                pkey,
                build_avatar_url=lambda fn: url_for(
                    "api_online_search_unit_avatar_file", filename=fn
                ),
                build_hero_url=lambda fn: url_for(
                    "api_online_search_unit_hero_file", filename=fn
                ),
            )
            return jsonify(payload)
        except OnlineSearchUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        finally:
            conn.close()

    @app.get("/api/online-search/battalion-spectrum")
    @login_required
    def api_online_search_battalion_spectrum():
        raw = request.args.get("k") or request.args.get("key") or ""
        unit_key = unquote(raw).strip()
        p = search_online_db_path()
        ensure_db(p)
        main_p = db_path(DEFAULT_DB_NAME)
        ensure_db(main_p)
        search_conn = connect(p)
        main_conn = connect(main_p)
        try:
            payload = assemble_online_search_battalion_spectrum_payload(
                search_conn,
                main_conn,
                unit_key,
                build_avatar_url=lambda fn: url_for(
                    "api_online_search_unit_avatar_file", filename=fn
                ),
                build_hero_url=lambda fn: url_for(
                    "api_online_search_unit_hero_file", filename=fn
                ),
            )
            return jsonify(payload)
        except OnlineSearchUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        finally:
            search_conn.close()
            main_conn.close()

    @app.get("/api/online-search/battalion-freq-detail")
    @login_required
    def api_online_search_battalion_freq_detail():
        rawk = request.args.get("k") or request.args.get("key") or ""
        unit_key = unquote(rawk).strip()
        freq = (request.args.get("f") or request.args.get("frequency") or "").strip()
        group_id = (request.args.get("g") or request.args.get("group_id") or "").strip()
        if not unit_key or not freq or not group_id:
            return (
                jsonify(
                    {
                        "ok": False,
                        "error": "нужны параметры k (unit), f (частота), g (группа)",
                    }
                ),
                400,
            )
        p = search_online_db_path()
        ensure_db(p)
        main_p = db_path(DEFAULT_DB_NAME)
        ensure_db(main_p)
        search_conn = connect(p)
        main_conn = connect(main_p)
        try:
            st = seanses_datetime_extremes_for_unit_pair(
                main_conn, unit_key, freq, group_id
            )
            seans_ids = list_seanses_ids_for_unit_pair(
                main_conn, unit_key, freq, group_id
            )
            os_ids = list_online_search_ids_for_note_pair(
                search_conn, unit_key, freq, group_id
            )
            callsigns = list_intercept_callsigns_for_unit_pair(
                main_conn,
                unit_note=unit_key,
                frequency=freq,
                group_id=group_id,
                limit=500,
            )
            return jsonify(
                {
                    "ok": True,
                    "unit_key": unit_key,
                    "frequency": freq,
                    "group_id": group_id,
                    "seanses_first": st.get("first"),
                    "seanses_last": st.get("last"),
                    "id_seanses": seans_ids,
                    "id_online_search": os_ids,
                    "callsigns": callsigns,
                }
            )
        finally:
            search_conn.close()
            main_conn.close()

    @app.get("/api/online-search/unit-detail")
    @login_required
    def api_online_search_unit_detail():
        raw = request.args.get("key", "")
        unit_key = unquote(raw).strip()
        p = search_online_db_path()
        ensure_db(p)
        main_p = db_path(DEFAULT_DB_NAME)
        ensure_db(main_p)
        search_conn = connect(p)
        main_conn = connect(main_p)
        try:
            payload = assemble_online_search_unit_detail_payload(
                search_conn,
                main_conn,
                unit_key,
                build_avatar_url=lambda fn: url_for(
                    "api_online_search_unit_avatar_file", filename=fn
                ),
            )
            return jsonify(payload)
        except OnlineSearchUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        finally:
            search_conn.close()
            main_conn.close()

    @app.get("/api/online-search/unit-avatar/<path:filename>")
    @login_required
    def api_online_search_unit_avatar_file(filename: str):
        if not re.match(r"^[a-fA-F0-9]{32}\.[A-Za-z0-9]{2,5}$", filename or ""):
            abort(404)
        av_dir = (ctx.base_dir / "data" / "unit_avatars").resolve()
        av_dir.mkdir(parents=True, exist_ok=True)
        path = (av_dir / filename).resolve()
        try:
            path.relative_to(av_dir)
        except Exception:
            abort(404)
        if not path.is_file():
            abort(404)
        return send_from_directory(str(av_dir), path.name)

    @app.post("/api/online-search/unit-profile")
    @login_required
    @require_perm("edit_search")
    def api_online_search_unit_profile_save():
        body = request.get_json(force=True) or {}
        key = str(body.get("unit_key") or "").strip() or "__none__"
        if len(key) > 4000:
            return jsonify({"ok": False, "error": "key слишком длинный"}), 400
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            ex = get_online_search_unit_profile(conn, key)
            new_h = (
                str(body.get("history") or "")
                if "history" in body
                else str(ex.get("history") or "")
            )
            new_hero_str: str | None
            if "hero" in body:
                hv = body.get("hero")
                if hv is None:
                    new_hero_str = None
                elif isinstance(hv, dict):
                    if str(hv.get("mode") or "default") == "default":
                        new_hero_str = None
                    else:
                        new_hero_str = json.dumps(
                            hv, ensure_ascii=False, sort_keys=True
                        )
                else:
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": "hero должен быть объектом или null",
                            }
                        ),
                        400,
                    )
            else:
                new_hero_str = ex.get("hero_json")
            upsert_online_search_unit_profile(conn, key, new_h, new_hero_str)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/online-search/unit-avatar")
    @login_required
    @require_perm("edit_search")
    def api_online_search_unit_avatar_upload():
        key = (request.form.get("unit_key") or "").strip() or "__none__"
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "файл не выбран"}), 400
        ext = Path(f.filename).suffix.lower() or ".png"
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            return jsonify({"ok": False, "error": "Нужен файл изображения"}), 400
        h = hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]
        out_name = f"{h}{ext}"
        av_dir = ctx.base_dir / "data" / "unit_avatars"
        av_dir.mkdir(parents=True, exist_ok=True)
        f.save(str(av_dir / out_name))
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            set_online_search_unit_avatar(conn, key, out_name)
        finally:
            conn.close()
        avatar_url = url_for(
            "api_online_search_unit_avatar_file", filename=out_name
        )
        return jsonify({"ok": True, "avatar_url": avatar_url})

    @app.post("/api/online-search/unit-hero-banner")
    @login_required
    @require_perm("edit_search")
    def api_online_search_unit_hero_banner_upload():
        key = (request.form.get("unit_key") or "").strip() or "__none__"
        f = request.files.get("file")
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "файл не выбран"}), 400
        ext = Path(f.filename).suffix.lower() or ".jpg"
        if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
            return jsonify({"ok": False, "error": "Нужен файл изображения"}), 400
        h = hashlib.sha256(f"{key}:hero_banner".encode("utf-8")).hexdigest()[:32]
        out_name = f"h{h}{ext}"
        hero_dir = ctx.base_dir / "data" / "unit_hero"
        hero_dir.mkdir(parents=True, exist_ok=True)
        f.save(str(hero_dir / out_name))
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            ex = get_online_search_unit_profile(conn, key)
            try:
                cur_hero = json.loads(ex.get("hero_json") or "{}")
            except json.JSONDecodeError:
                cur_hero = {}
            if not isinstance(cur_hero, dict):
                cur_hero = {}
            cur_hero["mode"] = "banner"
            cur_hero["banner"] = out_name
            upsert_online_search_unit_profile(
                conn, key, str(ex.get("history") or ""), json.dumps(
                    cur_hero, ensure_ascii=False, sort_keys=True
                )
            )
        finally:
            conn.close()
        banner_url = url_for(
            "api_online_search_unit_hero_file", filename=out_name
        )
        return jsonify(
            {"ok": True, "banner_url": banner_url, "banner": out_name}
        )

    @app.get("/api/online-search/unit-hero/<path:filename>")
    @login_required
    def api_online_search_unit_hero_file(filename: str):
        if not re.match(
            r"^h[a-fA-F0-9]{32}\.[A-Za-z0-9]{2,5}$", str(filename), re.I
        ):
            abort(404)
        hero_dir = ctx.base_dir / "data" / "unit_hero"
        path = hero_dir / filename
        try:
            path = path.resolve()
            if not str(path).startswith(str(hero_dir.resolve())):
                abort(404)
        except Exception:
            abort(404)
        if not path.is_file():
            abort(404)
        return send_from_directory(str(hero_dir), path.name)

    @app.get("/api/online-search/import-progress")
    @login_required
    def api_online_search_import_progress():
        import_id = str(request.args.get("import_id") or "").strip()
        if not import_id:
            return jsonify({"ok": False, "error": "import_id обязателен"}), 400
        progress = _online_import_progress_get(import_id)
        if not progress:
            return jsonify(
                {
                    "ok": True,
                    "progress": {
                        "phase": "idle",
                        "percent": 0,
                        "processed_rows": 0,
                        "total_rows": 0,
                        "done": False,
                    },
                }
            )
        owner_id = int(progress.get("user_id") or 0)
        if owner_id and owner_id != int(current_user.id):
            return (
                jsonify({"ok": False, "error": "Нет доступа к прогрессу импорта"}),
                403,
            )
        progress.pop("user_id", None)
        progress.pop("updated_ts", None)
        return jsonify({"ok": True, "progress": progress})

    @app.post("/api/online-search")
    @require_perm("edit_search")
    def api_online_search_upsert():
        # Используем отдельную БД для поиска онлайн
        data = request.get_json(silent=True) or {}
        row = data.get("row") or {}
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            rid = upsert_online_search_row(conn, row)
            # Применяем note → unit в основной БД (main.sqlite)
            freq = str(row.get("frequency") or row.get("col1") or "")
            gid = str(row.get("group_id") or row.get("col2") or "")
            note = str(row.get("note") or row.get("col9") or "")
            unit_sync = None
            if freq and gid:
                # Подключаемся к основной БД для обновления unit
                main_conn = connect(db_path(DEFAULT_DB_NAME))
                try:
                    unit_sync = apply_search_note_to_unit(main_conn, freq, gid, note)
                    # синхронизация для актуальных пар из seanses за последнюю неделю
                    one_week_ago = (_utc_now().replace(tzinfo=None) - timedelta(days=7)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    )
                    frequency_groups = list_distinct_seans_frequency_groups(
                        main_conn,
                        since_dt=one_week_ago,
                    )
                    sync_units_from_online_search(main_conn, conn, frequency_groups)
                finally:
                    main_conn.close()
            return jsonify({"ok": True, "id": rid, "unit_sync": unit_sync})
        finally:
            conn.close()

    @app.post("/api/online-search/delete")
    @require_perm("edit_search")
    def api_online_search_delete():
        # Используем отдельную БД для поиска онлайн
        data = request.get_json(silent=True) or {}
        row_id = int(data.get("id") or 0)
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            delete_online_search_row(conn, row_id)
            # HUB: отправляем tombstone на сервер (батч-синк по updated_at не увидит удаление)
            if ctx.sync_upstream and ctx.sync_key and row_id:
                try:
                    # Используем основную БД для синхронизации
                    main_conn = connect(db_path(DEFAULT_DB_NAME))
                    try:
                        enqueue_sync_outbox(
                            main_conn,
                            kind="online_search:delete",
                            payload={"id": int(row_id)},
                        )
                    finally:
                        main_conn.close()
                except Exception:
                    _log.debug("api_online_search_delete: suppressed error", exc_info=True)
            return jsonify({"ok": True})
        finally:
            conn.close()

    @app.post("/api/online-search/mark-all-read")
    @login_required
    def api_online_search_mark_all_read():
        """Отметить все записи как прочитанные (убрать тег 'новое')."""
        # Используем отдельную БД для поиска онлайн
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            from datetime import datetime, timedelta

            # Обновляем updated_at всех записей на дату старше 24 часов, чтобы они не считались новыми
            old_date = (_utc_now().replace(tzinfo=None) - timedelta(hours=25)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            cur = conn.cursor()
            cur.execute(
                "UPDATE online_search SET updated_at = ? WHERE updated_at > ?",
                (
                    old_date,
                    (_utc_now().replace(tzinfo=None) - timedelta(hours=24)).strftime(
                        "%Y-%m-%d %H:%M:%S"
                    ),
                ),
            )
            count = cur.rowcount
            conn.commit()
            return jsonify({"ok": True, "marked": count})
        finally:
            conn.close()

    @app.post("/api/online-search/note")
    @require_perm("edit_search")
    def api_online_search_update_note():
        # Используем отдельную БД для поиска онлайн
        data = request.get_json(silent=True) or {}
        row_id = int(data.get("id") or 0)
        note = str(data.get("note") or "")
        if not row_id:
            return jsonify({"ok": False, "error": "id обязателен"}), 400
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        try:
            row_info = update_online_search_note(conn, row_id, note)
            # Применяем note → unit в основной БД (main.sqlite)
            main_conn = connect(db_path(DEFAULT_DB_NAME))
            try:
                unit_sync = apply_search_note_to_unit(
                    main_conn,
                    row_info.get("frequency", ""),
                    row_info.get("group_id", ""),
                    row_info.get("note", ""),
                )
            finally:
                main_conn.close()
            return jsonify({"ok": True, "id": row_id, "unit_sync": unit_sync})
        finally:
            conn.close()

    @app.post("/api/online-search/import-xlsx")
    @require_perm("edit_search")
    def api_online_search_import_xlsx():
        apply_to_unit = request.form.get("apply_to_unit", "1") == "1"
        import_id = str(request.form.get("import_id") or "").strip()
        if not import_id:
            import_id = f"imp-{int(time.time() * 1000)}-{int(current_user.id)}"
        f = request.files.get("file")
        if not f:
            return jsonify({"ok": False, "error": "Файл не передан"}), 400

        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            f.save(str(tmp_path))
            payload = execute_online_search_import_xlsx(
                conn,
                xlsx_path=tmp_path,
                apply_to_unit=apply_to_unit,
                import_id=import_id,
                user_id=int(current_user.id),
                is_sync_hub=ctx.is_sync_hub(),
                progress_set=_online_import_progress_set,
            )
            return jsonify(payload)
        except OnlineSearchUseCaseHTTP as e:
            return jsonify(e.payload), e.status_code
        finally:
            conn.close()
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                _log.debug("api_online_search_import_xlsx: suppressed error", exc_info=True)

    @app.post("/api/online-search/sync-units")
    @require_perm("edit_search")
    def api_online_search_sync_units():
        # Полная синхронизация unit из online_search
        search_p = search_online_db_path()
        ensure_db(search_p)
        search_conn = connect(search_p)
        main_conn = connect(db_path(DEFAULT_DB_NAME))
        try:
            # синхронизируем только пары frequency/group_ из seanses за последнюю неделю
            one_week_ago = (_utc_now().replace(tzinfo=None) - timedelta(days=7)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            frequency_groups = list_distinct_seans_frequency_groups(
                main_conn,
                since_dt=one_week_ago,
            )
            if not frequency_groups:
                return (
                    jsonify(
                        {
                            "ok": False,
                            "error": "Не найдено пар частота/группа в хранилище сеансов за последнюю неделю. "
                            "Проверьте seans.sqlite и не удаляйте привязки unit вручную.",
                        }
                    ),
                    400,
                )
            # удаляем старые привязки unit, которых нет в seanses за неделю
            keep_set = {(f, g) for (f, g) in frequency_groups}
            existing_units = main_conn.execute(
                "SELECT frequency, group_ FROM unit"
            ).fetchall()
            for r in existing_units:
                f = str(r[0] or "")
                g = str(r[1] or "")
                if (f, g) not in keep_set:
                    main_conn.execute(
                        "DELETE FROM unit WHERE frequency=? AND group_=?",
                        (f, g),
                    )
            # очищаем привязки по активным парам, чтобы остались только из online_search
            for f, g in keep_set:
                main_conn.execute(
                    "DELETE FROM unit WHERE frequency=? AND group_=?",
                    (f, g),
                )
            main_conn.commit()
            stats = sync_units_from_online_search(
                main_conn, search_conn, frequency_groups
            )
            return jsonify({"ok": True, "stats": stats})
        finally:
            search_conn.close()
            main_conn.close()

    @app.get("/api/online-search/export-xlsx")
    @login_required
    def api_online_search_export_xlsx():
        # Используем отдельную БД для поиска онлайн
        q = request.args.get("q", "")
        p = search_online_db_path()
        ensure_db(p)
        conn = connect(p)
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        try:
            data = list_online_search(conn, q=q, limit=50000, offset=0)
            headers = get_online_search_headers(conn)
            wb = Workbook()
            ws = wb.active
            ws.append([h or f"col{i+1}" for i, h in enumerate(headers)])
            for r in data["rows"]:
                ws.append([r.get(f"col{i}") for i in range(1, 10)])
            wb.save(str(tmp_path))
            wb.close()
            safe_ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"poisk_online_{safe_ts}.xlsx"
            return send_file(
                str(tmp_path),
                as_attachment=True,
                download_name=filename,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        finally:
            conn.close()
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                _log.debug("api_online_search_export_xlsx: suppressed error", exc_info=True)
