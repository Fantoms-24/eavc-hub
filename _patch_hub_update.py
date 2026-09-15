# -*- coding: utf-8 -*-
"""Patch HUB update progress + SERVER hub-updated notifications."""
from pathlib import Path
import re

ROOT = Path(r"C:\Users\vasya\Desktop\Project\Copy")

# ---------- hub_updates.py: append report helpers ----------
hub_updates = ROOT / "lib" / "hub_updates.py"
text = hub_updates.read_text(encoding="utf-8")
marker = "def release_signature("
if "def append_hub_update_report(" not in text:
    helper = '''
HUB_UPDATE_ACKS_NAME = "hub_update_acks.json"
_MAX_HUB_UPDATE_ACKS = 200


def _acks_path(directory: Path) -> Path:
    return Path(directory) / HUB_UPDATE_ACKS_NAME


def append_hub_update_report(directory: Path, report: dict[str, Any]) -> dict[str, Any]:
    """Сохраняет отчёт HUB об успешном обновлении (дедуп по hub_id+revision)."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    hub_id = str(report.get("hub_id") or "").strip() or "unknown"
    hub_name = str(report.get("hub_name") or hub_id).strip() or hub_id
    revision = str(report.get("revision") or "").strip()
    if not revision:
        raise ValueError("revision обязателен")
    entry = {
        "hub_id": hub_id,
        "hub_name": hub_name,
        "revision": revision,
        "ip_address": str(report.get("ip_address") or "").strip(),
        "reported_at": _utc_now(),
        "id": f"{hub_id}|{revision}",
    }
    path = _acks_path(directory)
    rows: list[dict[str, Any]] = []
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8") or "[]")
            if isinstance(raw, list):
                rows = [r for r in raw if isinstance(r, dict)]
        except Exception:
            rows = []
    rows = [r for r in rows if str(r.get("id") or "") != entry["id"]]
    rows.insert(0, entry)
    rows = rows[:_MAX_HUB_UPDATE_ACKS]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return entry


def list_hub_update_reports(directory: Path, *, limit: int = 50) -> list[dict[str, Any]]:
    path = _acks_path(Path(directory))
    if not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "[]")
    except Exception:
        return []
    if not isinstance(raw, list):
        return []
    out = [r for r in raw if isinstance(r, dict)]
    return out[: max(1, min(int(limit or 50), 200))]


'''
    text = text.replace(marker, helper + marker, 1)
    hub_updates.write_text(text, encoding="utf-8")
    print("hub_updates.py: helpers OK")
else:
    print("hub_updates.py: already patched")

# ---------- updates.py ----------
upd = ROOT / "webapp" / "routes" / "updates.py"
ut = upd.read_text(encoding="utf-8")

# Fix imports
old_imp = '''from web_portal.lib.hub_updates import (
    list_release_packages,
    publish_release,
    read_current_release,
    release_signature,
    release_package_path,
    sha256_file,
)'''
new_imp = '''from web_portal.lib.hub_updates import (
    append_hub_update_report,
    list_hub_update_reports,
    list_release_packages,
    publish_release,
    read_current_release,
    release_signature,
    release_package_path,
    sha256_file,
)'''
if "append_hub_update_report" not in ut:
    ut = ut.replace(old_imp, new_imp, 1)

# Replace _download_package with progress-aware version
old_dl_start = "def _download_package(*, upstream: str, sync_key: str, release: dict) -> Path:"
if "bytes_received" not in ut:
    # replace the whole function body until next def
    m = re.search(r"def _download_package\(.*?\n(?=def _hub_install_dir)", ut, re.S)
    if not m:
        raise SystemExit("download function not found")
    new_dl = '''def _download_package(*, upstream: str, sync_key: str, release: dict) -> Path:
    package = str(release.get("package") or "").strip()
    checksum = str(release.get("sha256") or "").strip().lower()
    revision = str(release.get("revision") or "").strip()
    size = max(0, int(release.get("size_bytes") or 0))
    if not package or "/" in package or "\\\\" in package or len(checksum) != 64:
        raise ValueError("Некорректный манифест обновления")
    # Файлы обновления кладём возле EXE: при замене каталог остаётся на одном томе
    # и не отнимает место у рабочих SQLite-данных HUB.
    updates_state = _hub_install_dir() / ".eavc-update"
    updates_state.mkdir(parents=True, exist_ok=True)
    if size:
        free = shutil.disk_usage(updates_state).free
        unpacked = max(0, int(release.get("unpacked_bytes") or 0))
        required = size + unpacked + 512 * 1024 * 1024
        if free < required:
            raise RuntimeError("Недостаточно места для безопасного обновления HUB")
    final = updates_state / f"{revision}.zip"
    partial = updates_state / f"{revision}.zip.part"
    digest = hashlib.sha256()
    req = urlrequest.Request(
        f"{upstream.rstrip('/')}/api/updates/package/{package}",
        method="GET",
        headers={"X-Sync-Key": sync_key},
    )
    received = 0
    last_pct = -1
    last_write = 0.0
    try:
        with urlrequest.urlopen(req, timeout=30) as response, partial.open("wb") as dst:
            while chunk := response.read(1024 * 1024):
                received += len(chunk)
                if size and received > size:
                    raise RuntimeError("Размер скачанного обновления не совпадает с манифестом")
                digest.update(chunk)
                dst.write(chunk)
                now = time.monotonic()
                pct = int(received * 100 / size) if size else 0
                if (
                    size
                    and (pct != last_pct or now - last_write >= 0.4)
                    and (pct >= last_pct + 1 or now - last_write >= 0.4 or received == size)
                ):
                    last_pct = pct
                    last_write = now
                    _write_update_request_status(
                        {
                            "state": "downloading",
                            "revision": revision,
                            "percent": max(0, min(100, pct)),
                            "bytes_received": received,
                            "bytes_total": size,
                        }
                    )
        if size and received != size:
            raise RuntimeError("Пакет обновления скачан не полностью")
        if not hmac.compare_digest(digest.hexdigest(), checksum):
            raise RuntimeError("Контрольная сумма пакета не совпадает")
        _write_update_request_status(
            {
                "state": "verifying",
                "revision": revision,
                "percent": 100,
                "bytes_received": received,
                "bytes_total": size or received,
            }
        )
        os.replace(partial, final)
        return final
    except Exception:
        partial.unlink(missing_ok=True)
        raise


'''
    ut = ut[: m.start()] + new_dl + ut[m.end() :]
    print("updates.py: download progress OK")
else:
    print("updates.py: download already has progress")

# Add socket/hostname import for hub identity if missing
if "import socket" not in ut:
    ut = ut.replace("from pathlib import Path", "import socket\nfrom pathlib import Path", 1)

# Add endpoints before end of register_update_routes - find last return of apply and add after apply function
if "/api/updates/hub-report" not in ut:
    extra = '''
    @app.post("/api/updates/hub-report")
    def api_server_hub_update_report():
        """HUB сообщает SERVER об успешном обновлении (X-Sync-Key)."""
        if not _is_central_server() or not _require_sync_key():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        data = request.get_json(silent=True) or {}
        try:
            entry = append_hub_update_report(
                updates_dir(),
                {
                    "hub_id": data.get("hub_id") or request.remote_addr or "unknown",
                    "hub_name": data.get("hub_name") or "",
                    "revision": data.get("revision") or "",
                    "ip_address": request.remote_addr or "",
                },
            )
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if ctx.log_portal_event is not None:
            ctx.log_portal_event(
                level="INFO",
                category="updates",
                action="hub_updated",
                message=f"HUB {entry['hub_name']} обновился до {entry['revision']}",
                username="",
                path="/api/updates/hub-report",
                method="POST",
                details=entry,
            )
        return jsonify({"ok": True, "report": entry})

    @app.get("/api/admin/updates/hub-reports")
    @login_required
    def api_admin_hub_update_reports():
        if not _is_release_admin():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        if not _is_central_server():
            return jsonify({"ok": False, "error": "Только на SERVER", "reports": []}), 409
        limit = request.args.get("limit", 30, type=int)
        return jsonify({"ok": True, "reports": list_hub_update_reports(updates_dir(), limit=limit)})

    @app.post("/api/hub-update/notify-server")
    @login_required
    def api_hub_notify_server_updated():
        """После успешного обновления HUB один раз отчитывается на SERVER."""
        if not ctx.is_sync_hub():
            return jsonify({"ok": False, "error": "Только на HUB"}), 409
        data = request.get_json(silent=True) or {}
        revision = str(data.get("revision") or "").strip() or _read_installed_revision()
        if not revision:
            return jsonify({"ok": False, "error": "Нет revision"}), 400
        status_path = DATA_DIR / "update_status.json"
        try:
            st = json.loads(status_path.read_text(encoding="utf-8") or "{}")
        except Exception:
            st = {}
        if isinstance(st, dict) and st.get("server_notified") and str(st.get("revision") or "") == revision:
            return jsonify({"ok": True, "already": True})
        hostname = socket.gethostname() or "HUB"
        try:
            ip_addr = socket.gethostbyname(hostname)
        except Exception:
            ip_addr = ""
        body = json.dumps(
            {
                "hub_id": ip_addr or hostname,
                "hub_name": hostname,
                "revision": revision,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        req = urlrequest.Request(
            f"{ctx.sync_upstream.rstrip('/')}/api/updates/hub-report",
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Sync-Key": ctx.sync_key,
            },
        )
        try:
            with urlrequest.urlopen(req, timeout=12) as response:
                raw = response.read() or b"{}"
            payload = json.loads(raw.decode("utf-8") or "{}")
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                raise RuntimeError(str(payload.get("error") if isinstance(payload, dict) else "bad response"))
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Не удалось отчитаться на SERVER: {exc}"}), 502
        merged = st if isinstance(st, dict) else {}
        merged.update(
            {
                "state": "completed",
                "revision": revision,
                "server_notified": True,
                "percent": 100,
            }
        )
        _write_update_request_status(merged)
        return jsonify({"ok": True})

'''
    # Insert before the last line of register function - after apply's return
    # Find the shutdown return 202 line and append routes after the whole apply function
    anchor = '        return jsonify({"ok": True, "message": "Пакет проверен. HUB перезапустится через несколько секунд."}), 202\n'
    if anchor not in ut:
        raise SystemExit("apply return anchor missing")
    ut = ut.replace(anchor, anchor + "\n" + extra, 1)
    print("updates.py: report endpoints OK")
else:
    print("updates.py: endpoints already present")

upd.write_text(ut, encoding="utf-8")
print("updates.py written")
