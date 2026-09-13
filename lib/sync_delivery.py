"""Hub delivery receipts live separately from the read-only source databases."""

from contextlib import contextmanager
import hashlib
from pathlib import Path
import sqlite3

from web_portal.lib.db.sync import (
    _SYNC_OUTBOX_PRIORITY_KINDS,
    _sync_outbox_priority_order_sql,
)


def delivery_state_path(source: Path) -> Path:
    # No .sqlite suffix: this internal file must not appear in the DB picker.
    return source.resolve().with_name(source.name + ".sync-state")


@contextmanager
def read_source(source: Path):
    """Never initialize schemas or acquire a source writer lock in a sender."""
    conn = sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.1)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def _write_state(source: Path):
    conn = sqlite3.connect(str(delivery_state_path(source)), timeout=0.2)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE IF NOT EXISTS delivery_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("""CREATE TABLE IF NOT EXISTS delivery_receipts (
            outbox_id INTEGER NOT NULL, fingerprint TEXT NOT NULL,
            sent_at TEXT, attempts INTEGER NOT NULL DEFAULT 0,
            last_error TEXT NOT NULL DEFAULT '',
            PRIMARY KEY(outbox_id, fingerprint))""")
        yield conn
        conn.commit()
    finally:
        conn.close()


def load_cursor(source: Path, key: str) -> str:
    state = delivery_state_path(source)
    if state.is_file():
        with read_source(state) as conn:
            row = conn.execute("SELECT value FROM delivery_meta WHERE key=?", (key,)).fetchone()
            if row is not None:
                return str(row[0])
    # Keep the previous delivery position without migrating or writing source.
    with read_source(source) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='sync_meta'").fetchone():
            return ""
        row = conn.execute("SELECT value FROM sync_meta WHERE key=?", (key,)).fetchone()
        return str(row[0] or "") if row else ""


def save_cursors(source: Path, values: dict[str, str]) -> None:
    with _write_state(source) as conn:
        conn.executemany(
            "INSERT INTO delivery_meta VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            list(values.items()),
        )


def session_source() -> Path:
    """Preserve the empty-separate-DB fallback using short read-only probes."""
    from web_portal.lib import seans_db
    from web_portal.config import DEFAULT_DB_NAME

    main = seans_db.db_path(DEFAULT_DB_NAME)
    if not seans_db.use_separate_seans_db():
        return main
    separate = seans_db.seans_db_path()

    def has_rows(path: Path) -> bool:
        if not path.is_file():
            return False
        with read_source(path) as conn:
            for table in ("seanses", "seanses_archive"):
                if conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
                    if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
                        return True
        return False

    if has_rows(separate):
        return separate
    return main if has_rows(main) else separate


def _event_fingerprint(kind: str, payload: str) -> str:
    return hashlib.sha256((kind + "\0" + payload).encode("utf-8")).hexdigest()


def pending_delivery(source: Path, *, limit: int = 200, priority_only: bool = False) -> list[dict]:
    state = delivery_state_path(source)
    with read_source(source) as conn:
        conn.create_function("delivery_hash", 2, _event_fingerprint, deterministic=True)
        join = ""
        unsent = ""
        attempts = "o.attempts"
        last_error = "o.last_error"
        if state.is_file():
            conn.execute("ATTACH DATABASE ? AS delivery", (state.as_uri() + "?mode=ro",))
            join = """LEFT JOIN delivery.delivery_receipts r ON r.outbox_id=o.id
                      AND r.fingerprint=delivery_hash(o.kind, o.payload_json)"""
            unsent = "AND r.sent_at IS NULL"
            attempts = "o.attempts + COALESCE(r.attempts, 0)"
            last_error = "COALESCE(r.last_error, o.last_error)"
        priority = ""
        params = []
        if priority_only:
            priority = "AND o.kind IN (" + ",".join("?" for _ in _SYNC_OUTBOX_PRIORITY_KINDS) + ")"
            params.extend(_SYNC_OUTBOX_PRIORITY_KINDS)
        params.append(max(1, min(int(limit), 1000)))
        rows = conn.execute(
            f"""SELECT o.id, o.kind, o.payload_json, o.created_at,
                       {attempts} AS attempts, {last_error} AS last_error
                FROM sync_outbox o {join}
                WHERE o.sent_at IS NULL {unsent} {priority}
                ORDER BY {_sync_outbox_priority_order_sql()}, o.id LIMIT ?""",
            params,
        ).fetchall()
        return [dict(row) for row in rows]


def record_delivery(source: Path, batch: list[dict], *, error: str | None = None) -> None:
    with _write_state(source) as conn:
        conn.executemany(
            """INSERT INTO delivery_receipts
               (outbox_id, fingerprint, sent_at, attempts, last_error)
               VALUES (?, ?, CASE WHEN ? IS NULL THEN CURRENT_TIMESTAMP END, ?, ?)
               ON CONFLICT(outbox_id, fingerprint) DO UPDATE SET
                 sent_at=COALESCE(delivery_receipts.sent_at, excluded.sent_at),
                 attempts=delivery_receipts.attempts + excluded.attempts,
                 last_error=excluded.last_error""",
            [(int(row["id"]), _event_fingerprint(row["kind"], row["payload_json"]),
              error, int(error is not None), str(error or "")[:500]) for row in batch],
        )
