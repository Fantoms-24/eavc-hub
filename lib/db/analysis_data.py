"""Analysis assignments (физически из ``_impl``)."""
from __future__ import annotations

import sqlite3
from typing import Any

from web_portal.lib.db.connection import init_db
from web_portal.lib.db.sql_util import _in_clause



def _parse_duty_codes(raw: str) -> list[str]:
    codes: list[str] = []
    for part in str(raw or "").split(","):
        code = part.strip()
        if not code:
            continue
        if code in codes:
            continue
        codes.append(code)
    return codes


def _format_duty_codes(codes: list[str]) -> str:
    return ",".join([str(c).strip() for c in codes if str(c).strip()])


def get_analysis_assignments(
    conn: sqlite3.Connection, *, position_name: str, frequency: str, group_code: str
) -> dict[str, object]:
    init_db(conn)
    rows = conn.execute(
        """
        SELECT role_type, callsign_code
        FROM analysis_assignments
        WHERE position_name=? AND frequency=? AND group_code=?
        """,
        (str(position_name), str(frequency), str(group_code)),
    ).fetchall()
    out: dict[str, object] = {}
    for r in rows:
        role = str(r["role_type"])
        code = str(r["callsign_code"])
        if role == "duty":
            out[role] = _parse_duty_codes(code)
        else:
            out[role] = code
    return out


def set_analysis_assignment(
    conn: sqlite3.Connection,
    *,
    position_name: str,
    frequency: str,
    group_code: str,
    role_type: str,
    callsign_code: str,
    mode: str | None = None,
) -> None:
    init_db(conn)
    role_type = str(role_type or "").strip().lower()
    if role_type not in {"duty", "battalion", "company"}:
        raise ValueError("role_type должен быть duty (legacy: battalion/company)")
    callsign_code = str(callsign_code or "").strip()
    mode = str(mode or "").strip().lower() or "set"

    if role_type == "duty":
        row = conn.execute(
            """
            SELECT callsign_code
            FROM analysis_assignments
            WHERE position_name=? AND frequency=? AND group_code=? AND role_type=?
            """,
            (str(position_name), str(frequency), str(group_code), role_type),
        ).fetchone()
        existing = _parse_duty_codes(str(row["callsign_code"]) if row else "")

        # если пусто — снимаем назначение (или очищаем список)
        if not callsign_code:
            existing = []
        elif mode == "set":
            existing = [callsign_code]
        elif mode == "add":
            if callsign_code not in existing:
                existing.append(callsign_code)
        elif mode == "remove":
            existing = [c for c in existing if c != callsign_code]
        elif mode == "toggle":
            if callsign_code in existing:
                existing = [c for c in existing if c != callsign_code]
            else:
                existing.append(callsign_code)

        if not existing:
            conn.execute(
                """
                DELETE FROM analysis_assignments
                WHERE position_name=? AND frequency=? AND group_code=? AND role_type=?
                """,
                (str(position_name), str(frequency), str(group_code), role_type),
            )
            conn.commit()
            return

        duty_blob = _format_duty_codes(existing)
        conn.execute(
            """
            INSERT INTO analysis_assignments (position_name, frequency, group_code, role_type, callsign_code)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(position_name, frequency, group_code, role_type)
            DO UPDATE SET callsign_code=excluded.callsign_code, updated_at=CURRENT_TIMESTAMP
            """,
            (
                str(position_name),
                str(frequency),
                str(group_code),
                role_type,
                duty_blob,
            ),
        )
        conn.commit()
        return

    # одиночные назначения (legacy)
    if not callsign_code:
        conn.execute(
            """
            DELETE FROM analysis_assignments
            WHERE position_name=? AND frequency=? AND group_code=? AND role_type=?
            """,
            (str(position_name), str(frequency), str(group_code), role_type),
        )
        conn.commit()
        return
    conn.execute(
        """
        INSERT INTO analysis_assignments (position_name, frequency, group_code, role_type, callsign_code)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(position_name, frequency, group_code, role_type)
        DO UPDATE SET callsign_code=excluded.callsign_code, updated_at=CURRENT_TIMESTAMP
        """,
        (
            str(position_name),
            str(frequency),
            str(group_code),
            role_type,
            callsign_code,
        ),
    )
    conn.commit()


def list_analysis_assignments_since(
    conn: sqlite3.Connection, *, since_ts: str, position_names: list[str] | None = None
) -> list[dict[str, Any]]:
    init_db(conn)
    since = str(since_ts or "").strip() or "1970-01-01 00:00:00"
    where_pos, params_pos = _in_clause("position_name", position_names or [])
    rows = conn.execute(
        """
        SELECT position_name, frequency, group_code, role_type, callsign_code, updated_at
        FROM analysis_assignments
        WHERE COALESCE(updated_at,'') >= ?{where_pos}
        ORDER BY updated_at ASC
        """.format(where_pos=where_pos),
        [since] + params_pos,
    ).fetchall()
    return [
        {
            "position_name": str(r["position_name"] or ""),
            "frequency": str(r["frequency"] or ""),
            "group_code": str(r["group_code"] or ""),
            "role_type": str(r["role_type"] or ""),
            "callsign_code": str(r["callsign_code"] or ""),
            "updated_at": str(r["updated_at"] or ""),
        }
        for r in rows
    ]


__all__ = [
    "get_analysis_assignments",
    "set_analysis_assignment",
    "list_analysis_assignments_since",
]
