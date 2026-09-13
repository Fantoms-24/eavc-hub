"""Фильтры и SQL для /api/analysis/keys/check (без Flask)."""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.application.analysis.graph_payload import (
    normalize_analysis_freq_str,
    normalize_analysis_group_key,
)
from web_portal.lib.db import get_sync_meta, seanses_union_source_sql


def parse_analysis_keys_check_range(
    start_s: str,
    end_s: str,
) -> tuple[datetime, datetime] | None:
    start_s = str(start_s or "").strip()
    end_s = str(end_s or "").strip()
    if not start_s and not end_s:
        return None
    if not start_s or not end_s:
        raise AnalysisUseCaseHTTP(
            400, {"ok": False, "error": "start/end обязательны вместе"}
        )
    try:
        start = datetime.fromisoformat(start_s)
        end = datetime.fromisoformat(end_s)
    except Exception as exc:
        raise AnalysisUseCaseHTTP(
            400,
            {"ok": False, "error": "Неверный формат start/end (ISO)"},
        ) from exc
    if end <= start:
        raise AnalysisUseCaseHTTP(
            400, {"ok": False, "error": "end должен быть > start"}
        )
    return start, end


def build_analysis_keys_sql_filter(
    *,
    new_since: str = "",
    start: datetime | None = None,
    end: datetime | None = None,
) -> tuple[str, list[Any]]:
    params: list[Any] = []
    clauses: list[str] = []
    new_since = str(new_since or "").strip()
    if new_since:
        try:
            ns = datetime.fromisoformat(new_since.replace(" ", "T"))
            params.append(ns.strftime("%Y-%m-%d %H:%M:%S"))
            clauses.append("created_at >= ?")
        except Exception:
            pass
    if start is not None and end is not None:
        params.extend([start.date().isoformat(), end.date().isoformat()])
        clauses.append("substr(added_date, 1, 10) BETWEEN ? AND ?")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


def _crypto_required_files(folder: Path) -> dict[str, Path]:
    return {
        "dmr_enhanced_key_groups.xml": folder / "dmr_enhanced_key_groups.xml",
        "dmr_enhanced_key_privates.xml": folder / "dmr_enhanced_key_privates.xml",
        "dmr_enhanced_keys.xml": folder / "dmr_enhanced_keys.xml",
    }


def _crypto_folder_status(folder_raw: str) -> tuple[str, dict[str, bool]]:
    folder = Path(str(folder_raw or "").strip()) if folder_raw else None
    if not folder or not str(folder):
        return ("Путь не задан.", {})
    if not folder.exists() or not folder.is_dir():
        return ("Папка не найдена.", {})
    files = _crypto_required_files(folder)
    status = {name: p.is_file() for name, p in files.items()}
    if all(status.values()):
        return ("Все файлы найдены.", status)
    missing = [k for k, ok in status.items() if not ok]
    return (f"Не найдены файлы: {', '.join(missing)}", status)


def _parse_crypto_groups(path: Path) -> dict[str, list[str]]:
    tree = ET.parse(path)
    root = tree.getroot()
    out: dict[str, list[str]] = {}
    for group in root.findall("group"):
        gid = str(group.findtext("id") or "").strip()
        if not gid:
            continue
        keys = [
            str(k.text or "").strip()
            for k in group.findall("key_uid")
            if str(k.text or "").strip()
        ]
        if keys:
            out[gid] = keys
    return out


def _parse_crypto_keys(path: Path) -> dict[str, dict[str, str]]:
    tree = ET.parse(path)
    root = tree.getroot()
    out: dict[str, dict[str, str]] = {}
    for k in root.findall("key"):
        uid = str(k.findtext("key_uid") or "").strip()
        if not uid:
            continue
        out[uid] = {
            "key_id": str(k.findtext("key_id") or "").strip(),
            "value": str(k.findtext("value") or "").strip(),
            "alg": str(k.attrib.get("Alg") or "").strip(),
            "date_time": str(k.findtext("date_time") or "").strip(),
        }
    return out


def load_crypto_group_key_map(
    main_conn: sqlite3.Connection,
) -> tuple[bool, dict[tuple[str, str], str]]:
    crypto_group_key_map: dict[tuple[str, str], str] = {}
    try:
        folder_path = get_sync_meta(main_conn, "crypto_folder_path") or ""
        _status_text, files = _crypto_folder_status(folder_path)
        if files and all(files.values()):
            folder = Path(str(folder_path))
            files_map = _crypto_required_files(folder)
            groups_raw = _parse_crypto_groups(files_map["dmr_enhanced_key_groups.xml"])
            keys_raw = _parse_crypto_keys(files_map["dmr_enhanced_keys.xml"])
            for gid, key_uids in (groups_raw or {}).items():
                gid_norm = normalize_analysis_group_key(gid) or str(gid).strip()
                if not gid_norm:
                    continue
                for uid in key_uids or []:
                    uid = str(uid).strip()
                    if not uid:
                        continue
                    meta = (keys_raw or {}).get(uid, {})
                    val = str(meta.get("value") or "").strip().upper()
                    if val:
                        crypto_group_key_map[(gid_norm, val)] = uid
            return bool(crypto_group_key_map), crypto_group_key_map
    except Exception:
        pass
    return False, crypto_group_key_map


def assemble_analysis_keys_check_payload(
    main_conn: sqlite3.Connection,
    seans_conn: sqlite3.Connection,
    *,
    position_filter: str | None,
    match_id: bool,
    debug: bool,
    all_keys: bool,
    start: datetime | None,
    end: datetime | None,
    new_since: str,
) -> dict[str, Any]:
    seans_src = seanses_union_source_sql(seans_conn)
    params: list[object] = []
    where = "1=1"
    if position_filter:
        where += " AND client_name=?"
        params.append(position_filter)
    rows = seans_conn.execute(
        f"""
        SELECT frequency, group_, id, COUNT(*) as cnt
        FROM ({seans_src}) s
        WHERE {where}
        GROUP BY frequency, group_, id
        """,
        tuple(params),
    ).fetchall()
    last_seen_rows = seans_conn.execute(
        f"""
        SELECT frequency, group_, aes_key, MAX(date_time) as last_dt
        FROM ({seans_src}) s
        WHERE {where}
        GROUP BY frequency, group_, aes_key
        """,
        tuple(params),
    ).fetchall()

    seans_map: dict[tuple[str, str] | tuple[str, str, str], int] = {}
    last_seen_map: dict[tuple[str, str, str], str] = {}
    for r in rows:
        freq = str(r[0] or "").strip()
        grp_raw = str(r[1] or "").strip()
        aes_id = str(r[2] or "").strip()
        freq_norm = normalize_analysis_freq_str(freq)
        grp = normalize_analysis_group_key(grp_raw)
        if match_id:
            key: tuple[str, str] | tuple[str, str, str] = (freq_norm, grp, aes_id)
        else:
            key = (freq_norm, grp)
        seans_map[key] = seans_map.get(key, 0) + int(r[3] or 0)
    for r in last_seen_rows:
        freq = str(r[0] or "").strip()
        grp_raw = str(r[1] or "").strip()
        aes_key = str(r[2] or "").strip()
        freq_norm = normalize_analysis_freq_str(freq)
        grp = normalize_analysis_group_key(grp_raw)
        dt = str(r[3] or "").strip()
        if freq_norm and grp and aes_key and dt:
            last_seen_map[(freq_norm, grp, aes_key)] = dt

    debug_data: dict[str, Any] | None = None
    keys_where, keys_params = build_analysis_keys_sql_filter(
        new_since=new_since,
        start=start,
        end=end,
    )
    key_rows = main_conn.execute(
        f"""
        SELECT frequency, frequency_norm, group_, aes_id, aes_key, unit_name, added_date, created_at
        FROM analysis_keys
        {keys_where}
        """,
        tuple(keys_params),
    ).fetchall()
    crypto_available, crypto_group_key_map = load_crypto_group_key_map(main_conn)

    out: list[dict[str, object]] = []
    if debug:
        debug_limit = 30
        seans_keys_sample = list(seans_map.keys())[:debug_limit]
        debug_data = {
            "match_id": match_id,
            "position_filter": position_filter or "",
            "seanses_rows": len(rows),
            "seanses_keys_sample": seans_keys_sample,
            "keys_rows": len(key_rows),
            "keys_sample": [],
        }
    for r in key_rows:
        freq = str(r[0] or "").strip()
        freq_norm = str(r[1] or "").strip()
        grp_raw = str(r[2] or "").strip()
        aes_id = str(r[3] or "").strip()
        grp = normalize_analysis_group_key(grp_raw)
        if match_id:
            k: tuple[str, str] | tuple[str, str, str] = (freq_norm, grp, aes_id)
        else:
            k = (freq_norm, grp)
        if debug and debug_data is not None and len(debug_data["keys_sample"]) < 30:
            debug_data["keys_sample"].append(
                {
                    "frequency": freq,
                    "frequency_norm": freq_norm,
                    "group": grp,
                    "aes_id": aes_id,
                    "key_tuple": k,
                    "matched": k in seans_map,
                }
            )
        if not all_keys and k not in seans_map:
            continue
        last_seen = last_seen_map.get((freq_norm, grp, aes_id), "")
        crypto_present: bool | None = None
        crypto_key_uid = ""
        if crypto_available:
            key_val_norm = str(r[4] or "").strip().upper()
            crypto_key_uid = crypto_group_key_map.get((grp, key_val_norm), "")
            crypto_present = bool(crypto_key_uid)
        matched = k in seans_map
        out.append(
            {
                "frequency": freq,
                "group": grp,
                "aes_id": aes_id,
                "aes_key": str(r[4] or "").strip(),
                "unit_name": str(r[5] or "").strip(),
                "added_date": str(r[6] or "").strip(),
                "created_at": str(r[7] or "").strip(),
                "last_seen": last_seen,
                "match_count": int(seans_map.get(k, 0)),
                "session_matched": matched,
                "id_seen": bool(last_seen),
                "crypto_present": crypto_present,
                "crypto_key_uid": crypto_key_uid,
            }
        )

    matched_count = sum(1 for row in out if row.get("session_matched"))
    if all_keys:
        info = f"Всего ключей: {len(out)}, с сеансами: {matched_count}"
    else:
        info = f"Найдено совпадений: {len(out)}"

    return {
        "ok": True,
        "rows": out,
        "info": info,
        "all_keys": all_keys,
        "debug": debug_data,
        "crypto_available": crypto_available,
    }
