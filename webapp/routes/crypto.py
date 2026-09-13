"""Криптообеспечение (/crypto, /api/crypto/*), извлечено из app.py дословно.

Хелперы подняты на уровень модуля: часть из них (_crypto_folder_status,
_crypto_required_files, _normalize_group_key, _parse_crypto_groups,
_parse_crypto_keys) используется также analysis-маршрутами app.py.
"""

from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from flask import jsonify, request
from flask_login import current_user, login_required

from web_portal.config import DEFAULT_DB_NAME, db_path
from web_portal.lib.db import (
    connect,
    ensure_db,
    get_sync_meta,
    seanses_union_source_sql,
    set_sync_meta,
)
from web_portal.lib.flask_db import get_request_main_db, get_request_seans_db
from web_portal.positions import get_selected_position, require_position_role
from web_portal.webapp.context import AppContext

_log = logging.getLogger("web_portal.webapp.routes.crypto")


def _normalize_group_key(g: str) -> str:
    import re

    s = str(g or "").strip()
    # normalize group like "G12345" -> "12345"
    digits = re.findall(r"\d+", s)
    if not digits:
        return s
    joined = "".join(digits)
    try:
        return str(int(joined))
    except Exception:
        return joined.lstrip("0") or "0"

def _normalize_key_id(v: str) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    if s.isdigit():
        try:
            return str(int(s))
        except Exception:
            return s.lstrip("0") or "0"
    return s

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

def _parse_crypto_callsigns(path: Path) -> dict[str, list[str]]:
    tree = ET.parse(path)
    root = tree.getroot()
    out: dict[str, list[str]] = {}
    for cs in root.findall("callsign"):
        cid = str(cs.findtext("id") or "").strip()
        if not cid:
            continue
        keys = [
            str(k.text or "").strip()
            for k in cs.findall("key_uid")
            if str(k.text or "").strip()
        ]
        if keys:
            out[cid] = keys
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

def _load_xml_tree(path: Path) -> tuple[ET.ElementTree, ET.Element]:
    tree = ET.parse(path)
    return tree, tree.getroot()

def _write_xml_tree(path: Path, tree: ET.ElementTree) -> None:
    try:
        ET.indent(tree, space="    ", level=0)
    except Exception:
        _log.debug("_write_xml_tree: suppressed error", exc_info=True)
    tree.write(path, encoding="utf-8", xml_declaration=True)

def _remove_key_uid_from_groups(root: ET.Element, key_uid: str) -> int:
    uid = str(key_uid or "").strip()
    if not uid:
        return 0
    removed = 0
    for group in root.findall("group"):
        for kid in list(group.findall("key_uid")):
            if str(kid.text or "").strip() == uid:
                group.remove(kid)
                removed += 1
    return removed

def _remove_key_uid_from_callsigns(root: ET.Element, key_uid: str) -> int:
    uid = str(key_uid or "").strip()
    if not uid:
        return 0
    removed = 0
    for cs in root.findall("callsign"):
        for kid in list(cs.findall("key_uid")):
            if str(kid.text or "").strip() == uid:
                cs.remove(kid)
                removed += 1
    return removed

def _reindex_key_uids(
    keys_root: ET.Element, groups_root: ET.Element, callsigns_root: ET.Element
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    keys = keys_root.findall("key")
    next_id = 1
    for k in keys:
        uid_node = k.find("key_uid")
        if uid_node is None:
            continue
        old = str(uid_node.text or "").strip()
        new = str(next_id)
        next_id += 1
        if old:
            mapping[old] = new
        uid_node.text = new
    # update references
    for root in (groups_root, callsigns_root):
        for node in root.findall(".//key_uid"):
            old = str(node.text or "").strip()
            if old in mapping:
                node.text = mapping[old]
    return mapping

def _cleanup_empty_groups(root: ET.Element) -> int:
    removed = 0
    for group in list(root.findall("group")):
        if not list(group.findall("key_uid")):
            root.remove(group)
            removed += 1
    return removed

def _cleanup_empty_callsigns(root: ET.Element) -> int:
    removed = 0
    for cs in list(root.findall("callsign")):
        if not list(cs.findall("key_uid")):
            root.remove(cs)
            removed += 1
    return removed

def _xml_find_group(root: ET.Element, group_id: str) -> ET.Element | None:
    gid = str(group_id or "").strip()
    if not gid:
        return None
    for group in root.findall("group"):
        gid_node = group.find("id")
        if gid_node is not None and str(gid_node.text or "").strip() == gid:
            return group
    return None

def _xml_add_key_uid(container: ET.Element, key_uid: str) -> bool:
    uid = str(key_uid or "").strip()
    if not uid:
        return False
    for kid in container.findall("key_uid"):
        if str(kid.text or "").strip() == uid:
            return False
    new_node = ET.Element("key_uid")
    new_node.text = uid
    comment = container.find("comment")
    if comment is not None:
        idx = list(container).index(comment)
        container.insert(idx, new_node)
    else:
        container.append(new_node)
    return True

def _xml_create_group(root: ET.Element, group_id: str) -> ET.Element:
    group = ET.Element("group")
    gid = ET.SubElement(group, "id")
    gid.text = str(group_id or "").strip()
    comment = ET.SubElement(group, "comment")
    comment.text = ""
    root.append(group)
    return group

def _sort_groups_by_id(root: ET.Element) -> None:
    """Sort <group> children by numeric <id> (ascending)."""
    groups = list(root.findall("group"))
    if not groups:
        return

    def key_fn(g: ET.Element) -> tuple[int, int | str]:
        id_el = g.find("id")
        if id_el is None or id_el.text is None:
            return (0, 0)
        t = str(id_el.text or "").strip()
        try:
            return (0, int(t))
        except ValueError:
            return (1, t)

    groups.sort(key=key_fn)
    for g in groups:
        root.remove(g)
    for g in groups:
        root.append(g)

def register_crypto_routes(app, ctx: AppContext):
    """Регистрирует маршруты криптообеспечения через AppContext. Код перенесён дословно."""

    @app.get("/api/crypto/config")
    @login_required
    def api_crypto_config():
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            folder_path = get_sync_meta(conn, "crypto_folder_path") or ""
        finally:
            conn.close()
        status_text, files = _crypto_folder_status(folder_path)
        return jsonify(
            {
                "ok": True,
                "folder_path": folder_path,
                "folder_status": status_text,
                "files": files,
            }
        )

    @app.post("/api/crypto/config")
    @login_required
    def api_crypto_config_save():
        if not (
            current_user.has_perm("import_folder")
            or current_user.has_perm("manage_users")
        ):
            return jsonify({"ok": False, "error": "Нет прав"}), 403
        data = request.get_json(silent=True) or {}
        folder_path = str(data.get("folder_path") or "").strip()
        status_text, files = _crypto_folder_status(folder_path)
        if not folder_path:
            return jsonify({"ok": False, "error": "Путь не задан"}), 400
        if not files or not all(files.values()):
            return jsonify({"ok": False, "error": status_text}), 400
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            set_sync_meta(conn, "crypto_folder_path", folder_path)
        finally:
            conn.close()
        return jsonify(
            {
                "ok": True,
                "folder_path": folder_path,
                "folder_status": status_text,
            }
        )

    @app.get("/api/crypto/check")
    @login_required
    def api_crypto_check():
        pos = get_selected_position()
        position_filter = None if (current_user.role == "admin" and not pos) else pos
        if not position_filter and current_user.role != "admin":
            return jsonify({"ok": False, "error": "Не выбрана позиция"}), 400
        if position_filter and not require_position_role(position_filter, "view"):
            return jsonify({"ok": False, "error": "Нет прав"}), 403

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        main_conn = get_request_main_db()
        folder_path = get_sync_meta(main_conn, "crypto_folder_path") or ""
        status_text, files = _crypto_folder_status(folder_path)
        if not folder_path or not files or not all(files.values()):
            return jsonify({"ok": False, "error": status_text}), 400

        start_s = str(request.args.get("start") or "").strip()
        end_s = str(request.args.get("end") or "").strip()
        days = int(str(request.args.get("days") or "1").strip() or 1)
        if start_s and end_s:
            try:
                start = datetime.fromisoformat(start_s)
                end = datetime.fromisoformat(end_s)
            except Exception:
                return (
                    jsonify({"ok": False, "error": "Неверный формат start/end (ISO)"}),
                    400,
                )
        else:
            end = datetime.now()
            start = end - timedelta(days=max(1, min(days, 365)))
        if end <= start:
            return jsonify({"ok": False, "error": "end должен быть > start"}), 400

        start_db = start.strftime("%Y-%m-%d %H:%M:%S")
        end_db = end.strftime("%Y-%m-%d %H:%M:%S")

        folder = Path(folder_path)
        files_map = _crypto_required_files(folder)
        groups_raw = _parse_crypto_groups(files_map["dmr_enhanced_key_groups.xml"])
        callsigns = _parse_crypto_callsigns(files_map["dmr_enhanced_key_privates.xml"])
        keys = _parse_crypto_keys(files_map["dmr_enhanced_keys.xml"])

        groups: dict[str, list[str]] = {}
        group_display: dict[str, str] = {}
        group_norm_by_display: dict[str, str] = {}
        for gid, key_uids in groups_raw.items():
            norm = _normalize_group_key(gid)
            if not norm:
                continue
            groups[norm] = key_uids
            if norm not in group_display:
                group_display[norm] = gid
            group_norm_by_display[gid] = norm

        seans_conn = get_request_seans_db()
        seans_src = seanses_union_source_sql(seans_conn)
        try:
            params: list[object] = []
            where = "1=1"
            if position_filter:
                where += " AND client_name=?"
                params.append(position_filter)
            rows = seans_conn.execute(
                f"""
                SELECT date_time, group_, id, aes_key
                FROM ({seans_src}) s
                WHERE {where} AND date_time >= ? AND date_time <= ?
                """,
                tuple(params + [start_db, end_db]),
            ).fetchall()

            unit_rows = main_conn.execute(
                """
                SELECT group_, name, updated_at
                FROM unit
                """
            ).fetchall()
            unit_by_group: dict[str, str] = {}
            unit_updated: dict[str, str] = {}
            for r in unit_rows:
                g_raw = str(r[0] or "").strip()
                g_norm = _normalize_group_key(g_raw)
                if not g_norm:
                    continue
                name = str(r[1] or "").strip()
                upd = str(r[2] or "").strip()
                if not name:
                    continue
                if g_norm not in unit_by_group:
                    unit_by_group[g_norm] = name
                    unit_updated[g_norm] = upd
                else:
                    prev = unit_updated.get(g_norm, "")
                    if upd and upd > prev:
                        unit_by_group[g_norm] = name
                        unit_updated[g_norm] = upd

            active_group_ids: set[str] = set()
            active_callsign_ids: set[str] = set()
            aes_key_set: set[str] = set()
            for r in rows:
                grp_raw = str(r[1] or "").strip()
                gid = _normalize_group_key(grp_raw)
                if gid:
                    active_group_ids.add(gid)
                cid = str(r[2] or "").strip()
                if cid:
                    active_callsign_ids.add(cid)
                aes_key = _normalize_key_id(str(r[3] or "").strip())
                if aes_key:
                    aes_key_set.add(aes_key)

            last_seen_key_map: dict[tuple[str, str], str] = {}
            last_seen_key_rows = seans_conn.execute(
                f"""
                SELECT group_, aes_key, MAX(date_time) as last_dt
                FROM ({seans_src}) s
                WHERE {where}
                GROUP BY group_, aes_key
                """,
                tuple(params),
            ).fetchall()
            for r in last_seen_key_rows:
                grp_raw = str(r[0] or "").strip()
                gid = _normalize_group_key(grp_raw)
                aes_key = _normalize_key_id(str(r[1] or "").strip())
                dt = str(r[2] or "").strip()
                if gid and aes_key and dt:
                    key = (gid, aes_key)
                    if key not in last_seen_key_map or dt > last_seen_key_map[key]:
                        last_seen_key_map[key] = dt

            group_last_raw = seans_conn.execute(
                f"""
                SELECT group_, MAX(date_time) as last_dt
                FROM ({seans_src}) s
                WHERE {where}
                GROUP BY group_
                """,
                tuple(params),
            ).fetchall()
            group_last_seen: dict[str, str] = {}
            for r in group_last_raw:
                gid = _normalize_group_key(str(r[0] or "").strip())
                dt = str(r[1] or "").strip()
                if not gid or not dt:
                    continue
                if gid not in group_last_seen or dt > group_last_seen[gid]:
                    group_last_seen[gid] = dt

            callsign_last_raw = seans_conn.execute(
                f"""
                SELECT id, MAX(date_time) as last_dt
                FROM ({seans_src}) s
                WHERE {where}
                GROUP BY id
                """,
                tuple(params),
            ).fetchall()
            callsign_last_seen: dict[str, str] = {}
            for r in callsign_last_raw:
                cid = str(r[0] or "").strip()
                dt = str(r[1] or "").strip()
                if not cid or not dt:
                    continue
                if cid not in callsign_last_seen or dt > callsign_last_seen[cid]:
                    callsign_last_seen[cid] = dt
        finally:
            pass

        key_groups: dict[str, set[str]] = defaultdict(set)
        key_callsigns: dict[str, set[str]] = defaultdict(set)
        for gid_norm, key_uids in groups.items():
            display_id = group_display.get(gid_norm, gid_norm)
            for uid in key_uids:
                key_groups[uid].add(display_id)
        for cid, key_uids in callsigns.items():
            for uid in key_uids:
                key_callsigns[uid].add(cid)

        active_key_uids: set[str] = set()
        for gid in active_group_ids:
            for uid in groups.get(gid, []):
                active_key_uids.add(uid)
        for cid in active_callsign_ids:
            for uid in callsigns.get(cid, []):
                active_key_uids.add(uid)

        all_key_uids = set(key_groups.keys()) | set(key_callsigns.keys())
        inactive_key_uids = all_key_uids - active_key_uids

        def _dt_to_iso(s: str) -> str:
            return s.replace(" ", "T") if s else ""

        active_keys = []
        for uid in sorted(
            active_key_uids, key=lambda x: int(x) if str(x).isdigit() else str(x)
        ):
            key_meta = keys.get(uid, {})
            group_ids = sorted(key_groups.get(uid, set()), key=str)
            callsign_ids = sorted(key_callsigns.get(uid, set()), key=str)
            key_id = _normalize_key_id(str(key_meta.get("key_id") or "").strip())
            unit_names: list[str] = []
            for g in group_ids:
                norm = group_norm_by_display.get(g, _normalize_group_key(g))
                name = unit_by_group.get(norm, "")
                if name and name not in unit_names:
                    unit_names.append(name)
            last_seen = ""
            if key_id:
                for g in group_ids:
                    norm = group_norm_by_display.get(g, _normalize_group_key(g))
                    dt = last_seen_key_map.get((norm, key_id), "")
                    if dt and dt > last_seen:
                        last_seen = dt
            active_keys.append(
                {
                    "key_uid": uid,
                    "key_id": key_id,
                    "alg": str(key_meta.get("alg") or "").strip(),
                    "value": str(key_meta.get("value") or "").strip(),
                    "group_ids": group_ids,
                    "callsign_ids": callsign_ids,
                    "unit_names": unit_names,
                    "key_id_seen": bool(last_seen),
                    "last_seen": _dt_to_iso(last_seen),
                }
            )
        # Сортируем по последней активности (новые -> старые)
        active_keys.sort(
            key=lambda x: (
                1 if x.get("last_seen") else 0,
                str(x.get("last_seen") or ""),
            ),
            reverse=True,
        )

        inactive_keys = []
        for uid in sorted(
            inactive_key_uids, key=lambda x: int(x) if str(x).isdigit() else str(x)
        ):
            key_meta = keys.get(uid, {})
            group_ids = sorted(key_groups.get(uid, set()), key=str)
            unit_names: list[str] = []
            for g in group_ids:
                norm = group_norm_by_display.get(g, _normalize_group_key(g))
                name = unit_by_group.get(norm, "")
                if name and name not in unit_names:
                    unit_names.append(name)
            inactive_keys.append(
                {
                    "key_uid": uid,
                    "key_id": _normalize_key_id(
                        str(key_meta.get("key_id") or "").strip()
                    ),
                    "group_ids": group_ids,
                    "callsign_ids": sorted(key_callsigns.get(uid, set()), key=str),
                    "unit_names": unit_names,
                }
            )

        inactive_groups = []
        for gid_norm, key_uids in groups.items():
            if gid_norm in active_group_ids:
                continue
            display_id = group_display.get(gid_norm, gid_norm)
            last_seen = group_last_seen.get(gid_norm, "")
            unit_name = unit_by_group.get(gid_norm, "")
            inactive_groups.append(
                {
                    "group_id": display_id,
                    "key_count": len(key_uids or []),
                    "last_seen": _dt_to_iso(last_seen),
                    "unit_name": unit_name,
                }
            )

        inactive_callsigns = []
        for cid, key_uids in callsigns.items():
            if cid in active_callsign_ids:
                continue
            last_seen = callsign_last_seen.get(cid, "")
            inactive_callsigns.append(
                {
                    "callsign_id": cid,
                    "key_count": len(key_uids or []),
                    "last_seen": _dt_to_iso(last_seen),
                }
            )

        inactive_groups.sort(key=lambda x: str(x.get("group_id") or ""))
        inactive_callsigns.sort(key=lambda x: str(x.get("callsign_id") or ""))

        return jsonify(
            {
                "ok": True,
                "info": f"Период: {start_db} — {end_db}.",
                "stats": {
                    "active_keys": len(active_keys),
                    "inactive_keys": len(inactive_keys),
                    "inactive_groups": len(inactive_groups),
                    "inactive_callsigns": len(inactive_callsigns),
                },
                "active_keys": active_keys,
                "inactive_keys": inactive_keys,
                "inactive_groups": inactive_groups,
                "inactive_callsigns": inactive_callsigns,
            }
        )

    @app.post("/api/crypto/keys/append")
    @login_required
    def api_crypto_keys_append():
        if not (
            current_user.has_perm("import_folder")
            or current_user.has_perm("manage_users")
        ):
            return jsonify({"ok": False, "error": "Нет прав"}), 403

        data = request.get_json(silent=True) or {}
        rows = data.get("rows") or []
        if not isinstance(rows, list) or not rows:
            return jsonify({"ok": False, "error": "Пустой список"}), 400

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            folder_path = get_sync_meta(conn, "crypto_folder_path") or ""
        finally:
            conn.close()
        status_text, files = _crypto_folder_status(folder_path)
        if not folder_path or not files or not all(files.values()):
            return jsonify({"ok": False, "error": status_text}), 400

        folder = Path(folder_path)
        files_map = _crypto_required_files(folder)
        groups_path = files_map["dmr_enhanced_key_groups.xml"]
        keys_path = files_map["dmr_enhanced_keys.xml"]

        keys_tree, keys_root = _load_xml_tree(keys_path)
        groups_tree, groups_root = _load_xml_tree(groups_path)

        existing_pairs: set[tuple[str, str]] = set()
        max_uid = 0
        for k in keys_root.findall("key"):
            uid_node = k.find("key_uid")
            kid_node = k.find("key_id")
            val_node = k.find("value")
            uid = str(uid_node.text or "").strip() if uid_node is not None else ""
            if uid.isdigit():
                max_uid = max(max_uid, int(uid))
            key_id = str(kid_node.text or "").strip() if kid_node is not None else ""
            val = str(val_node.text or "").strip() if val_node is not None else ""
            if key_id and val:
                existing_pairs.add((key_id, val))

        added = 0
        skipped = 0
        groups_created = 0
        for r in rows:
            freq = str(r.get("frequency") or "").strip()
            group_id_raw = str(r.get("group") or "").strip()
            group_id = _normalize_group_key(group_id_raw) or group_id_raw
            aes_id = str(r.get("aes_id") or "").strip()
            aes_key_raw = str(r.get("aes_key") or "").strip()
            aes_key = aes_key_raw.upper()
            if not group_id or not aes_id or not aes_key:
                skipped += 1
                continue
            key_id = aes_id
            if (key_id, aes_key) in existing_pairs:
                skipped += 1
                continue

            max_uid += 1
            key_uid = str(max_uid)
            key_el = ET.Element("key", {"Alg": "AES256"})
            kid_uid = ET.SubElement(key_el, "key_uid")
            kid_uid.text = key_uid
            kid = ET.SubElement(key_el, "key_id")
            kid.text = key_id
            alg = ET.SubElement(key_el, "alg_id")
            alg.text = "7"
            val = ET.SubElement(key_el, "value")
            val.text = aes_key
            dt = ET.SubElement(key_el, "date_time")
            dt.text = str(int(time.time()))
            comment = ET.SubElement(key_el, "comment")
            comment.text = ""
            keys_root.append(key_el)

            group_el = _xml_find_group(groups_root, group_id)
            if group_el is None:
                group_el = _xml_create_group(groups_root, group_id)
                groups_created += 1
            _xml_add_key_uid(group_el, key_uid)

            existing_pairs.add((key_id, aes_key))
            added += 1

        _sort_groups_by_id(groups_root)
        _write_xml_tree(keys_path, keys_tree)
        _write_xml_tree(groups_path, groups_tree)

        return jsonify(
            {
                "ok": True,
                "added": added,
                "skipped": skipped,
                "groups_created": groups_created,
            }
        )

    @app.post("/api/crypto/delete")
    @login_required
    def api_crypto_delete():
        if not (
            current_user.has_perm("import_folder")
            or current_user.has_perm("manage_users")
        ):
            return jsonify({"ok": False, "error": "Нет прав"}), 403

        data = request.get_json(silent=True) or {}
        kind = str(data.get("type") or "").strip().lower()
        key_uid = str(data.get("key_uid") or "").strip()
        group_id = str(data.get("group_id") or "").strip()

        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            folder_path = get_sync_meta(conn, "crypto_folder_path") or ""
        finally:
            conn.close()
        status_text, files = _crypto_folder_status(folder_path)
        if not folder_path or not files or not all(files.values()):
            return jsonify({"ok": False, "error": status_text}), 400

        folder = Path(folder_path)
        files_map = _crypto_required_files(folder)
        groups_path = files_map["dmr_enhanced_key_groups.xml"]
        callsigns_path = files_map["dmr_enhanced_key_privates.xml"]
        keys_path = files_map["dmr_enhanced_keys.xml"]

        if kind not in {"key", "group"}:
            return jsonify({"ok": False, "error": "Неверный тип удаления"}), 400

        if kind == "key":
            if not key_uid:
                return jsonify({"ok": False, "error": "key_uid обязателен"}), 400
            keys_tree, keys_root = _load_xml_tree(keys_path)
            groups_tree, groups_root = _load_xml_tree(groups_path)
            calls_tree, calls_root = _load_xml_tree(callsigns_path)

            removed_keys = 0
            for k in list(keys_root.findall("key")):
                uid_node = k.find("key_uid")
                if uid_node is not None and str(uid_node.text or "").strip() == key_uid:
                    keys_root.remove(k)
                    removed_keys += 1

            removed_group_refs = _remove_key_uid_from_groups(groups_root, key_uid)
            removed_call_refs = _remove_key_uid_from_callsigns(calls_root, key_uid)
            if removed_keys == 0 and removed_group_refs == 0 and removed_call_refs == 0:
                return jsonify({"ok": False, "error": "key_uid не найден"}), 404

            _cleanup_empty_groups(groups_root)
            _cleanup_empty_callsigns(calls_root)
            _reindex_key_uids(keys_root, groups_root, calls_root)
            _sort_groups_by_id(groups_root)
            _write_xml_tree(keys_path, keys_tree)
            _write_xml_tree(groups_path, groups_tree)
            _write_xml_tree(callsigns_path, calls_tree)
            return jsonify(
                {
                    "ok": True,
                    "info": "Ключ удален, key_uid переиндексированы.",
                    "removed": {
                        "keys": removed_keys,
                        "groups": removed_group_refs,
                        "callsigns": removed_call_refs,
                    },
                }
            )

        if not group_id:
            return jsonify({"ok": False, "error": "group_id обязателен"}), 400

        groups_tree = _parse_crypto_groups(groups_path)
        key_uids = groups_tree.get(group_id, [])
        if not key_uids:
            # попробуем через нормализацию
            norm = _normalize_group_key(group_id)
            if norm:
                for gid, keys in groups_tree.items():
                    if _normalize_group_key(gid) == norm:
                        key_uids = keys
                        group_id = gid
                        break
        if not key_uids:
            return jsonify({"ok": False, "error": "Группа не найдена"}), 404

        keys_tree, keys_root = _load_xml_tree(keys_path)
        groups_tree, groups_root = _load_xml_tree(groups_path)
        calls_tree, calls_root = _load_xml_tree(callsigns_path)

        removed_groups = 0
        for g in list(groups_root.findall("group")):
            gid_node = g.find("id")
            if gid_node is not None and str(gid_node.text or "").strip() == group_id:
                groups_root.remove(g)
                removed_groups += 1
                break
        if removed_groups == 0:
            return jsonify({"ok": False, "error": "Группа не найдена"}), 404

        removed_keys_total = 0
        removed_group_refs_total = 0
        removed_call_refs_total = 0
        for uid in key_uids:
            for k in list(keys_root.findall("key")):
                uid_node = k.find("key_uid")
                if uid_node is not None and str(uid_node.text or "").strip() == uid:
                    keys_root.remove(k)
                    removed_keys_total += 1
            removed_group_refs_total += _remove_key_uid_from_groups(groups_root, uid)
            removed_call_refs_total += _remove_key_uid_from_callsigns(calls_root, uid)

        _cleanup_empty_groups(groups_root)
        _cleanup_empty_callsigns(calls_root)
        _reindex_key_uids(keys_root, groups_root, calls_root)
        _sort_groups_by_id(groups_root)
        _write_xml_tree(groups_path, groups_tree)
        _write_xml_tree(keys_path, keys_tree)
        _write_xml_tree(callsigns_path, calls_tree)

        return jsonify(
            {
                "ok": True,
                "info": "Группа и связанные ключи удалены.",
                "removed": {
                    "groups": removed_groups,
                    "keys": removed_keys_total,
                    "groups_refs": removed_group_refs_total,
                    "callsigns_refs": removed_call_refs_total,
                },
            }
        )
