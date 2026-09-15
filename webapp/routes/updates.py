"""SERVER-публикация и безопасное применение обновлений HUB."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import socket
from pathlib import Path
from urllib import request as urlrequest

from flask import jsonify, request, send_file
from flask_login import current_user, login_required

from web_portal.config import (
    DATA_DIR,
    DEFAULT_DB_NAME,
    db_path,
    portal_db_path,
    seans_db_path,
    updates_dir,
)
from web_portal.lib.hub_updates import (
    append_hub_update_report,
    list_hub_update_reports,
    list_release_packages,
    publish_release,
    read_current_release,
    release_signature,
    release_package_path,
    sha256_file,
)
from web_portal.webapp.context import AppContext


def _fetch_server_manifest(upstream: str, sync_key: str) -> dict:
    req = urlrequest.Request(
        f"{upstream.rstrip('/')}/api/updates/current",
        method="GET",
        headers={"X-Sync-Key": sync_key},
    )
    with urlrequest.urlopen(req, timeout=12) as response:
        raw = response.read() or b"{}"
    data = json.loads(raw.decode("utf-8") or "{}")
    if not isinstance(data, dict) or data.get("ok") is not True:
        raise RuntimeError(str(data.get("error") if isinstance(data, dict) else "bad response"))
    release = data.get("release")
    signature = str(data.get("signature") or "").strip().lower()
    if not isinstance(release, dict) or not release.get("revision"):
        return {}
    expected = release_signature(release, sync_key)
    if len(signature) != 64 or not hmac.compare_digest(signature, expected):
        raise RuntimeError("Подпись манифеста обновления не прошла проверку")
    return release


def _read_installed_revision() -> str:
    path = DATA_DIR / "hub_release.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        return str(raw.get("revision") or "").strip() if isinstance(raw, dict) else ""
    except Exception:
        return ""


def _write_update_request_status(payload: dict) -> None:
    target = DATA_DIR / "update_status.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def _download_package(*, upstream: str, sync_key: str, release: dict) -> Path:
    package = str(release.get("package") or "").strip()
    checksum = str(release.get("sha256") or "").strip().lower()
    revision = str(release.get("revision") or "").strip()
    size = max(0, int(release.get("size_bytes") or 0))
    if not package or "/" in package or "\\" in package or len(checksum) != 64:
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


def _hub_install_dir() -> Path:
    if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _checkpoint_hub_databases() -> None:
    """Фиксирует WAL трёх рабочих БД до перезапуска процесса HUB."""
    failures: list[str] = []
    for path in (db_path(DEFAULT_DB_NAME), portal_db_path(), seans_db_path()):
        if not path.is_file():
            continue
        try:
            conn = sqlite3.connect(str(path), timeout=20)
            try:
                conn.execute("PRAGMA wal_checkpoint(FULL)")
                result = conn.execute("PRAGMA quick_check").fetchone()
                if not result or str(result[0]).lower() != "ok":
                    raise RuntimeError(f"quick_check: {result[0] if result else 'нет ответа'}")
            finally:
                conn.close()
        except Exception as exc:
            failures.append(f"{path.name}: {exc}")
    if failures:
        raise RuntimeError("Не удалось безопасно зафиксировать БД: " + "; ".join(failures))


def register_update_routes(app, ctx: AppContext) -> None:
    """Регистрирует SERVER API публикации и локальный HUB API установки."""

    def _require_sync_key() -> bool:
        expected = str(ctx.sync_key or "")
        got = (request.headers.get("X-Sync-Key") or "").strip()
        return bool(expected and got and hmac.compare_digest(expected, got))

    def _is_central_server() -> bool:
        return not ctx.is_sync_hub()

    def _is_release_admin() -> bool:
        return bool(
            current_user.is_authenticated
            and str(getattr(current_user, "role", "") or "").strip().lower() == "admin"
        )

    @app.before_request
    def reject_writes_while_hub_restarts():
        """После подтверждения обновления не принимаем новые изменения в БД."""
        if (
            ctx.is_sync_hub()
            and app.config.get("HUB_UPDATE_DRAINING")
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and request.path not in {"/api/hub-update/apply"}
        ):
            return jsonify(
                {
                    "ok": False,
                    "error": "HUB перезапускается для обновления. Повторите действие через минуту.",
                }
            ), 503

    @app.get("/api/admin/updates/packages")
    @login_required
    def api_admin_update_packages():
        if not _is_release_admin():
            return jsonify({"ok": False, "error": "Публиковать обновления может только роль admin"}), 403
        if not _is_central_server():
            return jsonify({"ok": False, "error": "Пакеты публикуются только на SERVER"}), 409
        return jsonify(
            {
                "ok": True,
                "directory": str(updates_dir()),
                "packages": list_release_packages(updates_dir()),
                "current": read_current_release(updates_dir()),
            }
        )

    @app.post("/api/admin/updates/publish")
    @login_required
    def api_admin_publish_update():
        if not _is_release_admin():
            return jsonify({"ok": False, "error": "Публиковать обновления может только роль admin"}), 403
        if not _is_central_server():
            return jsonify({"ok": False, "error": "Пакеты публикуются только на SERVER"}), 409
        data = request.get_json(silent=True) or {}
        try:
            release = publish_release(
                updates_dir(),
                package=str(data.get("package") or ""),
                revision=str(data.get("revision") or ""),
                title=str(data.get("title") or ""),
                notes=str(data.get("notes") or ""),
            )
        except (ValueError, OSError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if ctx.log_portal_event is not None:
            ctx.log_portal_event(
                level="INFO",
                category="updates",
                action="release_published",
                message=f"Опубликовано обновление HUB {release['revision']}",
                username=str(getattr(current_user, "username", "") or ""),
                path="/api/admin/updates/publish",
                method="POST",
                details={"revision": release["revision"], "package": release["package"]},
            )
        return jsonify({"ok": True, "release": release})

    @app.get("/api/updates/current")
    def api_server_current_update():
        if not _is_central_server() or not _require_sync_key():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        release = read_current_release(updates_dir())
        return jsonify(
            {
                "ok": True,
                "release": release,
                "signature": release_signature(release, ctx.sync_key) if release else "",
            }
        )

    @app.get("/api/updates/package/<path:package>")
    def api_server_update_package(package: str):
        if not _is_central_server() or not _require_sync_key():
            return jsonify({"ok": False, "error": "forbidden"}), 403
        current = read_current_release(updates_dir())
        if not current or str(current.get("package") or "") != str(package or ""):
            return jsonify({"ok": False, "error": "Пакет не опубликован"}), 404
        try:
            path = release_package_path(updates_dir(), package)
        except (FileNotFoundError, ValueError):
            return jsonify({"ok": False, "error": "Пакет не найден"}), 404
        if not hmac.compare_digest(sha256_file(path), str(current.get("sha256") or "")):
            return jsonify({"ok": False, "error": "Файл пакета изменён после публикации"}), 409
        return send_file(path, as_attachment=True, download_name=path.name, max_age=0)

    @app.get("/api/hub-update/manifest")
    @login_required
    def api_hub_update_manifest():
        if not ctx.is_sync_hub():
            return jsonify({"ok": True, "available": False, "reason": "not_hub"})
        try:
            release = _fetch_server_manifest(ctx.sync_upstream, ctx.sync_key)
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Не удалось проверить SERVER: {exc}"}), 502
        installed = _read_installed_revision()
        return jsonify(
            {
                "ok": True,
                "available": bool(release and str(release.get("revision") or "") != installed),
                "installed_revision": installed,
                "release": release,
            }
        )

    @app.get("/api/hub-update/status")
    @login_required
    def api_hub_update_status():
        path = DATA_DIR / "update_status.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8") or "{}")
        except Exception:
            data = {}
        return jsonify({"ok": True, "status": data if isinstance(data, dict) else {}})

    @app.post("/api/hub-update/apply")
    @login_required
    def api_hub_update_apply():
        if not ctx.is_sync_hub():
            return jsonify({"ok": False, "error": "Обновление пакета доступно только на HUB"}), 409
        data = request.get_json(silent=True) or {}
        requested_revision = str(data.get("revision") or "").strip()
        try:
            release = _fetch_server_manifest(ctx.sync_upstream, ctx.sync_key)
            revision = str(release.get("revision") or "").strip()
            if not revision or requested_revision != revision:
                return jsonify({"ok": False, "error": "Версия обновления изменилась; проверьте её заново"}), 409
            if revision == _read_installed_revision():
                return jsonify({"ok": False, "error": "Эта версия HUB уже установлена"}), 409
            _write_update_request_status({"state": "downloading", "revision": revision})
            package = _download_package(
                upstream=ctx.sync_upstream,
                sync_key=ctx.sync_key,
                release=release,
            )
            watcher = getattr(app, "session_watchers", {}).get("hub_global")
            if watcher:
                if watcher.get("mode") == "subprocess":
                    stop_path = watcher.get("stop_path")
                    proc = watcher.get("proc")
                    if stop_path:
                        Path(stop_path).touch()
                    if proc:
                        try:
                            proc.wait(timeout=8)
                        except Exception:
                            proc.terminate()
                            proc.wait(timeout=5)
                else:
                    stop = watcher.get("stop")
                    if stop:
                        stop.set()
                    thread = watcher.get("thread")
                    if thread:
                        thread.join(timeout=5)
            _write_update_request_status({"state": "checkpointing", "revision": revision})
            _checkpoint_hub_databases()
            updater = _hub_install_dir() / "EAVC Updater.exe"
            if not updater.is_file():
                raise RuntimeError(
                    "В этой сборке HUB нет EAVC Updater.exe. Первое обновление установите вручную."
                )
            _write_update_request_status({"state": "queued", "revision": revision})
            command = [
                str(updater),
                "--parent-pid", str(os.getpid()),
                "--install-dir", str(_hub_install_dir()),
                "--data-dir", str(DATA_DIR),
                "--package", str(package),
                "--revision", revision,
                "--port", str(int(os.environ.get("WEB_PORTAL_PORT", "5000"))),
            ]
            # После этой точки новые записи отвергаются: сохранённые БД уже
            # зафиксированы, а клиент получил 202 до остановки процесса.
            app.config["HUB_UPDATE_DRAINING"] = True
            subprocess.Popen(command, cwd=str(_hub_install_dir()), close_fds=True)
        except Exception as exc:
            app.config["HUB_UPDATE_DRAINING"] = False
            _write_update_request_status({"state": "failed", "revision": requested_revision, "error": str(exc)})
            return jsonify({"ok": False, "error": str(exc)}), 400

        def _shutdown_after_reply() -> None:
            time.sleep(3.5)
            os._exit(0)

        threading.Thread(target=_shutdown_after_reply, daemon=True, name="hub-update-shutdown").start()
        return jsonify({"ok": True, "message": "Пакет проверен. HUB перезапустится через несколько секунд."}), 202


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

