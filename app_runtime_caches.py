"""In-memory кэши и состояние прослушивания аудио для web_portal (вынесено из app.py)."""

from __future__ import annotations

import threading
import time

from flask import request
from flask_login import current_user

# --- Audio listening state ---
_AUDIO_LISTENING: dict[str, dict[str, float]] = {}
_AUDIO_LISTENING_LOCK = threading.Lock()
_AUDIO_LISTENING_TTL_SEC = 30

_ANALYSIS_RESP_CACHE: dict[str, dict[str, object]] = {}
_ANALYSIS_RESP_CACHE_LOCK = threading.Lock()
_ANALYSIS_RESP_CACHE_TTL_SEC = 45.0

_INTERCEPTS_STATE_CACHE: dict[str, dict[str, object]] = {}
_INTERCEPTS_STATE_CACHE_LOCK = threading.Lock()
# Короткий TTL: смена/каталог могут меняться не только локально (через эндпоинты,
# которые чистят кэш), но и через sync pull с upstream. Кэш на 35 с прятал такие
# изменения и приводил к тому, что смена не переключалась у всех. Запрос state идёт
# по маленьким таблицам, поэтому короткий TTL не нагружает БД.
_INTERCEPTS_STATE_CACHE_TTL_SEC = 0.8

# --- Live-уведомления об изменении бланка (long-poll /api/intercepts/item/wait) ---
_INTERCEPT_ITEM_LIVE: dict[int, dict[str, object]] = {}
_INTERCEPT_ITEM_WAITERS: dict[int, list[threading.Event]] = {}
_INTERCEPT_ITEM_LIVE_LOCK = threading.Lock()


def intercept_item_live_bump(
    item_id: int, *, item_sig: str, updated_at: str = ""
) -> None:
    iid = int(item_id or 0)
    if iid <= 0 or not str(item_sig or "").strip():
        return
    with _INTERCEPT_ITEM_LIVE_LOCK:
        _INTERCEPT_ITEM_LIVE[iid] = {
            "item_sig": str(item_sig or ""),
            "updated_at": str(updated_at or ""),
            "ts": time.time(),
        }
        for ev in _INTERCEPT_ITEM_WAITERS.get(iid, []):
            ev.set()


def intercept_item_live_wait(
    item_id: int, item_sig: str, *, timeout_sec: float = 25.0
) -> dict[str, object]:
    iid = int(item_id or 0)
    if iid <= 0:
        return {"changed": False}
    sig = str(item_sig or "")
    timeout = max(0.5, min(30.0, float(timeout_sec or 25.0)))

    def _snapshot() -> dict[str, object] | None:
        cur = _INTERCEPT_ITEM_LIVE.get(iid)
        if not isinstance(cur, dict):
            return None
        live_sig = str(cur.get("item_sig") or "")
        if live_sig and live_sig != sig:
            return {
                "changed": True,
                "item_sig": live_sig,
                "updated_at": str(cur.get("updated_at") or ""),
            }
        return None

    with _INTERCEPT_ITEM_LIVE_LOCK:
        hit = _snapshot()
        if hit:
            return hit

    ev = threading.Event()
    with _INTERCEPT_ITEM_LIVE_LOCK:
        _INTERCEPT_ITEM_WAITERS.setdefault(iid, []).append(ev)
    try:
        ev.wait(timeout=timeout)
    finally:
        with _INTERCEPT_ITEM_LIVE_LOCK:
            waiters = _INTERCEPT_ITEM_WAITERS.get(iid, [])
            if ev in waiters:
                waiters.remove(ev)

    with _INTERCEPT_ITEM_LIVE_LOCK:
        hit = _snapshot()
        if hit:
            return hit
    return {"changed": False}

_DOC_STATS_CACHE: dict[str, dict[str, object]] = {}
_DOC_STATS_CACHE_LOCK = threading.Lock()
_DOC_STATS_CACHE_TTL_SEC = 45.0

_CALLSIGNS_CACHE: dict[str, dict[str, object]] = {}
_CALLSIGNS_CACHE_LOCK = threading.Lock()
_CALLSIGNS_CACHE_TTL_SEC = 60.0

_UNITS_TREE_CACHE: dict[str, dict[str, object]] = {}
_UNITS_TREE_CACHE_LOCK = threading.Lock()
_UNITS_TREE_CACHE_TTL_SEC = 60.0

_ASSIGNMENTS_CACHE: dict[str, dict[str, object]] = {}
_ASSIGNMENTS_CACHE_LOCK = threading.Lock()
_ASSIGNMENTS_CACHE_TTL_SEC = 60.0

_ONLINE_IMPORT_PROGRESS: dict[str, dict[str, object]] = {}
_ONLINE_IMPORT_PROGRESS_LOCK = threading.Lock()
_ONLINE_IMPORT_PROGRESS_TTL_SEC = 1800


def online_import_progress_set(import_id: str, payload: dict[str, object]) -> None:
    iid = str(import_id or "").strip()
    if not iid:
        return
    now_ts = time.time()
    with _ONLINE_IMPORT_PROGRESS_LOCK:
        old = _ONLINE_IMPORT_PROGRESS.get(iid) or {}
        next_payload = {**old, **payload, "updated_ts": now_ts}
        _ONLINE_IMPORT_PROGRESS[iid] = next_payload
        stale_keys = [
            k
            for k, v in _ONLINE_IMPORT_PROGRESS.items()
            if (now_ts - float((v or {}).get("updated_ts") or 0.0))
            > _ONLINE_IMPORT_PROGRESS_TTL_SEC
        ]
        for k in stale_keys:
            _ONLINE_IMPORT_PROGRESS.pop(k, None)


def online_import_progress_get(import_id: str) -> dict[str, object] | None:
    iid = str(import_id or "").strip()
    if not iid:
        return None
    now_ts = time.time()
    with _ONLINE_IMPORT_PROGRESS_LOCK:
        item = _ONLINE_IMPORT_PROGRESS.get(iid)
        if not item:
            return None
        if (
            now_ts - float((item or {}).get("updated_ts") or 0.0)
            > _ONLINE_IMPORT_PROGRESS_TTL_SEC
        ):
            _ONLINE_IMPORT_PROGRESS.pop(iid, None)
            return None
        return dict(item)


_FOLDER_IMPORT_PROGRESS: dict[str, dict[str, object]] = {}
_FOLDER_IMPORT_PROGRESS_LOCK = threading.Lock()
_FOLDER_IMPORT_PROGRESS_TTL_SEC = 3600


def folder_import_progress_set(import_id: str, payload: dict[str, object]) -> None:
    iid = str(import_id or "").strip()
    if not iid:
        return
    now_ts = time.time()
    with _FOLDER_IMPORT_PROGRESS_LOCK:
        old = _FOLDER_IMPORT_PROGRESS.get(iid) or {}
        next_payload = {**old, **payload, "updated_ts": now_ts}
        _FOLDER_IMPORT_PROGRESS[iid] = next_payload
        stale_keys = [
            k
            for k, v in _FOLDER_IMPORT_PROGRESS.items()
            if (now_ts - float((v or {}).get("updated_ts") or 0.0))
            > _FOLDER_IMPORT_PROGRESS_TTL_SEC
        ]
        for k in stale_keys:
            _FOLDER_IMPORT_PROGRESS.pop(k, None)


def folder_import_progress_get(import_id: str) -> dict[str, object] | None:
    iid = str(import_id or "").strip()
    if not iid:
        return None
    now_ts = time.time()
    with _FOLDER_IMPORT_PROGRESS_LOCK:
        item = _FOLDER_IMPORT_PROGRESS.get(iid)
        if not item:
            return None
        if (
            now_ts - float((item or {}).get("updated_ts") or 0.0)
            > _FOLDER_IMPORT_PROGRESS_TTL_SEC
        ):
            _FOLDER_IMPORT_PROGRESS.pop(iid, None)
            return None
        return dict(item)


def analysis_cache_get(key: str) -> dict[str, object] | None:
    now_ts = time.time()
    with _ANALYSIS_RESP_CACHE_LOCK:
        item = _ANALYSIS_RESP_CACHE.get(str(key))
        if not item:
            return None
        ts = float(item.get("ts") or 0.0)
        ttl_sec = float(item.get("ttl_sec") or _ANALYSIS_RESP_CACHE_TTL_SEC)
        if (now_ts - ts) > ttl_sec:
            _ANALYSIS_RESP_CACHE.pop(str(key), None)
            return None
        payload = item.get("payload")
        return dict(payload) if isinstance(payload, dict) else None


def analysis_cache_set(key: str, payload: dict[str, object], ttl_sec: float | None = None) -> None:
    now_ts = time.time()
    with _ANALYSIS_RESP_CACHE_LOCK:
        _ANALYSIS_RESP_CACHE[str(key)] = {
            "ts": now_ts,
            "ttl_sec": float(ttl_sec or _ANALYSIS_RESP_CACHE_TTL_SEC),
            "payload": dict(payload),
        }
        if len(_ANALYSIS_RESP_CACHE) > 600:
            victims = sorted(
                _ANALYSIS_RESP_CACHE.items(),
                key=lambda kv: float((kv[1] or {}).get("ts") or 0.0),
            )[:120]
            for k, _v in victims:
                _ANALYSIS_RESP_CACHE.pop(k, None)


def analysis_cache_key(endpoint: str, *, pos: str | None) -> str:
    qs = request.query_string.decode("utf-8", errors="ignore")
    return (
        f"{endpoint}|u={int(getattr(current_user, 'id', 0) or 0)}|"
        f"pos={str(pos or '')}|qs={qs}"
    )


def intercepts_state_cache_get(key: str) -> dict[str, object] | None:
    now_ts = time.time()
    with _INTERCEPTS_STATE_CACHE_LOCK:
        item = _INTERCEPTS_STATE_CACHE.get(str(key))
        if not item:
            return None
        ts = float(item.get("ts") or 0.0)
        if (now_ts - ts) > _INTERCEPTS_STATE_CACHE_TTL_SEC:
            _INTERCEPTS_STATE_CACHE.pop(str(key), None)
            return None
        payload = item.get("payload")
        return dict(payload) if isinstance(payload, dict) else None


def intercepts_state_cache_set(key: str, payload: dict[str, object]) -> None:
    now_ts = time.time()
    with _INTERCEPTS_STATE_CACHE_LOCK:
        _INTERCEPTS_STATE_CACHE[str(key)] = {"ts": now_ts, "payload": dict(payload)}
        if len(_INTERCEPTS_STATE_CACHE) > 300:
            victims = sorted(
                _INTERCEPTS_STATE_CACHE.items(),
                key=lambda kv: float((kv[1] or {}).get("ts") or 0.0),
            )[:80]
            for k, _v in victims:
                _INTERCEPTS_STATE_CACHE.pop(k, None)


def intercepts_state_cache_clear() -> None:
    """Сброс кэша state перехватов (избранное/архив/порядок unit — per-user)."""
    with _INTERCEPTS_STATE_CACHE_LOCK:
        _INTERCEPTS_STATE_CACHE.clear()


def audio_listening_cleanup(now_ts: float | None = None) -> None:
    import time as _time

    now = now_ts or _time.time()
    with _AUDIO_LISTENING_LOCK:
        to_del = []
        for key, users in _AUDIO_LISTENING.items():
            users2 = {
                u: ts
                for u, ts in (users or {}).items()
                if now - ts <= _AUDIO_LISTENING_TTL_SEC
            }
            if users2:
                _AUDIO_LISTENING[key] = users2
            else:
                to_del.append(key)
        for k in to_del:
            _AUDIO_LISTENING.pop(k, None)


def _audio_listening_token(username: str, client_id: str) -> str:
    """Токен слушателя: username + client_id, чтобы различать компьютеры с одним логином."""
    return f"{username}\x00{client_id or ''}"


def audio_listening_token_username(token: str) -> str:
    return str(token or "").split("\x00", 1)[0]


def audio_listening_token_client(token: str) -> str:
    parts = str(token or "").split("\x00", 1)
    return parts[1] if len(parts) > 1 else ""


def audio_listening_snapshot() -> dict[str, list[str]]:
    """file_key -> список токенов (username\\x00client_id)."""
    import time as _time

    audio_listening_cleanup(_time.time())
    with _AUDIO_LISTENING_LOCK:
        return {k: list((v or {}).keys()) for k, v in _AUDIO_LISTENING.items()}


def audio_listening_start(file_key: str, username: str, client_id: str = "") -> None:
    if not file_key or not username:
        return
    import time as _time

    token = _audio_listening_token(username, client_id)
    with _AUDIO_LISTENING_LOCK:
        users = _AUDIO_LISTENING.get(file_key) or {}
        users[token] = _time.time()
        _AUDIO_LISTENING[file_key] = users


def audio_listening_stop(file_key: str, username: str, client_id: str = "") -> None:
    if not file_key or not username:
        return
    token = _audio_listening_token(username, client_id)
    with _AUDIO_LISTENING_LOCK:
        users = _AUDIO_LISTENING.get(file_key) or {}
        users.pop(token, None)
        if users:
            _AUDIO_LISTENING[file_key] = users
        else:
            _AUDIO_LISTENING.pop(file_key, None)


def _ttl_cache_get(
    store: dict[str, dict[str, object]],
    lock: threading.Lock,
    key: str,
    ttl_sec: float,
) -> object | None:
    now_ts = time.time()
    with lock:
        item = store.get(str(key))
        if not item:
            return None
        ts = float(item.get("ts") or 0.0)
        if (now_ts - ts) > ttl_sec:
            store.pop(str(key), None)
            return None
        return item.get("payload")


def _ttl_cache_set(
    store: dict[str, dict[str, object]],
    lock: threading.Lock,
    key: str,
    payload: object,
    max_size: int = 400,
    evict_batch: int = 80,
) -> None:
    now_ts = time.time()
    with lock:
        store[str(key)] = {"ts": now_ts, "payload": payload}
        if len(store) > max_size:
            victims = sorted(
                store.items(),
                key=lambda kv: float((kv[1] or {}).get("ts") or 0.0),
            )[:evict_batch]
            for k, _v in victims:
                store.pop(k, None)


def _ttl_cache_clear_prefix(
    store: dict[str, dict[str, object]],
    lock: threading.Lock,
    prefix: str | None = None,
) -> int:
    with lock:
        if not prefix:
            n = len(store)
            store.clear()
            return n
        keys = [k for k in store.keys() if k.startswith(str(prefix))]
        for k in keys:
            store.pop(k, None)
        return len(keys)


# --- doc_stats cache (таблица сеансов по диапазону дат и позиции) ---
def doc_stats_cache_get(key: str) -> object | None:
    return _ttl_cache_get(
        _DOC_STATS_CACHE, _DOC_STATS_CACHE_LOCK, key, _DOC_STATS_CACHE_TTL_SEC
    )


def doc_stats_cache_set(key: str, payload: object) -> None:
    _ttl_cache_set(_DOC_STATS_CACHE, _DOC_STATS_CACHE_LOCK, key, payload, max_size=300)


def doc_stats_cache_invalidate(position_name: str | None = None) -> int:
    prefix = (
        f"doc_stats|pos={str(position_name or '')}|"
        if position_name is not None
        else None
    )
    return _ttl_cache_clear_prefix(_DOC_STATS_CACHE, _DOC_STATS_CACHE_LOCK, prefix)


def doc_stats_cache_key(
    datetime_from: str | None,
    datetime_to: str | None,
    position_name: str | None = None,
    extra: str = "",
) -> str:
    return (
        f"doc_stats|pos={str(position_name or '')}|"
        f"from={str(datetime_from or '')}|to={str(datetime_to or '')}|{extra}"
    )


# --- callsigns cache (позывные по позиции) ---
def callsigns_cache_get(key: str) -> object | None:
    return _ttl_cache_get(
        _CALLSIGNS_CACHE, _CALLSIGNS_CACHE_LOCK, key, _CALLSIGNS_CACHE_TTL_SEC
    )


def callsigns_cache_set(key: str, payload: object) -> None:
    _ttl_cache_set(_CALLSIGNS_CACHE, _CALLSIGNS_CACHE_LOCK, key, payload, max_size=200)


def callsigns_cache_invalidate(position_name: str | None = None) -> int:
    prefix = (
        f"callsigns|pos={str(position_name or '')}|"
        if position_name is not None
        else None
    )
    return _ttl_cache_clear_prefix(_CALLSIGNS_CACHE, _CALLSIGNS_CACHE_LOCK, prefix)


def callsigns_cache_key(position_name: str | None, extra: str = "") -> str:
    return f"callsigns|pos={str(position_name or '')}|{extra}"


# --- units_tree cache (дерево подразделений по позиции) ---
def units_tree_cache_get(key: str) -> object | None:
    return _ttl_cache_get(
        _UNITS_TREE_CACHE, _UNITS_TREE_CACHE_LOCK, key, _UNITS_TREE_CACHE_TTL_SEC
    )


def units_tree_cache_set(key: str, payload: object) -> None:
    _ttl_cache_set(
        _UNITS_TREE_CACHE, _UNITS_TREE_CACHE_LOCK, key, payload, max_size=200
    )


def units_tree_cache_invalidate(position_name: str | None = None) -> int:
    prefix = (
        f"units|pos={str(position_name or '')}|"
        if position_name is not None
        else None
    )
    return _ttl_cache_clear_prefix(_UNITS_TREE_CACHE, _UNITS_TREE_CACHE_LOCK, prefix)


def units_tree_cache_key(position_name: str | None, extra: str = "") -> str:
    return f"units|pos={str(position_name or '')}|{extra}"


# --- assignments cache (привязки позывных к частоте/группе) ---
def assignments_cache_get(key: str) -> object | None:
    return _ttl_cache_get(
        _ASSIGNMENTS_CACHE, _ASSIGNMENTS_CACHE_LOCK, key, _ASSIGNMENTS_CACHE_TTL_SEC
    )


def assignments_cache_set(key: str, payload: object) -> None:
    _ttl_cache_set(
        _ASSIGNMENTS_CACHE, _ASSIGNMENTS_CACHE_LOCK, key, payload, max_size=400
    )


def assignments_cache_invalidate(position_name: str | None = None) -> int:
    prefix = (
        f"assign|pos={str(position_name or '')}|"
        if position_name is not None
        else None
    )
    return _ttl_cache_clear_prefix(_ASSIGNMENTS_CACHE, _ASSIGNMENTS_CACHE_LOCK, prefix)


def assignments_cache_key(
    position_name: str | None,
    frequency: str | None = None,
    group_code: str | None = None,
    extra: str = "",
) -> str:
    return (
        f"assign|pos={str(position_name or '')}|"
        f"f={str(frequency or '')}|g={str(group_code or '')}|{extra}"
    )


def all_caches_clear() -> dict[str, int]:
    """Полный сброс всех TTL-кэшей. Для /admin операций."""
    n1 = _ttl_cache_clear_prefix(_ANALYSIS_RESP_CACHE, _ANALYSIS_RESP_CACHE_LOCK)
    n2 = _ttl_cache_clear_prefix(_INTERCEPTS_STATE_CACHE, _INTERCEPTS_STATE_CACHE_LOCK)
    n3 = _ttl_cache_clear_prefix(_DOC_STATS_CACHE, _DOC_STATS_CACHE_LOCK)
    n4 = _ttl_cache_clear_prefix(_CALLSIGNS_CACHE, _CALLSIGNS_CACHE_LOCK)
    n5 = _ttl_cache_clear_prefix(_UNITS_TREE_CACHE, _UNITS_TREE_CACHE_LOCK)
    n6 = _ttl_cache_clear_prefix(_ASSIGNMENTS_CACHE, _ASSIGNMENTS_CACHE_LOCK)
    return {
        "analysis": n1,
        "intercepts_state": n2,
        "doc_stats": n3,
        "callsigns": n4,
        "units_tree": n5,
        "assignments": n6,
    }
