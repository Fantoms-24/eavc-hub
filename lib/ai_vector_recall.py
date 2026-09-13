"""
Семантический RAG для AI-планировщика: бланки перехватов (intercept_items) + вкладка «Сеансы» (seanses).
Храним float32-векторы в SQLite (BLOB) и ищем top-k по косинусу в NumPy — без нативного sqlite-vec
(стабильнее на Windows; при росте объёма можно заменить на sqlite-vec KNN).

Инкремент: sync_vectors_incremental() — только изменившиеся строки (fingerprint + ai_vector_index_state).
Полный прогон: reindex_*. Скрипт: scripts/reindex_ai_vectors.py (--incremental).
Нужны Ollama и модель эмбеддингов, напр. ollama pull nomic-embed-text
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from typing import Any, Callable, Literal

IndexOutcome = Literal["indexed", "skipped", "failed"]

import numpy as np

from web_portal.lib.ai_client import AIClientError, embed_text

_INTERCEPT_CHUNK = int(os.environ.get("WEB_PORTAL_AI_VECTOR_CHUNK", "1400"))
_VECTOR_TOPK = int(os.environ.get("WEB_PORTAL_AI_VECTOR_TOPK", "12"))
_VECTOR_MAX_ROWS = int(os.environ.get("WEB_PORTAL_AI_VECTOR_MAX_ROWS", "12000"))


def init_ai_vector_schema(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_vector_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            item_id INTEGER,
            seanse_date TEXT,
            seanse_freq TEXT,
            seanse_group TEXT,
            seanse_id TEXT,
            position_name TEXT NOT NULL,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            text_snippet TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            dim INTEGER NOT NULL,
            embedding BLOB NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_vec_pos ON ai_vector_chunks(position_name);")
    cur.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_vec_intercept ON ai_vector_chunks(source, item_id);"
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_vec_src_hash ON ai_vector_chunks(source, content_hash);")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_vector_index_state (
            ref_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_ai_vec_state_source ON ai_vector_index_state(source);")
    conn.commit()


def _hash_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8", errors="replace")).hexdigest()


def _fp_model_salt() -> str:
    return (
        (os.environ.get("WEB_PORTAL_AI_VECTOR_FP_VERSION") or "1").strip()
        + "|"
        + (os.environ.get("WEB_PORTAL_AI_EMBED_MODEL") or "nomic-embed-text").strip()
    )


def _intercept_source_fingerprint(updated_at: str, content: str) -> str:
    return _hash_text(f"{_fp_model_salt()}|i|{updated_at!s}|{content!s}")


def _seanse_line_for_embed(
    *,
    date_time: str,
    frequency: str,
    group_: str,
    sid: str,
    client_name: str | None = None,
    color_voice: str | None = None,
    time_seconds: str | None = None,
) -> str:
    line = (
        f"Сеанс связи | {date_time} | ID {sid} | {frequency} / {group_} | "
        f"позиция: {str(client_name or '').strip() or 'н/у'}"
    )
    if color_voice and str(color_voice).strip():
        line += f" | color_voice: {str(color_voice).strip()[:80]}"
    if time_seconds is not None and str(time_seconds).strip() != "":
        line += f" | t={time_seconds}"
    return line


def _seanse_ref_key(
    date_time: str, frequency: str, group_: str, sid: str
) -> str:
    parts = (date_time, frequency, group_, str(sid))
    b = "\x1e".join(p.replace("\x1e", " ") for p in parts)
    return f"seanse:{_hash_text(b)}"


def _seanse_source_fingerprint(
    date_time: str,
    frequency: str,
    group_: str,
    sid: str,
    client_name: str | None = None,
    color_voice: str | None = None,
    time_seconds: str | None = None,
) -> str:
    line = _seanse_line_for_embed(
        date_time=date_time,
        frequency=frequency,
        group_=group_,
        sid=sid,
        client_name=client_name,
        color_voice=color_voice,
        time_seconds=time_seconds,
    )
    return _hash_text(f"{_fp_model_salt()}|s|{line}")


def _state_get_fingerprint(conn: sqlite3.Connection, ref_key: str) -> str | None:
    r = conn.execute(
        "SELECT fingerprint FROM ai_vector_index_state WHERE ref_key = ?",
        (ref_key,),
    ).fetchone()
    if not r:
        return None
    return str(r[0] or "")


def _state_upsert(
    conn: sqlite3.Connection, ref_key: str, source: str, fingerprint: str
) -> None:
    conn.execute(
        """
        INSERT INTO ai_vector_index_state (ref_key, source, fingerprint, indexed_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(ref_key) DO UPDATE SET
            fingerprint = excluded.fingerprint,
            source = excluded.source,
            indexed_at = CURRENT_TIMESTAMP
        """,
        (ref_key, source, fingerprint),
    )


def _state_delete(conn: sqlite3.Connection, ref_key: str) -> None:
    conn.execute("DELETE FROM ai_vector_index_state WHERE ref_key = ?", (ref_key,))


def prune_stale_vector_data(conn: sqlite3.Connection) -> dict[str, int]:
    """
    Удаляет векторы и состояния для записей, которых уже нет в intercept_items / seanses.
    """
    cur = conn.cursor()
    cur.execute(
        """
        DELETE FROM ai_vector_chunks
        WHERE source = 'intercept' AND item_id IS NOT NULL
          AND item_id NOT IN (SELECT id FROM intercept_items)
        """
    )
    n_chunks_i = int(cur.rowcount or 0)
    cur.execute(
        """
        DELETE FROM ai_vector_index_state
        WHERE source = 'intercept'
          AND ref_key GLOB 'intercept:*'
          AND NOT EXISTS (
            SELECT 1 FROM intercept_items i
            WHERE i.id = CAST(substr(ref_key, 10) AS INTEGER)
          )
        """
    )
    n_st_i = int(cur.rowcount or 0)
    cur.execute(
        """
        DELETE FROM ai_vector_chunks
        WHERE source = 'seanse'
          AND NOT EXISTS (
            SELECT 1 FROM seanses s
            WHERE s.date_time = seanse_date
              AND s.frequency = seanse_freq
              AND s.group_ = seanse_group
              AND s.id = seanse_id
        )
        """
    )
    n_chunks_s = int(cur.rowcount or 0)
    srows = (
        conn.execute(
            "SELECT date_time, frequency, group_, id FROM seanses"
        ).fetchall()
        or []
    )
    want = {
        _seanse_ref_key(
            str(s["date_time"] or ""),
            str(s["frequency"] or ""),
            str(s["group_"] or ""),
            str(s["id"] or ""),
        )
        for s in srows
    }
    n_st_s = 0
    for (rk_t,) in conn.execute(
        "SELECT ref_key FROM ai_vector_index_state WHERE source = 'seanse'"
    ).fetchall() or []:
        rk = str(rk_t or "")
        if rk and rk.startswith("seanse:") and rk not in want:
            _state_delete(conn, rk)
            n_st_s += 1
    conn.commit()
    return {
        "chunks_intercept_pruned": n_chunks_i,
        "state_intercept_pruned": n_st_i,
        "chunks_seanse_pruned": n_chunks_s,
        "state_seanse_pruned": n_st_s,
    }


def _pack_embedding(vec: list[float]) -> bytes:
    arr = np.asarray(vec, dtype=np.float32)
    return arr.tobytes()


def _unpack_rows(rows: list[sqlite3.Row]) -> tuple[list[int], list[np.ndarray], list[str], list[str]]:
    ids: list[int] = []
    vecs: list[np.ndarray] = []
    snips: list[str] = []
    src: list[str] = []
    for r in rows:
        blob = r["embedding"]
        if not blob:
            continue
        v = np.frombuffer(blob, dtype=np.float32).astype(np.float64)
        n = float(np.linalg.norm(v))
        if n < 1e-12:
            continue
        ids.append(int(r["id"]))
        vecs.append(v / n)
        snips.append(str(r["text_snippet"] or "")[:800])
        src.append(f"{r['source']}:{r['id']}")
    return ids, vecs, snips, src


def _position_filter_sql(position_name: str) -> tuple[str, list[Any]]:
    if (position_name or "").strip() == "__all__":
        return "1=1", []
    p = (position_name or "").strip()
    return (
        "(position_name = ? OR TRIM(COALESCE(position_name, '')) = '')",
        [p],
    )


def search_planner_recall(
    conn: sqlite3.Connection,
    *,
    question: str,
    position_name: str,
    top_k: int | None = None,
) -> str:
    """
    Top-k фрагментов по смыслу; пустая строка если индекса нет или ошибка эмбеддера.
    """
    if os.environ.get("WEB_PORTAL_AI_VECTOR_RAG", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return ""
    k = top_k if top_k is not None else _VECTOR_TOPK
    qraw = (question or "").strip()
    if not qraw:
        return ""
    try:
        qv = np.asarray(embed_text(text=qraw[:8000]), dtype=np.float64)
    except (AIClientError, OSError, ValueError, TypeError):
        return ""
    qn = float(np.linalg.norm(qv))
    if qn < 1e-12:
        return ""
    qv = qv / qn
    d = int(qv.shape[0])
    wh, prm = _position_filter_sql(position_name)
    sql = f"""
        SELECT id, source, text_snippet, embedding
        FROM ai_vector_chunks
        WHERE dim = ? AND {wh}
        ORDER BY id DESC
        LIMIT ?
    """
    try:
        rows = conn.execute(
            sql,
            (d, *prm, _VECTOR_MAX_ROWS),
        ).fetchall()
    except sqlite3.Error:
        return ""
    if not rows:
        return ""
    _ids, vecs, snips, _tags = _unpack_rows(list(rows))
    if not vecs:
        return ""
    M = np.stack(vecs, axis=0)
    sim = M @ qv
    m = int(min(k, sim.shape[0]))
    if m < 1:
        return ""
    top_idx = np.argsort(-sim)[:m]
    lines: list[str] = []
    for j in top_idx:
        sc = float(sim[int(j)])
        label = f"[{sc:.3f}]"
        lines.append(f"- {label} {snips[int(j)]}")
    return "\n".join(lines)


def _delete_intercept_chunks(conn: sqlite3.Connection, item_id: int) -> None:
    conn.execute("DELETE FROM ai_vector_chunks WHERE source = 'intercept' AND item_id = ?", (int(item_id),))


def _delete_seanse_chunks(
    conn: sqlite3.Connection,
    *,
    d: str,
    f: str,
    g: str,
    iid: str,
) -> None:
    conn.execute(
        """
        DELETE FROM ai_vector_chunks
        WHERE source = 'seanse' AND seanse_date = ? AND seanse_freq = ? AND seanse_group = ? AND seanse_id = ?
        """,
        (d, f, g, str(iid)),
    )


def _insert_chunk(
    conn: sqlite3.Connection,
    *,
    source: str,
    item_id: int | None,
    seanse_date: str | None,
    seanse_freq: str | None,
    seanse_group: str | None,
    seanse_id: str | None,
    position_name: str,
    chunk_index: int,
    text_snippet: str,
    vec: list[float],
) -> None:
    dim = len(vec)
    conn.execute(
        """
        INSERT INTO ai_vector_chunks (
            source, item_id, seanse_date, seanse_freq, seanse_group, seanse_id,
            position_name, chunk_index, text_snippet, content_hash, dim, embedding, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            source,
            item_id,
            seanse_date,
            seanse_freq,
            seanse_group,
            seanse_id,
            (position_name or "").strip() or "",
            int(chunk_index),
            text_snippet[:12000],
            _hash_text(text_snippet),
            dim,
            _pack_embedding(vec),
        ),
    )


def _split_chunks(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    if len(t) <= _INTERCEPT_CHUNK:
        return [t]
    out: list[str] = []
    step = _INTERCEPT_CHUNK
    for i in range(0, len(t), step):
        out.append(t[i : i + step])
    return out or [t[:_INTERCEPT_CHUNK]]


def index_intercept_item(
    conn: sqlite3.Connection,
    item_id: int,
    *,
    do_commit: bool = True,
    skip_if_unchanged: bool = False,
) -> IndexOutcome:
    ref_key = f"intercept:{int(item_id)}"
    row = conn.execute(
        """
        SELECT i.id, i.content, i.unit_name, i.frequency, i.group_code, i.updated_at, s.position_name
        FROM intercept_items i
        JOIN intercept_sessions s ON s.id = i.session_id
        WHERE i.id = ?
        """,
        (int(item_id),),
    ).fetchone()
    if not row:
        return "failed"
    content = str(row["content"] or "").strip()
    if len(content) < 8:
        return "failed"
    uat = str(row["updated_at"] or "")
    fp = _intercept_source_fingerprint(uat, content)
    if skip_if_unchanged and _state_get_fingerprint(conn, ref_key) == fp:
        return "skipped"
    pos = str(row["position_name"] or "").strip()
    u = str(row["unit_name"] or "")
    fr = str(row["frequency"] or "")
    gr = str(row["group_code"] or "")
    header = f"Перехват (бланк) | смена привязана к позиции: {pos or 'н/у'} | {u} | {fr} / {gr}\n"
    chunks = _split_chunks(content)
    _delete_intercept_chunks(conn, int(item_id))
    inserted = 0
    for idx, ch in enumerate(chunks):
        body = header + (ch or "")
        try:
            vec = embed_text(text=body[:12000])
        except (AIClientError, OSError, ValueError, TypeError):
            continue
        _insert_chunk(
            conn,
            source="intercept",
            item_id=int(item_id),
            seanse_date=None,
            seanse_freq=None,
            seanse_group=None,
            seanse_id=None,
            position_name=pos,
            chunk_index=idx,
            text_snippet=body[:10000],
            vec=vec,
        )
        inserted += 1
    if inserted == 0:
        _state_delete(conn, ref_key)
        if do_commit:
            conn.commit()
        return "failed"
    _state_upsert(conn, ref_key, "intercept", fp)
    if do_commit:
        conn.commit()
    return "indexed"


def index_seanse_row(
    conn: sqlite3.Connection,
    *,
    date_time: str,
    frequency: str,
    group_: str,
    sid: str,
    client_name: str | None = None,
    color_voice: str | None = None,
    time_seconds: str | None = None,
    do_commit: bool = True,
    skip_if_unchanged: bool = False,
) -> IndexOutcome:
    line = _seanse_line_for_embed(
        date_time=date_time,
        frequency=frequency,
        group_=group_,
        sid=sid,
        client_name=client_name,
        color_voice=color_voice,
        time_seconds=time_seconds,
    )
    if len(line) < 10:
        return "failed"
    ref_key = _seanse_ref_key(
        str(date_time or ""),
        str(frequency or ""),
        str(group_ or ""),
        str(sid or ""),
    )
    fp = _seanse_source_fingerprint(
        str(date_time or ""),
        str(frequency or ""),
        str(group_ or ""),
        str(sid or ""),
        client_name=client_name,
        color_voice=color_voice,
        time_seconds=time_seconds,
    )
    if skip_if_unchanged and _state_get_fingerprint(conn, ref_key) == fp:
        return "skipped"
    pos = str(client_name or "").strip()
    try:
        vec = embed_text(text=line[:10000])
    except (AIClientError, OSError, ValueError, TypeError):
        return "failed"
    _delete_seanse_chunks(conn, d=date_time, f=frequency, g=group_, iid=sid)
    _insert_chunk(
        conn,
        source="seanse",
        item_id=None,
        seanse_date=date_time,
        seanse_freq=frequency,
        seanse_group=group_,
        seanse_id=str(sid),
        position_name=pos,
        chunk_index=0,
        text_snippet=line,
        vec=vec,
    )
    _state_upsert(conn, ref_key, "seanse", fp)
    if do_commit:
        conn.commit()
    return "indexed"


def reindex_intercepts(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    delay_sec: float = 0.0,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    q = "SELECT id FROM intercept_items WHERE length(trim(content)) > 8 ORDER BY id"
    params: tuple = ()
    if limit is not None:
        q += " LIMIT ?"
        params = (int(limit),)
    rows = conn.execute(q, params).fetchall()
    total = len(rows)
    ok = 0
    for i, r in enumerate(rows):
        if (
            index_intercept_item(
                conn, int(r["id"]), do_commit=False, skip_if_unchanged=False
            )
            == "indexed"
        ):
            ok += 1
        if on_progress:
            on_progress(i + 1, total)
        if delay_sec > 0:
            time.sleep(delay_sec)
    try:
        conn.commit()
    except sqlite3.Error:
        pass
    return ok, total


def reindex_seanses(
    conn: sqlite3.Connection,
    *,
    limit: int | None = None,
    delay_sec: float = 0.0,
    on_progress: Callable[[int, int], None] | None = None,
) -> tuple[int, int]:
    q = "SELECT date_time, frequency, group_, id, client_name, color_voice, time_seconds FROM seanses ORDER BY date_time DESC"
    params: tuple = ()
    if limit is not None:
        q += " LIMIT ?"
        params = (int(limit),)
    rows = conn.execute(q, params).fetchall()
    total = len(rows)
    ok = 0
    for i, r in enumerate(rows):
        if (
            index_seanse_row(
                conn,
                date_time=str(r["date_time"] or ""),
                frequency=str(r["frequency"] or ""),
                group_=str(r["group_"] or ""),
                sid=str(r["id"] or ""),
                client_name=(str(r["client_name"]) if r["client_name"] is not None else None),
                color_voice=(str(r["color_voice"]) if r["color_voice"] is not None else None),
                time_seconds=(str(r["time_seconds"]) if r["time_seconds"] is not None else None),
                do_commit=False,
                skip_if_unchanged=False,
            )
            == "indexed"
        ):
            ok += 1
        if on_progress:
            on_progress(i + 1, total)
        if delay_sec > 0:
            time.sleep(delay_sec)
    try:
        conn.commit()
    except sqlite3.Error:
        pass
    return ok, total


def reindex_all(
    conn: sqlite3.Connection,
    *,
    intercept_limit: int | None = None,
    seanses_limit: int | None = None,
) -> dict[str, Any]:
    init_ai_vector_schema(conn)
    a, at = reindex_intercepts(conn, limit=intercept_limit, delay_sec=0.0)
    b, bt = reindex_seanses(conn, limit=seanses_limit, delay_sec=0.0)
    return {
        "intercept_indexed": a,
        "intercept_total": at,
        "seanse_indexed": b,
        "seanse_total": bt,
    }


def sync_intercepts_incremental(
    conn: sqlite3.Connection,
    *,
    max_rows: int = 400,
    delay_sec: float = 0.0,
) -> dict[str, int]:
    init_ai_vector_schema(conn)
    rows = conn.execute(
        """
        SELECT id FROM intercept_items
        WHERE length(trim(content)) > 8
        ORDER BY COALESCE(updated_at, '') DESC, id DESC
        LIMIT ?
        """,
        (int(max(1, max_rows)),),
    ).fetchall()
    idx = sk = fl = 0
    for r in rows or []:
        o = index_intercept_item(
            conn,
            int(r["id"]),
            do_commit=False,
            skip_if_unchanged=True,
        )
        if o == "indexed":
            idx += 1
        elif o == "skipped":
            sk += 1
        else:
            fl += 1
        if delay_sec > 0:
            time.sleep(delay_sec)
    try:
        conn.commit()
    except sqlite3.Error:
        pass
    return {"indexed": idx, "skipped": sk, "failed": fl, "candidates": len(rows or [])}


def sync_seanses_incremental(
    conn: sqlite3.Connection,
    *,
    max_rows: int = 800,
    delay_sec: float = 0.0,
) -> dict[str, int]:
    init_ai_vector_schema(conn)
    rows = conn.execute(
        """
        SELECT date_time, frequency, group_, id, client_name, color_voice, time_seconds
        FROM seanses
        ORDER BY date_time DESC
        LIMIT ?
        """,
        (int(max(1, max_rows)),),
    ).fetchall()
    idx = sk = fl = 0
    for r in rows or []:
        o = index_seanse_row(
            conn,
            date_time=str(r["date_time"] or ""),
            frequency=str(r["frequency"] or ""),
            group_=str(r["group_"] or ""),
            sid=str(r["id"] or ""),
            client_name=(str(r["client_name"]) if r["client_name"] is not None else None),
            color_voice=(str(r["color_voice"]) if r["color_voice"] is not None else None),
            time_seconds=(str(r["time_seconds"]) if r["time_seconds"] is not None else None),
            do_commit=False,
            skip_if_unchanged=True,
        )
        if o == "indexed":
            idx += 1
        elif o == "skipped":
            sk += 1
        else:
            fl += 1
        if delay_sec > 0:
            time.sleep(delay_sec)
    try:
        conn.commit()
    except sqlite3.Error:
        pass
    return {"indexed": idx, "skipped": sk, "failed": fl, "candidates": len(rows or [])}


def sync_vectors_incremental(
    conn: sqlite3.Connection,
    *,
    max_intercepts: int = 400,
    max_seanses: int = 800,
    prune: bool = True,
) -> dict[str, Any]:
    a = sync_intercepts_incremental(conn, max_rows=max_intercepts)
    b = sync_seanses_incremental(conn, max_rows=max_seanses)
    pr: dict[str, int] = {}
    if prune:
        pr = prune_stale_vector_data(conn)
    return {"intercepts": a, "seanses": b, "prune": pr}
