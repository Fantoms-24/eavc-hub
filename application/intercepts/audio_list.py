"""Сборка ответа GET /api/intercepts/audio/list — сканирование и фильтрация без Flask."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import logging
import sqlite3
from pathlib import Path
from typing import Any

from web_portal.application.intercepts.audio_arm_task_sync import AUDIO_GLOBAL_POS
from web_portal.lib.db import (
    get_intercept_audio_state,
    list_intercept_audio_listened_keys,
    list_intercept_audio_tasks,
)
from web_portal.lib.intercept_audio import (
    SPEECH_HEURISTIC_VERSION,
    scan_intercept_audio_files,
)
from web_portal.lib.intercept_audio_bundle import (
    probe_bundle_layout,
    scan_bundle_intercept_audio_files,
)
from web_portal.lib.safe_paths import PathProbeResult, probe_path

_log = logging.getLogger("web_portal.application.intercepts.audio_list")


def _truthy_flag(value: object) -> bool:
    return str(value or "").lower() in {"1", "true", "yes"}


@dataclass(frozen=True)
class InterceptsAudioListParams:
    folder_paths: list[str]
    tasks_only: bool
    limit: int
    full_scan: bool
    quick_scan: bool
    debug_flag: bool
    cache_flag: bool
    since_ts: float | None
    recent_mtime_since: float | None
    layout_param: str
    req_is_running: bool | None
    req_client_id: str
    current_username: str


def parse_intercepts_audio_list_params(
    args: Mapping[str, str],
    *,
    current_username: str = "",
) -> InterceptsAudioListParams:
    folder_path_param = str(args.get("folder_path") or "").strip()
    folder_paths = [p.strip() for p in folder_path_param.splitlines() if p.strip()]

    tasks_only = _truthy_flag(args.get("tasks_only"))
    try:
        limit_raw = int(args.get("limit") or 300)
    except Exception:
        limit_raw = 300
    full_scan = _truthy_flag(args.get("full_scan"))
    quick_scan = _truthy_flag(args.get("quick"))
    limit = max(100, min(limit_raw, 50000))
    if not full_scan:
        cap = 200 if quick_scan else 600
        limit = min(limit, cap)
    debug_flag = _truthy_flag(args.get("debug"))
    cache_flag = str(args.get("cache") or "").lower() not in {"0", "false", "no"}

    since_time = str(args.get("since_time") or "").strip()
    since_ts: float | None = None
    if since_time:
        try:
            since_ts = float(since_time)
        except Exception:
            since_ts = None

    recent_mtime = str(args.get("recent_mtime_since") or "").strip()
    recent_mtime_since: float | None = None
    if recent_mtime:
        try:
            recent_mtime_since = float(recent_mtime)
        except Exception:
            recent_mtime_since = None

    layout_param = str(args.get("layout") or "auto").strip().lower()
    if layout_param not in ("auto", "dmr", "bundle"):
        layout_param = "auto"

    req_running_raw = args.get("is_running")
    req_is_running: bool | None = None
    if req_running_raw is not None:
        req_is_running = _truthy_flag(req_running_raw)

    req_client_id = str(args.get("client_id") or "").strip()

    return InterceptsAudioListParams(
        folder_paths=folder_paths,
        tasks_only=tasks_only,
        limit=limit,
        full_scan=full_scan,
        quick_scan=quick_scan,
        debug_flag=debug_flag,
        cache_flag=cache_flag,
        since_ts=since_ts,
        recent_mtime_since=recent_mtime_since,
        layout_param=layout_param,
        req_is_running=req_is_running,
        req_client_id=req_client_id,
        current_username=str(current_username or ""),
    )


def _resolve_bases(
    folder_paths: list[str],
    *,
    probe_path_fn: Callable[[str], PathProbeResult] = probe_path,
    logger: logging.Logger | None = None,
) -> tuple[list[str], list[str]]:
    log = logger or _log
    bases: list[str] = []
    invalid_paths: list[str] = []
    for fp in folder_paths:
        probe = probe_path_fn(fp)
        if probe.timed_out:
            invalid_paths.append(str(fp))
            log.warning("audio list: path probe timeout: %s", fp)
            continue
        if probe.ok and probe.exists and probe.is_dir:
            bases.append(probe.resolved or str(fp))
        else:
            invalid_paths.append(str(fp))
    return bases, invalid_paths


def _listening_users_for(
    file_key: str,
    *,
    listening_snapshot: dict[str, list[str]],
    listening_token_username: Callable[[str], str],
    listening_token_client: Callable[[str], str],
    current_username: str,
    req_client_id: str,
) -> list[str]:
    out: list[str] = []
    for token in listening_snapshot.get(file_key, []):
        name = listening_token_username(token).strip()
        if not name:
            continue
        tok_client = listening_token_client(token)
        if name == current_username and (
            (req_client_id and tok_client == req_client_id)
            or (not req_client_id and not tok_client)
        ):
            continue
        if name not in out:
            out.append(name)
    return out


def build_intercepts_audio_list_payload(
    conn: sqlite3.Connection,
    *,
    params: InterceptsAudioListParams,
    arm_task_sync: dict[str, Any] | None = None,
    listening_snapshot: dict[str, list[str]] | None = None,
    listening_token_username: Callable[[str], str] | None = None,
    listening_token_client: Callable[[str], str] | None = None,
    probe_path_fn: Callable[[str], PathProbeResult] = probe_path,
    logger: logging.Logger | None = None,
) -> dict[str, Any]:
    log = logger or _log
    bases, invalid_paths = _resolve_bases(
        params.folder_paths, probe_path_fn=probe_path_fn, logger=log
    )

    if not bases:
        tasks_for_response = list_intercept_audio_tasks(conn, AUDIO_GLOBAL_POS)
        return {
            "ok": True,
            "items": [],
            "total_found": 0,
            "total_unlistened": 0,
            "tasks": tasks_for_response,
            "arm_task_sync": arm_task_sync,
            "scan_meta": {
                "path_unavailable": True,
                "invalid_paths": invalid_paths,
                "base_count": 0,
                "bases_scanned": 0,
                "truncated": False,
                "reasons": ["path_unavailable"],
            },
        }

    state = get_intercept_audio_state(conn, position_name=AUDIO_GLOBAL_POS)
    if params.req_is_running is not None:
        state = dict(state) if state else {}
        state["is_running"] = params.req_is_running

    state_layout = str(state.get("layout_mode") or "dmr").strip().lower()
    if params.layout_param == "auto":
        resolved_layout = state_layout
        if resolved_layout != "bundle" and bases:
            try:
                if probe_bundle_layout(Path(bases[0])):
                    resolved_layout = "bundle"
            except Exception:
                _log.debug("build_intercepts_audio_list_payload: suppressed error", exc_info=True)
    else:
        resolved_layout = params.layout_param

    if (
        not state.get("is_running")
        and not params.debug_flag
        and not params.full_scan
        and resolved_layout != "bundle"
    ):
        return {
            "ok": True,
            "items": [],
            "total_found": 0,
            "total_unlistened": 0,
            "tasks": list_intercept_audio_tasks(conn, AUDIO_GLOBAL_POS),
            "arm_task_sync": arm_task_sync,
            "scan_meta": {"stopped": True, "layout": resolved_layout},
        }

    tasks_only = params.tasks_only
    tasks = list_intercept_audio_tasks(conn, AUDIO_GLOBAL_POS)
    active_task_freqs = [t["frequency"] for t in tasks if bool(t.get("is_active"))]
    if active_task_freqs and resolved_layout != "bundle":
        tasks_only = True
    if resolved_layout == "bundle":
        tasks_only = False

    limit = params.limit
    full_scan = params.full_scan
    quick_scan = params.quick_scan
    debug_flag = params.debug_flag
    cache_flag = params.cache_flag
    since_ts = params.since_ts
    recent_mtime_since = params.recent_mtime_since

    if resolved_layout == "bundle":
        time_budget_total = None if full_scan else 20.0
        since_ts = None
    elif full_scan:
        time_budget_total = None
    elif quick_scan:
        time_budget_total = 6.0 if tasks_only else 5.0
    elif recent_mtime_since is not None:
        time_budget_total = 3.5 if tasks_only else 2.5
    elif tasks_only:
        time_budget_total = 10.0
    else:
        time_budget_total = 5.0

    if quick_scan:
        max_time_folders = 6 if tasks_only else 8
    elif full_scan:
        max_time_folders = None
    elif tasks_only:
        max_time_folders = 10
    else:
        max_time_folders = 12

    debug_info: dict[str, Any] | None = {} if debug_flag else None
    scan_meta: dict[str, Any] = {
        "truncated": False,
        "reasons": [],
        "base_count": len(bases),
        "bases_scanned": 0,
        "cached_hits": 0,
        "elapsed_ms": 0.0,
        "invalid_paths": invalid_paths,
        "budget_s": float(time_budget_total or 0.0),
        "quick_scan": bool(quick_scan),
        "speech_heuristic_version": int(SPEECH_HEURISTIC_VERSION),
        "layout": resolved_layout,
    }
    budget_per_base = (
        (time_budget_total / len(bases)) if (time_budget_total and bases) else None
    )
    tagged_entries: list[tuple[str, Any]] = []
    scan_fn = (
        scan_bundle_intercept_audio_files
        if resolved_layout == "bundle"
        else scan_intercept_audio_files
    )
    for base_str in bases:
        base = Path(base_str)
        meta_this: dict[str, Any] = {}
        scan_kwargs = dict(
            tasks=active_task_freqs,
            tasks_only=tasks_only,
            limit=limit * 2,
            debug=debug_info,
            use_cache=cache_flag and not debug_flag and not full_scan,
            meta=meta_this,
            time_budget_s=budget_per_base if budget_per_base else None,
            since_ts=since_ts,
            newest_first=True,
        )
        if resolved_layout == "bundle":
            entries = scan_fn(base, **scan_kwargs)
        else:
            entries = scan_fn(
                base,
                **scan_kwargs,
                max_time_folders=max_time_folders,
                recent_mtime_since=recent_mtime_since,
            )
        for e in entries:
            tagged_entries.append((base_str, e))
        scan_meta["bases_scanned"] = int(scan_meta.get("bases_scanned", 0)) + 1
        if meta_this:
            scan_meta["elapsed_ms"] = float(scan_meta.get("elapsed_ms", 0.0)) + float(
                meta_this.get("elapsed_ms") or 0.0
            )
            if meta_this.get("cached"):
                scan_meta["cached_hits"] = int(scan_meta.get("cached_hits", 0)) + 1
            if meta_this.get("truncated"):
                scan_meta["truncated"] = True
                reason = str(meta_this.get("truncated_reason") or "").strip()
                if reason and reason not in scan_meta["reasons"]:
                    scan_meta["reasons"].append(reason)

    tagged_entries.sort(
        key=lambda x: (x[1].recorded_ts, x[1].order_index, x[1].file_rel),
        reverse=True,
    )
    if len(tagged_entries) > limit:
        tagged_entries = tagged_entries[:limit]
        scan_meta["truncated"] = True
        if "limit" not in scan_meta["reasons"]:
            scan_meta["reasons"].append("limit")

    try:
        listened = list_intercept_audio_listened_keys(conn, None)
    except Exception:
        listened = set()

    snap = listening_snapshot if listening_snapshot is not None else {}
    tok_user = listening_token_username or (lambda _t: "")
    tok_client = listening_token_client or (lambda _t: "")

    items: list[dict[str, Any]] = []
    for base_str, e in tagged_entries:
        items.append(
            {
                "file_rel": e.file_rel,
                "file_key": e.file_key,
                "folder_path": base_str,
                "frequency": e.frequency,
                "group_code": e.group_code,
                "correspondent_id": e.correspondent_id,
                "order_index": e.order_index,
                "recorded_at": e.recorded_at,
                "recorded_ts": e.recorded_ts,
                "duration_sec": e.duration_sec,
                "listened": bool(e.file_key in listened),
                "has_key": bool(e.has_key),
                "has_message": bool(getattr(e, "has_message", e.has_key)),
                "aes_key": str(e.aes_key or ""),
                "slot": str(e.slot or ""),
                "peer_correspondent_id": str(
                    getattr(e, "peer_correspondent_id", "") or ""
                ),
                "call_mode": str(getattr(e, "call_mode", "group") or "group"),
                "listening_by": _listening_users_for(
                    e.file_key,
                    listening_snapshot=snap,
                    listening_token_username=tok_user,
                    listening_token_client=tok_client,
                    current_username=params.current_username,
                    req_client_id=params.req_client_id,
                ),
            }
        )

    payload: dict[str, Any] = {
        "ok": True,
        "items": items,
        "total_found": len(items),
        "total_unlistened": len([i for i in items if not i.get("listened")]),
        "tasks": tasks,
        "arm_task_sync": arm_task_sync,
        "scan_meta": scan_meta,
    }
    if debug_info is not None:
        payload["debug"] = debug_info
    return payload
