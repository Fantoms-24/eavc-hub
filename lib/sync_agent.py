from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime
from datetime import timedelta
from urllib import request as urlrequest
from urllib.error import URLError, HTTPError
from urllib.parse import urlencode

from web_portal.lib.db import (
    connect,
    ensure_db,
    get_sync_meta,
    list_online_search_rows_after,
    upsert_online_search_rows_from_sync,
    upsert_online_search_meta_from_sync,
    list_seanses_rows_after_rowid,
    list_unit_rows_after_rowid,
    upsert_unit_rows_from_sync,
    set_sync_meta,
    apply_intercept_catalog_delete_from_sync,
    upsert_intercept_catalog_from_sync,
    upsert_intercept_callsign_from_sync,
    upsert_intercept_item_from_sync,
    upsert_intercept_session_from_sync,
    upsert_seanses_rows_from_sync,
    upsert_analysis_assignment_from_sync,
)
from web_portal.lib.auth_db import (
    connect_portal,
    list_targeting_since,
    upsert_targeting_from_sync,
    upsert_user_from_sync,
    set_user_positions_by_username_from_sync,
    list_chat_messages_since,
    upsert_chat_message_from_sync,
)
from web_portal.config import portal_db_path, search_online_db_path
from web_portal.lib.aviation_db_sync import (
    upsert_aviation_frequency_from_sync,
    upsert_aviation_intercept_from_sync,
    upsert_aviation_callsign_from_sync,
)
from web_portal.config import DEFAULT_DB_NAME, db_path
from web_portal.lib.sync_delivery import (
    load_cursor, save_cursors, pending_delivery, record_delivery, read_source, session_source,
)

_log = logging.getLogger("web_portal.sync_agent")
_PULL_CURSOR_OVERLAP_SEC = 2
# Полная сверка справочника нужна при восстановлении/переустановке SERVER:
# курсор HUB мог уже уйти вперёд, а таблица unit на SERVER — оказаться пустой.
_UNIT_FULL_SYNC_INTERVAL_SEC = 300


def _now_ts() -> str:
    # SQLite CURRENT_TIMESTAMP возвращает UTC, поэтому курсоры синка держим в UTC.
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _parse_sync_ts(value: str) -> datetime | None:
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _next_pull_cursor(response: dict, previous: str, max_row_ts: str) -> str:
    """Продвигает курсор без повторной выгрузки всей исторической границы.

    SERVER формирует ``now`` до чтения БД. После полного ответа можно безопасно
    перейти к ``now - 2 секунды``: правки, пришедшие во время сборки ответа,
    попадут в следующее короткое перекрытие. Если сервер отдал лимитированную
    страницу (или это старый SERVER без поля pagination), сохраняем старую
    стратегию по максимальному timestamp, чтобы не потерять хвост истории.
    """
    pagination = response.get("pagination")
    if not isinstance(pagination, dict):
        return str(max_row_ts or previous).strip()
    if any(bool(value) for value in pagination.values()):
        return str(max_row_ts or previous).strip()
    snapshot = _parse_sync_ts(str(response.get("now") or ""))
    if snapshot is None:
        return str(max_row_ts or previous).strip()
    candidate_dt = snapshot - timedelta(seconds=_PULL_CURSOR_OVERLAP_SEC)
    candidate = candidate_dt.strftime("%Y-%m-%d %H:%M:%S")
    prev_dt = _parse_sync_ts(previous)
    if prev_dt is not None and candidate_dt <= prev_dt:
        return str(previous).strip()
    return candidate


def _normalize_positions(positions) -> list[str]:
    if not positions:
        return []
    if isinstance(positions, str):
        raw = positions
    else:
        raw = ",".join([str(x) for x in positions if x is not None])
    parts = [str(x).strip() for x in raw.split(",")]
    return [p for p in parts if p]


def _http_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    timeout: float = 4.0,
    return_errors: bool = False,
) -> dict:
    data = None
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(url=url, data=data, method=method.upper(), headers=hdrs)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            raw = resp.read() or b"{}"
            return json.loads(raw.decode("utf-8") or "{}") or {}
    except HTTPError as e:
        raw = None
        try:
            raw = e.read()
        except Exception:
            _log.debug("_http_json: suppressed error", exc_info=True)
        msg = raw.decode("utf-8", errors="ignore") if raw else str(e)
        if return_errors:
            try:
                parsed = json.loads(msg or "{}")
                if isinstance(parsed, dict):
                    if "ok" not in parsed:
                        parsed["ok"] = False
                    return parsed
            except Exception:
                _log.debug("_http_json: suppressed error", exc_info=True)
            return {"ok": False, "error": f"HTTP {int(e.code)}: {msg[:300]}"}
        raise RuntimeError(f"HTTP {int(e.code)}: {msg[:300]}")
    except URLError as e:
        if return_errors:
            return {"ok": False, "error": str(e)}
        raise RuntimeError(str(e))


def sync_push_priority_once(
    *,
    upstream_base: str,
    sync_key: str,
    db_name: str = DEFAULT_DB_NAME,
    limit: int = 40,
    position_names: list[str] | None = None,
) -> dict:
    """
    Срочная отправка перехватов/смен/чата — без ожидания тысяч seanses в outbox.
    """
    upstream = (upstream_base or "").rstrip("/")
    if not upstream:
        return {"ok": False, "error": "empty upstream"}

    p = db_path(db_name)
    batch = pending_delivery(p, limit=limit, priority_only=True)
    if not batch:
        return {"ok": True, "sent": 0}

    events = []
    ids = []
    for it in batch:
        try:
            payload = json.loads(it["payload_json"] or "{}") or {}
        except Exception:
            payload = {}
        events.append({"kind": it["kind"], "payload": payload})
        ids.append(int(it["id"]))

    import socket

    try:
        hostname = socket.gethostname()
        ip_addr = socket.gethostbyname(hostname)
    except Exception:
        hostname = "unknown"
        ip_addr = "unknown"

    pos_list = _normalize_positions(position_names)
    pos_str = ",".join(pos_list)
    resp = _http_json(
        "POST",
        f"{upstream}/api/sync/push",
        headers={"X-Sync-Key": sync_key},
        body={
            "events": events,
            "hub_id": ip_addr or hostname,
            "hub_name": hostname,
            "position_name": pos_str,
        },
        timeout=4.0,
    )
    if resp.get("ok") is True:
        record_delivery(p, batch)
        return {"ok": True, "sent": len(ids), "server_now": resp.get("now") or ""}

    err = str(resp.get("error") or "push failed")
    record_delivery(p, batch, error=err)
    return {"ok": False, "error": err}


def sync_push_once(
    *,
    upstream_base: str,
    sync_key: str,
    db_name: str = DEFAULT_DB_NAME,
    limit: int = 200,
    position_names: list[str] | None = None,
) -> dict:
    """
    Отправляет pending outbox на upstream (приоритетные kind — первыми в batch).
    """
    upstream = (upstream_base or "").rstrip("/")
    if not upstream:
        return {"ok": False, "error": "empty upstream"}

    p = db_path(db_name)
    batch = pending_delivery(p, limit=limit)
    if not batch:
        return {"ok": True, "sent": 0}

    events = []
    ids = []
    for it in batch:
        try:
            payload = json.loads(it["payload_json"] or "{}") or {}
        except Exception:
            payload = {}
        events.append({"kind": it["kind"], "payload": payload})
        ids.append(int(it["id"]))

    import socket

    try:
        hostname = socket.gethostname()
        ip_addr = socket.gethostbyname(hostname)
    except Exception:
        hostname = "unknown"
        ip_addr = "unknown"

    pos_list = _normalize_positions(position_names)
    pos_str = ",".join(pos_list)
    resp = _http_json(
        "POST",
        f"{upstream}/api/sync/push",
        headers={"X-Sync-Key": sync_key},
        body={
            "events": events,
            "hub_id": ip_addr or hostname,
            "hub_name": hostname,
            "position_name": pos_str,
        },
        timeout=6.0,
    )
    if resp.get("ok") is True:
        record_delivery(p, batch)
        return {"ok": True, "sent": len(ids), "server_now": resp.get("now") or ""}

    # отказ сервера — считаем попыткой
    err = str(resp.get("error") or "push failed")
    record_delivery(p, batch, error=err)
    return {"ok": False, "error": err}


def sync_pull_once(
    *,
    upstream_base: str,
    sync_key: str,
    db_name: str = DEFAULT_DB_NAME,
    position_names: list[str] | None = None,
    include_seanses: bool = True,
) -> dict:
    """
    Подтягивает изменения с upstream и применяет в локальную БД.
    """
    upstream = (upstream_base or "").rstrip("/")
    if not upstream:
        return {"ok": False, "error": "empty upstream"}

    def _resp_empty(d: dict) -> bool:
        return not any(
            (d.get("sessions") or [])
            or (d.get("catalog") or [])
            or (d.get("callsigns") or [])
            or (d.get("items") or [])
            or (d.get("analysis_assignments") or [])
            or (d.get("seanses") or [])
            or (d.get("unit_rows") or [])
            or (d.get("online_search") or [])
            or (d.get("online_search_meta") or {})
            or (d.get("aviation_frequencies") or [])
            or (d.get("aviation_intercepts") or [])
            or (d.get("aviation_callsigns") or [])
            or (d.get("targeting") or [])
            or (d.get("portal_users") or [])
            or (d.get("chat_messages") or [])
        )

    p = db_path(db_name)
    ensure_db(p)
    conn = connect(p)
    try:
        since = get_sync_meta(conn, "last_pull_ts") or "1970-01-01 00:00:00"

        import socket

        try:
            hostname = socket.gethostname()
            ip_addr = socket.gethostbyname(hostname)
        except Exception:
            hostname = "unknown"
            ip_addr = "unknown"

        def _do_pull(since_ts: str) -> dict:
            pos_list = _normalize_positions(position_names)
            pos_str = ",".join(pos_list)
            seanses_limit = max(
                200,
                min(
                    int(os.environ.get("WEB_PORTAL_SYNC_PULL_SEANSES_LIMIT") or 2000),
                    4000,
                ),
            )
            unit_limit = max(
                200,
                min(int(os.environ.get("WEB_PORTAL_SYNC_PULL_UNIT_LIMIT") or 2000), 4000),
            )
            online_limit = max(
                200,
                min(int(os.environ.get("WEB_PORTAL_SYNC_PULL_ONLINE_LIMIT") or 1200), 3000),
            )
            params = {
                "since": since_ts,
                "hub_id": ip_addr or hostname,
                "hub_name": hostname,
                "positions": pos_str,
                "include_seanses": "1" if include_seanses else "0",
                "seanses_limit": str(seanses_limit),
                "unit_limit": str(unit_limit),
                "online_limit": str(online_limit),
            }
            qs = urlencode(params)
            pull_timeout = max(
                8.0,
                min(float(os.environ.get("WEB_PORTAL_SYNC_PULL_TIMEOUT") or 45.0), 120.0),
            )
            return _http_json(
                "GET",
                f"{upstream}/api/sync/pull?{qs}",
                headers={"X-Sync-Key": sync_key},
                body=None,
                timeout=pull_timeout,
                return_errors=True,
            )

        def _do_pull_with_retry(since_ts: str) -> dict:
            import time as _time_retry

            last: dict = {"ok": False, "error": "pull failed"}
            for attempt in range(4):
                last = _do_pull(since_ts)
                err = str(last.get("error") or "")
                if last.get("ok") is True or err != "sync_pull_busy":
                    return last
                if attempt < 3:
                    _time_retry.sleep(min(2.0 * (attempt + 1), 8.0))
            return last

        resp = _do_pull_with_retry(since)
        if resp.get("ok") is not True:
            return {"ok": False, "error": str(resp.get("error") or "pull failed")}

        # Если на хабе уже записан last_pull_ts в локальном времени (впереди UTC),
        # то сервер будет возвращать пусто. В этом случае сделаем одноразовый
        # ретрай с epoch.
        if _resp_empty(resp):
            since_dt = _parse_sync_ts(since)
            if since_dt and since_dt > (datetime.utcnow() + timedelta(seconds=300)):
                since = "1970-01-01 00:00:00"
                resp = _do_pull_with_retry(since)
                if resp.get("ok") is not True:
                    return {
                        "ok": False,
                        "error": str(resp.get("error") or "pull failed"),
                    }

        applied = 0
        errors = []
        from web_portal.lib.db import set_connection_defer_commit

        set_connection_defer_commit(conn, True)
        conn.execute("BEGIN IMMEDIATE")
        # sessions first
        for s in resp.get("sessions") or []:
            try:
                upsert_intercept_session_from_sync(conn, data=s)
                applied += 1
            except Exception as e:
                errors.append(f"session: {str(e)}")
                import logging

                logging.warning(
                    f"sync_pull: failed to apply session {s.get('uuid', '?')}: {e}"
                )
                continue
        # deletions first (чтобы не "возвращалось" после апдейтов)
        for d in resp.get("catalog_deletes") or []:
            try:
                if isinstance(d, dict):
                    apply_intercept_catalog_delete_from_sync(conn, payload=d)
                    applied += 1
            except Exception as e:
                errors.append(f"catalog_delete: {str(e)}")
                import logging

                logging.warning(f"sync_pull: failed to apply catalog_delete: {e}")
                continue
        for c in resp.get("catalog") or []:
            try:
                upsert_intercept_catalog_from_sync(conn, data=c)
                applied += 1
            except Exception as e:
                errors.append(f"catalog: {str(e)}")
                import logging

                logging.warning(
                    f"sync_pull: failed to apply catalog {c.get('uuid', '?')}: {e}"
                )
                continue
        for cs in resp.get("callsigns") or []:
            try:
                upsert_intercept_callsign_from_sync(conn, data=cs)
                applied += 1
            except Exception as e:
                errors.append(f"callsign: {str(e)}")
                import logging

                logging.warning(
                    f"sync_pull: failed to apply callsign {cs.get('uuid', '?')}: {e}"
                )
                continue
        for it in resp.get("items") or []:
            try:
                iid = upsert_intercept_item_from_sync(conn, data=it)
                applied += 1
                try:
                    from web_portal.application.intercepts.state_sig import (
                        compute_intercept_item_content_sig,
                        normalize_intercept_item_content_sig,
                    )
                    from web_portal.app_runtime_caches import intercept_item_live_bump

                    updated_at = str((it or {}).get("updated_at") or "")
                    content = str((it or {}).get("content") or "")
                    sig = normalize_intercept_item_content_sig(
                        compute_intercept_item_content_sig(updated_at, content)
                    )
                    intercept_item_live_bump(
                        int(iid),
                        item_sig=sig,
                        updated_at=updated_at,
                    )
                except Exception:
                    _log.debug("_do_pull_with_retry: suppressed error", exc_info=True)
            except Exception as e:
                errors.append(f"item: {str(e)}")
                import logging

                logging.warning(
                    f"sync_pull: failed to apply item {it.get('uuid', '?')}: {e}"
                )
                continue
        # Analysis assignments
        for a in resp.get("analysis_assignments") or []:
            try:
                if isinstance(a, dict):
                    upsert_analysis_assignment_from_sync(conn, payload=a)
                    applied += 1
            except Exception as e:
                errors.append(f"analysis_assignment: {str(e)}")
                import logging

                logging.warning(f"sync_pull: failed to apply analysis_assignment: {e}")
                continue
        # unit rows
        urows = resp.get("unit_rows")
        if isinstance(urows, list) and urows:
            try:
                upsert_unit_rows_from_sync(conn, rows=urows)
                applied += len(urows)
            except Exception as e:
                errors.append(f"unit_rows: {str(e)}")
                import logging

                logging.warning(f"sync_pull: failed to apply unit_rows: {e}")
        # online_search (отдельная БД)
        os_rows = resp.get("online_search")
        if isinstance(os_rows, list) and os_rows:
            try:
                search_p = search_online_db_path()
                ensure_db(search_p)
                search_conn = connect(search_p)
                try:
                    upsert_online_search_rows_from_sync(search_conn, rows=os_rows)
                finally:
                    search_conn.close()
                applied += len(os_rows)
            except Exception as e:
                errors.append(f"online_search: {str(e)}")
                import logging

                logging.warning(f"sync_pull: failed to apply online_search: {e}")
        os_meta = resp.get("online_search_meta")
        if isinstance(os_meta, dict) and os_meta:
            try:
                search_p = search_online_db_path()
                ensure_db(search_p)
                search_conn = connect(search_p)
                try:
                    upsert_online_search_meta_from_sync(search_conn, payload=os_meta)
                finally:
                    search_conn.close()
                applied += 1
            except Exception as e:
                errors.append(f"online_search_meta: {str(e)}")
                import logging

                logging.warning(f"sync_pull: failed to apply online_search_meta: {e}")
        # Aviation sync
        for af in resp.get("aviation_frequencies") or []:
            try:
                upsert_aviation_frequency_from_sync(conn, data=af)
                applied += 1
            except Exception as e:
                errors.append(f"aviation_frequency: {str(e)}")
                import logging

                logging.warning(
                    f"sync_pull: failed to apply aviation_frequency {af.get('uuid', '?')}: {e}"
                )
                continue
        for ai in resp.get("aviation_intercepts") or []:
            try:
                upsert_aviation_intercept_from_sync(conn, data=ai)
                applied += 1
            except Exception as e:
                errors.append(f"aviation_intercept: {str(e)}")
                import logging

                logging.warning(
                    f"sync_pull: failed to apply aviation_intercept {ai.get('uuid', '?')}: {e}"
                )
                continue
        for ac in resp.get("aviation_callsigns") or []:
            try:
                upsert_aviation_callsign_from_sync(conn, data=ac)
                applied += 1
            except Exception as e:
                errors.append(f"aviation_callsign: {str(e)}")
                import logging

                logging.warning(
                    f"sync_pull: failed to apply aviation_callsign {ac.get('uuid', '?')}: {e}"
                )
                continue
        # Targeting из portal_db
        pconn = connect_portal(portal_db_path())
        try:
            for t in resp.get("targeting") or []:
                try:
                    upsert_targeting_from_sync(pconn, payload=t)
                    applied += 1
                except Exception as e:
                    errors.append(f"targeting: {str(e)}")
                    import logging

                    logging.warning(
                        f"sync_pull: failed to apply targeting {t.get('uuid', '?')}: {e}"
                    )
                    continue
        finally:
            pconn.close()

        # portal users/roles/passwords/positions (server -> hub)
        pconn = connect_portal(portal_db_path())
        try:
            for u in resp.get("portal_users") or []:
                try:
                    if isinstance(u, dict):
                        upsert_user_from_sync(pconn, payload=u)
                        # positions may be embedded in payload (name:role)
                        positions = u.get("positions") or []
                        if isinstance(positions, list) and positions:
                            set_user_positions_by_username_from_sync(
                                pconn,
                                username=str(u.get("username") or ""),
                                positions=[str(x) for x in positions],
                            )
                        applied += 1
                except Exception as e:
                    errors.append(f"portal_user: {str(e)}")
                    import logging

                    logging.warning(f"sync_pull: failed to apply portal_user: {e}")
                    continue

            # Chat messages (server -> hub)
            for msg in resp.get("chat_messages") or []:
                try:
                    if isinstance(msg, dict):
                        upsert_chat_message_from_sync(pconn, payload=msg)
                        applied += 1
                except Exception as e:
                    errors.append(f"chat_message: {str(e)}")
                    import logging

                    logging.warning(f"sync_pull: failed to apply chat_message: {e}")
                    continue
        finally:
            pconn.close()

        # high-watermark: не используем server "now", а двигаем курсор по фактическим updated_at
        max_ts = ""
        try:
            for s in resp.get("sessions") or []:
                max_ts = max(
                    max_ts, str(s.get("started_at") or ""), str(s.get("ended_at") or "")
                )
            for d in resp.get("catalog_deletes") or []:
                if isinstance(d, dict):
                    max_ts = max(max_ts, str(d.get("deleted_at") or ""))
            for c in resp.get("catalog") or []:
                max_ts = max(max_ts, str(c.get("updated_at") or ""))
            for cs in resp.get("callsigns") or []:
                max_ts = max(max_ts, str(cs.get("updated_at") or ""))
            for it in resp.get("items") or []:
                max_ts = max(max_ts, str(it.get("updated_at") or ""))
            for a in resp.get("analysis_assignments") or []:
                max_ts = max(max_ts, str((a or {}).get("updated_at") or ""))
            for r in resp.get("seanses") or []:
                max_ts = max(max_ts, str((r or {}).get("created_at") or ""))
            for r in resp.get("unit_rows") or []:
                max_ts = max(max_ts, str((r or {}).get("updated_at") or ""))
            for r in resp.get("online_search") or []:
                max_ts = max(max_ts, str((r or {}).get("updated_at") or ""))
            try:
                m = resp.get("online_search_meta") or {}
                if isinstance(m, dict):
                    max_ts = max(max_ts, str(m.get("updated_at") or ""))
            except Exception:
                _log.debug("_do_pull_with_retry: suppressed error", exc_info=True)
            for af in resp.get("aviation_frequencies") or []:
                max_ts = max(max_ts, str(af.get("updated_at") or ""))
            for ai in resp.get("aviation_intercepts") or []:
                max_ts = max(max_ts, str(ai.get("updated_at") or ""))
            for ac in resp.get("aviation_callsigns") or []:
                max_ts = max(max_ts, str(ac.get("updated_at") or ""))
            for t in resp.get("targeting") or []:
                max_ts = max(max_ts, str(t.get("created_at") or ""))
            for u in resp.get("portal_users") or []:
                if isinstance(u, dict):
                    max_ts = max(
                        max_ts, str(u.get("_updated_at") or u.get("updated_at") or "")
                    )
            for msg in resp.get("chat_messages") or []:
                if isinstance(msg, dict):
                    max_ts = max(max_ts, str(msg.get("created_at") or ""))
        except Exception:
            max_ts = ""

        # коммитим все изменения одним fsync (batch вместо commit на каждый item/session)
        conn.commit()
        set_connection_defer_commit(conn, False)
        # Release main before acquiring the session writer. Legacy storage uses
        # the same file; separate storage's watcher may need main for ID alerts.
        rows = resp.get("seanses")
        if isinstance(rows, list) and rows:
            try:
                from web_portal.lib.seans_db import connect_seans_storage

                seans_conn = connect_seans_storage()
                try:
                    upsert_seanses_rows_from_sync(seans_conn, rows=rows)
                finally:
                    seans_conn.close()
                applied += len(rows)
            except Exception as e:
                errors.append(f"seanses: {str(e)}")
                _log.warning("sync_pull: failed to apply seanses batch: %s", e)
        new_cursor = _next_pull_cursor(resp, since, max_ts)
        if new_cursor:
            set_sync_meta(conn, "last_pull_ts", new_cursor)
            conn.commit()
        now = str(resp.get("now") or "").strip() or _now_ts()
        result = {
            "ok": True,
            "applied": applied,
            "since": since,
            "now": now,
            "cursor": (new_cursor or since),
        }
        if errors:
            result["errors"] = errors[:10]  # первые 10 ошибок
        return result
    finally:
        try:
            from web_portal.lib.db import finish_connection_defer_commit

            finish_connection_defer_commit(conn, rollback=True)
        except Exception:
            _log.debug("_resp_empty: suppressed error", exc_info=True)
        try:
            from web_portal.lib.db import unregister_connection

            unregister_connection(conn)
            conn.close()
        except Exception:
            _log.debug("_resp_empty: suppressed error", exc_info=True)


def sync_push_seanses_once(
    *,
    upstream_base: str,
    sync_key: str,
    db_name: str = DEFAULT_DB_NAME,
    limit: int = 5000,
    position_names: list[str] | None = None,
) -> dict:
    upstream = (upstream_base or "").rstrip("/")
    if not upstream:
        return {"ok": False, "error": "empty upstream"}
    p = session_source()
    last_rowid = int(load_cursor(p, "seanses_last_rowid") or 0)
    with read_source(p) as seans_conn:
        rows = list_seanses_rows_after_rowid(
            seans_conn, after_rowid=last_rowid, limit=limit, initialize=False,
        )
    if not rows:
        return {"ok": True, "sent": 0}
    max_rowid = max(int(r.get("rowid") or 0) for r in rows)
    pos_list = _normalize_positions(position_names)
    pos_str = ",".join(pos_list)
    resp = _http_json(
        "POST",
        f"{upstream}/api/sync/push",
        headers={"X-Sync-Key": sync_key},
        body={
            "events": [
                {
                    "kind": "seanses:batch",
                    "payload": {"rows": rows, "max_rowid": max_rowid},
                }
            ],
            "position_name": pos_str,
        },
        timeout=10.0,
    )
    if resp.get("ok") is True:
        save_cursors(p, {"seanses_last_rowid": str(max_rowid)})
        return {"ok": True, "sent": len(rows), "max_rowid": max_rowid}
    return {"ok": False, "error": str(resp.get("error") or "push failed")}


def sync_push_online_search_once(
    *,
    upstream_base: str,
    sync_key: str,
    db_name: str = DEFAULT_DB_NAME,
    limit: int = 500,
    position_names: list[str] | None = None,
) -> dict:
    upstream = (upstream_base or "").rstrip("/")
    if not upstream:
        return {"ok": False, "error": "empty upstream"}
    search_p = search_online_db_path()
    main_p = db_path(db_name)
    last_ts = load_cursor(main_p, "online_search_last_ts") or "1970-01-01 00:00:00"
    last_id = int(load_cursor(main_p, "online_search_last_id") or 0)
    with read_source(search_p) as search_conn:
        rows = list_online_search_rows_after(
            search_conn, after_updated_at=last_ts, after_id=last_id,
            limit=limit, initialize=False,
        )
    if not rows:
        return {"ok": True, "sent": 0}
    tail = rows[-1]
    new_ts = str(tail.get("updated_at") or last_ts)
    new_id = int(tail.get("id") or last_id)
    pos_list = _normalize_positions(position_names)
    pos_str = ",".join(pos_list)
    resp = _http_json(
        "POST",
        f"{upstream}/api/sync/push",
        headers={"X-Sync-Key": sync_key},
        body={
            "events": [{"kind": "online_search:batch", "payload": {"rows": rows}}],
            "position_name": pos_str,
        },
        timeout=10.0,
    )
    if resp.get("ok") is True:
        save_cursors(main_p, {"online_search_last_ts": new_ts, "online_search_last_id": str(new_id)})
        return {
            "ok": True,
            "sent": len(rows),
            "cursor": {"ts": new_ts, "id": new_id},
        }
    return {"ok": False, "error": str(resp.get("error") or "push failed")}


def sync_push_unit_once(
    *,
    upstream_base: str,
    sync_key: str,
    db_name: str = DEFAULT_DB_NAME,
    limit: int = 5000,
    position_names: list[str] | None = None,
) -> dict:
    upstream = (upstream_base or "").rstrip("/")
    if not upstream:
        return {"ok": False, "error": "empty upstream"}
    p = db_path(db_name)
    last_rowid = int(load_cursor(p, "unit_last_rowid") or 0)
    with read_source(p) as conn:
        rows = list_unit_rows_after_rowid(conn, after_rowid=last_rowid, limit=limit, initialize=False)
    is_full_reconciliation = False
    full_sync_rowid = 0
    if not rows:
        last_full_raw = load_cursor(p, "unit_last_full_sync_at")
        full_sync_rowid = int(load_cursor(p, "unit_full_sync_rowid") or 0)
        try:
            last_full_at = float(last_full_raw or 0)
        except (TypeError, ValueError):
            last_full_at = 0.0
        # Ненулевой rowid означает, что предыдущая полная сверка ещё идёт:
        # продолжаем её сразу, не ждём следующего пятиминутного окна.
        if (
            not full_sync_rowid
            and (time.time() - last_full_at) < _UNIT_FULL_SYNC_INTERVAL_SEC
        ):
            return {"ok": True, "sent": 0}
        # Повторно отправляем весь актуальный справочник. Принимающая сторона
        # применяет только действительно новые значения, поэтому такая сверка
        # не создаёт бесконечный обмен и не перезаписывает свежую правку SERVER.
        with read_source(p) as conn:
            rows = list_unit_rows_after_rowid(
                conn,
                after_rowid=full_sync_rowid,
                limit=limit,
                initialize=False,
            )
        if not rows:
            save_cursors(
                p,
                {
                    "unit_last_full_sync_at": str(time.time()),
                    "unit_full_sync_rowid": "0",
                },
            )
            return {"ok": True, "sent": 0, "full": True}
        is_full_reconciliation = True

    max_rowid = max(int(r.get("rowid") or 0) for r in rows)
    pos_list = _normalize_positions(position_names)
    pos_str = ",".join(pos_list)
    resp = _http_json(
        "POST",
        f"{upstream}/api/sync/push",
        headers={"X-Sync-Key": sync_key},
        body={
            "events": [
                {
                    "kind": "unit:batch",
                    "payload": {"rows": rows, "max_rowid": max_rowid},
                }
            ],
            "position_name": pos_str,
        },
        timeout=10.0,
    )
    if resp.get("ok") is True:
        cursors = {"unit_last_rowid": str(max_rowid)}
        if is_full_reconciliation:
            if len(rows) >= limit:
                cursors["unit_full_sync_rowid"] = str(max_rowid)
            else:
                cursors["unit_last_full_sync_at"] = str(time.time())
                cursors["unit_full_sync_rowid"] = "0"
        save_cursors(p, cursors)
        return {
            "ok": True,
            "sent": len(rows),
            "max_rowid": max_rowid,
            "full": is_full_reconciliation,
            "more": bool(is_full_reconciliation and len(rows) >= limit),
        }
    return {"ok": False, "error": str(resp.get("error") or "push failed")}


def run_sync_loop(
    *,
    upstream_base: str,
    sync_key: str,
    interval_sec: float = 5.0,
    position_names: list[str] | None = None,
    include_seanses: bool = True,
) -> None:
    """
    Бесконечный цикл синхронизации. Запускать в daemon-thread.
    """
    sleep_s = max(3.0, float(interval_sec or 5.0))
    # Одновременный старт трёх HUB раньше создавал шип /sync/pull на SERVER.
    # Небольшой случайный сдвиг сохраняет оперативность, но разводит запросы.
    time.sleep(random.uniform(0.1, min(3.0, sleep_s * 0.75)))
    while True:
        # Важно: один упавший шаг не должен блокировать остальные (особенно pull).
        try:
            sync_push_priority_once(
                upstream_base=upstream_base,
                sync_key=sync_key,
                position_names=position_names,
            )
        except Exception:
            _log.debug("run_sync_loop: suppressed error", exc_info=True)
        try:
            sync_push_once(
                upstream_base=upstream_base,
                sync_key=sync_key,
                position_names=position_names,
            )
        except Exception:
            _log.debug("run_sync_loop: suppressed error", exc_info=True)
        if include_seanses:
            try:
                sync_push_seanses_once(
                    upstream_base=upstream_base,
                    sync_key=sync_key,
                    position_names=position_names,
                )
            except Exception:
                _log.debug("run_sync_loop: suppressed error", exc_info=True)
        try:
            sync_push_online_search_once(
                upstream_base=upstream_base,
                sync_key=sync_key,
                position_names=position_names,
            )
        except Exception:
            _log.debug("run_sync_loop: suppressed error", exc_info=True)
        try:
            sync_push_unit_once(
                upstream_base=upstream_base,
                sync_key=sync_key,
                position_names=position_names,
            )
        except Exception:
            _log.debug("run_sync_loop: suppressed error", exc_info=True)
        try:
            sync_pull_once(
                upstream_base=upstream_base,
                sync_key=sync_key,
                position_names=position_names,
                include_seanses=include_seanses,
            )
        except Exception:
            _log.debug("run_sync_loop: suppressed error", exc_info=True)
        time.sleep(sleep_s)
