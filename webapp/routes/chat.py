"""Маршруты чата (/api/chat/*), извлечены из app.py без изменений логики."""

from __future__ import annotations

import logging
import os

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from web_portal.app_perf import perf_route as _perf_route
from web_portal.config import DEFAULT_DB_NAME, db_path, portal_db_path
from web_portal.lib.ai_assistant import answer_ai_chat_message
from web_portal.lib.auth_db import (
    clear_chat_user_ai_history,
    connect_portal,
    create_chat_file,
    create_chat_message,
    ensure_ai_assistant_user,
    get_ai_chat_feedback_map,
    get_chat_file,
    get_chat_group_name,
    list_chat_channels_for_user,
    list_chat_messages,
    set_ai_agent_memory,
    set_ai_chat_message_feedback,
    user_can_access_chat_channel,
)
from web_portal.lib.db import connect, enqueue_sync_outbox
from web_portal.positions import get_selected_position, require_position_role
from web_portal.webapp.context import AppContext

_log = logging.getLogger("web_portal.webapp.routes.chat")


def register_chat_routes(app, ctx: AppContext):
    """Регистрирует маршруты чата через AppContext. Код перенесён из create_app дословно."""

    # --- Chat API ---
    @app.get("/api/chat/channels")
    @login_required
    def api_chat_channels():
        """Список каналов чата, доступных текущему пользователю."""
        conn = connect_portal(portal_db_path())
        try:
            channels = list_chat_channels_for_user(
                conn, user_role=getattr(current_user, "role", "") or ""
            )
            return jsonify({"ok": True, "channels": channels})
        finally:
            conn.close()

    @app.get("/api/chat/messages")
    @_perf_route("api/chat/messages")
    @login_required
    def api_chat_messages():
        """Получить сообщения чата."""
        group_id = request.args.get("group_id")
        since_id = request.args.get("since_id")
        limit = request.args.get("limit", 100, type=int)

        conn = connect_portal(portal_db_path())
        try:
            group_id_int = int(group_id) if group_id else None
            group_name = ""
            if group_id_int is not None:
                group_name = get_chat_group_name(conn, group_id_int)
                if not group_name or not user_can_access_chat_channel(
                    conn, group_name, getattr(current_user, "role", "") or ""
                ):
                    return jsonify({"ok": False, "error": "Нет доступа к каналу"}), 403
            since_id_int = int(since_id) if since_id else None
            messages = list_chat_messages(
                conn,
                group_id=group_id_int,
                since_id=since_id_int,
                limit=limit,
            )
            if group_name == "ai_assistant" and messages:
                mid = [int(m["id"]) for m in messages]
                fb = get_ai_chat_feedback_map(
                    conn, user_id=int(current_user.id), message_ids=mid
                )
                for m in messages:
                    r = fb.get(int(m["id"]))
                    if r is not None:
                        m["ai_feedback"] = r
            return jsonify({"ok": True, "messages": messages})
        finally:
            conn.close()

    @app.post("/api/chat/clear-history")
    @login_required
    def api_chat_clear_history():
        """Очистить историю чата в канале (для AI — только свои сообщения и ответы ассистента)."""
        data = request.get_json(silent=True) or {}
        try:
            group_id = int(data.get("group_id") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Некорректные данные"}), 400
        if not group_id:
            return jsonify({"ok": False, "error": "Укажите канал"}), 400

        conn = connect_portal(portal_db_path())
        try:
            group_name = get_chat_group_name(conn, group_id)
            if not group_name or not user_can_access_chat_channel(
                conn, group_name, getattr(current_user, "role", "") or ""
            ):
                return jsonify({"ok": False, "error": "Нет доступа к каналу"}), 403
            if group_name == "ai_assistant":
                deleted = clear_chat_user_ai_history(
                    conn,
                    group_id=group_id,
                    user_id=int(current_user.id),
                )
                set_ai_agent_memory(
                    conn,
                    user_id=int(current_user.id),
                    scope="ai_assistant",
                    memory={},
                )
            else:
                deleted = clear_chat_user_ai_history(
                    conn,
                    group_id=group_id,
                    user_id=int(current_user.id),
                )
            return jsonify({"ok": True, "deleted": deleted})
        finally:
            conn.close()

    @app.post("/api/chat/ai-feedback")
    @login_required
    def api_chat_ai_feedback():
        """Оценка ответа EAVC Manager в канале AI (полезно / не полезно)."""
        data = request.get_json(silent=True) or {}
        try:
            message_id = int(data.get("message_id") or 0)
            group_id = int(data.get("group_id") or 0)
            rating = int(data.get("rating") or 0)
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "Некорректные данные"}), 400
        comment = str(data.get("comment") or "").strip()[:2000]

        if not message_id or not group_id:
            return jsonify({"ok": False, "error": "Некорректные данные"}), 400
        if rating not in (-1, 0, 1):
            return jsonify({"ok": False, "error": "Некорректная оценка"}), 400

        conn = connect_portal(portal_db_path())
        try:
            gname = get_chat_group_name(conn, group_id)
            if not gname or not user_can_access_chat_channel(
                conn, gname, getattr(current_user, "role", "") or ""
            ):
                return jsonify({"ok": False, "error": "Нет доступа к каналу"}), 403
            if gname != "ai_assistant":
                return jsonify({"ok": False, "error": "Только для канала AI"}), 403
            try:
                set_ai_chat_message_feedback(
                    conn,
                    user_id=int(current_user.id),
                    message_id=message_id,
                    group_id=group_id,
                    rating=rating,
                    comment=comment,
                )
            except ValueError as e:
                code = str(e) or "error"
                msg = {
                    "message_not_found": "Сообщение не найдено",
                    "group_mismatch": "Несовпадение канала",
                    "not_ai_channel": "Только для канала AI",
                    "not_ai_message": "Оценка только для ответов ассистента",
                    "rating": "Некорректная оценка",
                }.get(code, "Невозможно сохранить оценку")
                return jsonify({"ok": False, "error": msg}), 400
            return jsonify({"ok": True, "rating": rating})
        finally:
            conn.close()

    @app.post("/api/chat/messages")
    @login_required
    def api_chat_send_message():
        """Отправить сообщение в чат."""
        data = request.get_json(silent=True) or {}
        group_id = data.get("group_id")
        message_text = str(data.get("message_text") or "").strip()
        file_id = data.get("file_id")

        if not message_text and not file_id:
            return (
                jsonify({"ok": False, "error": "Сообщение или файл обязательны"}),
                400,
            )

        conn = connect_portal(portal_db_path())
        try:
            group_id_int = int(group_id) if group_id else None
            group_name = ""
            if group_id_int is not None:
                group_name = get_chat_group_name(conn, group_id_int)
                if not group_name or not user_can_access_chat_channel(
                    conn, group_name, getattr(current_user, "role", "") or ""
                ):
                    return jsonify({"ok": False, "error": "Нет доступа к каналу"}), 403
            file_id_int = int(file_id) if file_id else None
            msg_id = create_chat_message(
                conn,
                group_id=group_id_int,
                user_id=int(current_user.id),
                message_text=message_text,
                file_id=file_id_int,
            )
            ai_msg_id = None
            if group_name == "ai_assistant" and message_text:
                try:
                    pos = get_selected_position()
                    if not pos and current_user.role == "admin":
                        pos = "__all__"
                    ai_answer = answer_ai_chat_message(
                        portal_conn=conn,
                        main_db_path=db_path(DEFAULT_DB_NAME),
                        group_id=group_id_int,
                        message_id=msg_id,
                        message_text=message_text,
                        position_name=str(pos or ""),
                        user_id=int(current_user.id),
                        user_role=str(getattr(current_user, "role", "") or ""),
                        created_by=str(
                            getattr(current_user, "callsign", "")
                            or getattr(current_user, "username", "")
                            or getattr(current_user, "id", "")
                            or ""
                        ),
                        can_use_position=lambda p: require_position_role(p, "view"),
                        has_permission=lambda perm: current_user.has_perm(str(perm or "")),
                    )
                except Exception as e:
                    ai_answer = f"EAVC Manager временно недоступен: {e}"
                ai_user_id = ensure_ai_assistant_user(conn)
                ai_msg_id = create_chat_message(
                    conn,
                    group_id=group_id_int,
                    user_id=ai_user_id,
                    message_text=ai_answer,
                    file_id=None,
                )

            # Синхронизация с Hub'ами
            if ctx.sync_upstream and ctx.sync_key:
                try:
                    msg = conn.execute(
                        """
                        SELECT m.uuid, m.message_text, m.file_id, m.created_at,
                               u.username, u.callsign,
                               f.uuid as file_uuid, f.original_filename
                        FROM chat_messages m
                        JOIN users u ON u.id = m.user_id
                        LEFT JOIN chat_files f ON f.id = m.file_id
                        WHERE m.id = ?
                        """,
                        (msg_id,),
                    ).fetchone()
                    if msg:
                        payload = {
                            "uuid": str(msg["uuid"] or ""),
                            "username": str(msg["username"] or ""),
                            "callsign": str(msg["callsign"] or ""),
                            "message_text": str(msg["message_text"] or ""),
                            "created_at": str(msg["created_at"] or ""),
                        }
                        if msg["file_id"]:
                            payload["file"] = {
                                "uuid": str(msg["file_uuid"] or ""),
                                "original_filename": str(
                                    msg["original_filename"] or ""
                                ),
                            }
                        mconn = connect(db_path(DEFAULT_DB_NAME))
                        try:
                            enqueue_sync_outbox(
                                mconn,
                                kind="chat:message",
                                payload=payload,
                            )
                        finally:
                            mconn.close()
                except Exception:
                    _log.debug("api_chat_send_message: suppressed error", exc_info=True)

            return jsonify({"ok": True, "message_id": msg_id, "ai_message_id": ai_msg_id})
        finally:
            conn.close()

    @app.post("/api/chat/files")
    @login_required
    def api_chat_upload_file():
        """Загрузить файл для чата."""
        if "file" not in request.files:
            return jsonify({"ok": False, "error": "Файл не указан"}), 400

        file = request.files["file"]
        if not file.filename:
            return jsonify({"ok": False, "error": "Имя файла пустое"}), 400

        import uuid as uuid_lib
        import os

        # Сохраняем файл
        file_uuid = str(uuid_lib.uuid4())
        file_ext = os.path.splitext(file.filename)[1] or ""
        stored_filename = f"{file_uuid}{file_ext}"

        chat_files_dir = ctx.base_dir / "data" / "chat_files"
        chat_files_dir.mkdir(parents=True, exist_ok=True)

        file_path = chat_files_dir / stored_filename
        file.save(str(file_path))

        file_size = file_path.stat().st_size
        mime_type = file.content_type or "application/octet-stream"

        conn = connect_portal(portal_db_path())
        try:
            file_id = create_chat_file(
                conn,
                original_filename=file.filename,
                stored_filename=stored_filename,
                file_size=file_size,
                mime_type=mime_type,
                uploaded_by=int(current_user.id),
            )
            return jsonify({"ok": True, "file_id": file_id})
        finally:
            conn.close()

    @app.get("/api/chat/files/<int:file_id>")
    @login_required
    def api_chat_download_file(file_id: int):
        """Скачать файл из чата."""
        conn = connect_portal(portal_db_path())
        try:
            file_info = get_chat_file(conn, file_id)
            if not file_info:
                return jsonify({"ok": False, "error": "Файл не найден"}), 404

            chat_files_dir = ctx.base_dir / "data" / "chat_files"
            file_path = chat_files_dir / file_info["stored_filename"]

            if not file_path.exists():
                return jsonify({"ok": False, "error": "Файл не найден на диске"}), 404

            return send_file(
                str(file_path),
                mimetype=file_info["mime_type"],
                as_attachment=True,
                download_name=file_info["original_filename"],
            )
        finally:
            conn.close()
