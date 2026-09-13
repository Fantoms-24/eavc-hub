
import hmac
import logging
import os

_log = logging.getLogger("web_portal.app")
import sys
import threading
import sqlite3
from datetime import datetime
from pathlib import Path


from xml.etree import ElementTree as ET

from flask import Flask, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user

# Позволяет запускать как:
#   1) cd <папка проекта с любым именем> && python app.py
#   2) python -m web_portal.app   (из родительской директории)
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(BASE_DIR.parent))
# Регистрируем ЭТУ директорию как пакет web_portal: папка может называться
# как угодно (Copy, web_portal_v2 и т.п.), а случайная старая копия
# web_portal рядом не будет импортирована вместо актуальной.
_bootstrap_py = BASE_DIR / "_pkg_bootstrap.py"
if not getattr(sys, "frozen", False) and _bootstrap_py.exists():
    import importlib.util as _ilu

    _bs_spec = _ilu.spec_from_file_location("_pkg_bootstrap", _bootstrap_py)
    if _bs_spec is not None and _bs_spec.loader is not None:
        _bs_mod = _ilu.module_from_spec(_bs_spec)
        sys.modules.setdefault("_pkg_bootstrap", _bs_mod)
        _bs_spec.loader.exec_module(_bs_mod)

from web_portal.config import (
    DATA_DIR,
    DEFAULT_DB_NAME,
    db_path,
    deploy_announce_path,
    portal_db_path,
)
from web_portal.application.intercepts.state_sig import (
    compute_intercept_item_content_sig,
    normalize_intercept_item_content_sig,
)
from web_portal.lib.flask_db import close_request_dbs
from web_portal.lib.deploy_announce import read_announce
from web_portal.lib.auth_db import (
    TAB_CATEGORIES,
    UserRecord,
    connect_portal,
    update_custom_role,
    delete_custom_role,
    ensure_default_admin,
    get_user_by_id,
    update_user_password,
    verify_login,
    get_user_sync_payload_by_id,
    update_hub_activity,
)
from web_portal.lib.db import (
    connect,
    ensure_db,
    enqueue_sync_outbox,
    create_ai_job,
    update_ai_job,
    get_intercept_txt_push_state,
    set_intercept_txt_push_state,
    compute_intercept_word_delta,
    list_sync_outbox_pending,
    get_sync_meta,
)
from web_portal.lib.txt_push import post_json_text  # noqa: E402
from web_portal.lib.ai_client import current_ai_config  # noqa: E402
from web_portal.lib.ai_prompts import AI_PROMPT_VERSION  # noqa: E402
from web_portal.lib.ai_sessions import run_sessions_ai_analysis  # noqa: E402
from web_portal.lib.ai_agent_watch import (
    build_watch_snapshot,
    default_main_db_path,
    save_watch_state,
)


def _missing_optional(dep: str):
    def _raise(*_args, **_kwargs):
        raise RuntimeError(f"Опциональная зависимость '{dep}' недоступна в этой сборке")

    return _raise


try:
    from web_portal.lib.asr.dataset import (
        build_supervised_samples as asr_build_supervised_samples,
    )  # noqa: E402
    from web_portal.lib.asr.infer import (  # noqa: E402
        make_group_transcript_key,
        transcribe_audio_to_operator_ru,
        transcribe_track_segments_to_operator_blank,
    )
    from web_portal.lib.asr.learn_from_blank import learn_from_operator_blank  # noqa: E402
    from web_portal.lib.asr.runtime import asr_runtime  # noqa: E402
    from web_portal.lib.asr.train import train_whisper_adaptation  # noqa: E402
except Exception:
    asr_build_supervised_samples = _missing_optional("ASR")
    transcribe_audio_to_operator_ru = _missing_optional("ASR")
    transcribe_track_segments_to_operator_blank = _missing_optional("ASR")
    make_group_transcript_key = _missing_optional("ASR")
    learn_from_operator_blank = _missing_optional("ASR")
    asr_runtime = None
    train_whisper_adaptation = _missing_optional("ASR")

try:
    from web_portal.lib.ml.features import (  # noqa: E402
        FEATURE_ORDER,
        build_snapshots as ml_build_snapshots,
        build_forecast_samples as ml_build_forecast_samples,
        vectorize_feature_dict as ml_vectorize_feature_dict,
    )
    from web_portal.lib.ml.train import (
        train_multiclass as ml_train_multiclass,
    )  # noqa: E402
    from web_portal.lib.ml.predict import (
        predict_probabilities as ml_predict_probabilities,
    )  # noqa: E402
    from web_portal.lib.ml.model import (
        save_checkpoint as ml_save_checkpoint,
    )  # noqa: E402
    from web_portal.lib.ml.explain import (  # noqa: E402
        explain_feature_contributions as ml_explain_feature_contributions,
        explain_hotspots as ml_explain_hotspots,
    )
except Exception:
    FEATURE_ORDER = []
    ml_build_snapshots = _missing_optional("ML")
    ml_build_forecast_samples = _missing_optional("ML")
    ml_vectorize_feature_dict = _missing_optional("ML")
    ml_train_multiclass = _missing_optional("ML")
    ml_predict_probabilities = _missing_optional("ML")
    ml_save_checkpoint = _missing_optional("ML")
    ml_explain_feature_contributions = _missing_optional("ML")
    ml_explain_hotspots = _missing_optional("ML")
from web_portal.lib.aviation_db import normalize_aviation_work_date
from web_portal.app_perf import perf_route as _perf_route, perf_span as _perf_span
from web_portal.lib.background_jobs import default_runner as _background_jobs  # noqa: E402
from web_portal.lib.heavy_workers import run_sync_pull_blocking as _run_sync_pull_blocking  # noqa: E402
from web_portal.lib.sync_pull_builder import build_sync_pull_payload as _build_sync_pull_payload  # noqa: E402
from web_portal.lib.export_jobs import (
    create_export_job as _create_export_job,
    export_job_max_queue_sec as _export_job_max_queue_sec,
    export_job_max_runtime_sec as _export_job_max_runtime_sec,
    get_export_job as _get_export_job,
    update_export_job as _update_export_job,
)
from web_portal.lib.export_jobs_embedded import (  # noqa: E402
    run_export_job_by_id as _run_export_job_by_id,
    start_embedded_export_jobs_worker as _start_embedded_export_jobs_worker,
    submit_export_task as _submit_export_task,
)
from web_portal.lib.export_job_builders import (
    build_aviation_word_export as _build_aviation_word_export,
    build_intercepts_docx_export as _build_intercepts_docx_export,
    build_sessions_excel_export as _build_sessions_excel_export,
    build_sessions_word_export as _build_sessions_word_export,
)
from web_portal.app_runtime_caches import (
    intercepts_state_cache_clear as _intercepts_state_cache_clear,
    intercept_item_live_bump as _intercept_item_live_bump,
)
from web_portal.positions import (  # noqa: E402
    allowed_positions_for_current_user,
    can_edit_session_unit_name,
    current_user_position_role,
    get_selected_position,
    require_position_role,
)
from web_portal.webapp.httputils import json_etag_response  # noqa: E402
from web_portal.webapp.context import AppContext  # noqa: E402
from web_portal.webapp.routes.admin import register_admin_routes  # noqa: E402
from web_portal.webapp.routes.auth_pages import register_auth_pages_routes  # noqa: E402
from web_portal.webapp.routes.aviation import register_aviation_routes  # noqa: E402
from web_portal.webapp.routes.analysis import register_analysis_routes  # noqa: E402
from web_portal.webapp.routes.chat import register_chat_routes  # noqa: E402
from web_portal.webapp.routes.crypto import register_crypto_routes
from web_portal.webapp.routes.intercepts import register_intercepts_routes
from web_portal.webapp.routes.jobs import register_jobs_routes  # noqa: E402
from web_portal.webapp.routes.misc import register_misc_routes  # noqa: E402
from web_portal.webapp.routes.shell import register_shell_routes  # noqa: E402
from web_portal.webapp.routes.sync_api import register_sync_routes  # noqa: E402
from web_portal.webapp.routes.updates import register_update_routes  # noqa: E402
from web_portal.webapp.routes.online_search import (  # noqa: E402
    register_online_search_routes,
)
from web_portal.webapp.routes.sessions import register_sessions_routes  # noqa: E402
from web_portal.webapp.security import (  # noqa: E402
    CSRF_SAFE_METHODS,
    LoginRateLimiter,
    csrf_request_valid,
    ensure_csrf_token,
    resolve_secret_key,
)
from web_portal.webapp.timeutils import _utc_now_str
from web_portal.webapp.auth import (
    PortalUser,
    _mobile_primary_url,
    _request_is_mobile_shell,
    _request_wants_json,
    require_perm,
    require_tab,
)
from web_portal.webapp.seans_watch import (
    _launch_global_seans_watch_worker,
    _read_seans_watch_autostart,
)






def create_app() -> Flask:
    # Настраиваем логирование СРАЗУ, чтобы все логи работали
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,  # Переопределяем, если уже было настроено
    )
    from web_portal.lib.portal_event_log import (  # noqa: E402
        init_portal_event_log as _init_portal_event_log,
        install_request_event_logging as _install_request_event_logging,
        log_portal_event as _log_portal_event,
        setup_portal_file_logging as _setup_portal_file_logging,
    )

    _setup_portal_file_logging()
    logger = logging.getLogger(__name__)
    logger.info("=" * 60)
    logger.info("Инициализация приложения web_portal")
    logger.info("=" * 60)

    try:
        from web_portal.lib.ai_env import apply_ai_env_from_config

        for cfg_name in ("hub_config.json", "server_config.json"):
            cfg_path = (BASE_DIR / cfg_name).resolve()
            if cfg_path.exists():
                import json as _json

                apply_ai_env_from_config(_json.loads(cfg_path.read_text(encoding="utf-8") or "{}"))
                logger.info("AI config loaded from %s", cfg_path.name)
                break
    except Exception as exc:
        logger.warning("AI config from JSON skipped: %s", exc)

    try:
        from web_portal.lib.network_summary_export import apply_intensity_template_env

        tpl = apply_intensity_template_env(BASE_DIR)
        if tpl is not None:
            logger.info("Шаблон Excel (учёт интенсивности): %s", tpl)
    except Exception as exc:
        logger.warning("Autodetect intensity template skipped: %s", exc)

    # PyInstaller (onedir): ресурсы оказываются в dist/HUB/_internal/...
    def _find_resource_base() -> Path:
        candidates: list[Path] = []
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.append(Path(meipass).resolve())
        if getattr(sys, "frozen", False) and getattr(sys, "executable", ""):
            candidates.append(
                (Path(sys.executable).resolve().parent / "_internal").resolve()
            )
        candidates.append(Path(__file__).resolve().parent)
        candidates.append(BASE_DIR)

        for c in candidates:
            if (c / "templates").exists() and (c / "static").exists():
                return c
        # fallback: первый кандидат
        return candidates[0] if candidates else BASE_DIR

    base = _find_resource_base()
    app = Flask(
        __name__,
        static_folder=str((base / "static").resolve()),
        template_folder=str((base / "templates").resolve()),
    )
    app.config["JSON_AS_ASCII"] = False
    app.teardown_appcontext(close_request_dbs)
    app.secret_key = resolve_secret_key(DATA_DIR)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["REMEMBER_COOKIE_HTTPONLY"] = True
    app.config["REMEMBER_COOKIE_SAMESITE"] = "Lax"
    # sync (hub <-> server): на hub задаём апстрим и ключ
    SYNC_KEY = (os.environ.get("WEB_PORTAL_SYNC_KEY") or "").strip()
    SYNC_UPSTREAM = (
        (os.environ.get("WEB_PORTAL_SYNC_UPSTREAM") or "").strip().rstrip("/")
    )
    SYNC_POSITIONS_RAW = (
        (os.environ.get("WEB_PORTAL_SYNC_POSITIONS") or "")
        or (os.environ.get("WEB_PORTAL_SYNC_POSITION") or "")
    ).strip()
    SYNC_POSITIONS = [p.strip() for p in SYNC_POSITIONS_RAW.split(",") if p.strip()]
    SYNC_SEANSES = (os.environ.get("WEB_PORTAL_SYNC_SEANSES") or "").strip().lower()
    SYNC_SEANSES_ENABLED = SYNC_SEANSES not in {"0", "false", "no", "off"}
    INTERCEPT_FORWARD_URL = (
        (os.environ.get("WEB_PORTAL_INTERCEPT_FORWARD_URL") or "").strip().rstrip("/")
    )
    INTERCEPT_FORWARD_KEY = (
        os.environ.get("WEB_PORTAL_INTERCEPT_FORWARD_KEY") or ""
    ).strip()
    try:
        INTERCEPT_FORWARD_TIMEOUT_SEC = float(
            os.environ.get("WEB_PORTAL_INTERCEPT_FORWARD_TIMEOUT_SEC") or "6"
        )
    except Exception:
        INTERCEPT_FORWARD_TIMEOUT_SEC = 6.0
    # делаем доступными в роутах через app.config
    app.config["SYNC_KEY"] = SYNC_KEY
    app.config["SYNC_UPSTREAM"] = SYNC_UPSTREAM
    app.config["SYNC_POSITIONS"] = SYNC_POSITIONS
    app.config["SYNC_SEANSES_ENABLED"] = SYNC_SEANSES_ENABLED
    app.config["INTERCEPT_FORWARD_URL"] = INTERCEPT_FORWARD_URL
    app.config["INTERCEPT_FORWARD_KEY"] = INTERCEPT_FORWARD_KEY
    app.config["INTERCEPT_FORWARD_TIMEOUT_SEC"] = INTERCEPT_FORWARD_TIMEOUT_SEC

    def _maybe_forward_intercept_payload(
        conn: sqlite3.Connection, payload: dict | None
    ) -> None:
        """
        Сервер: отправка только новых строк перехвата на внешний получатель.
        """
        target_url = str(app.config.get("INTERCEPT_FORWARD_URL") or "").strip()
        if not target_url:
            return
        p = payload or {}
        item_uuid = str(p.get("uuid") or "").strip()
        content = str(p.get("content") or "")
        if not item_uuid or not content.strip():
            return
        try:
            last_sent_min = get_intercept_txt_push_state(conn, item_uuid=item_uuid)
            delta_text, new_last_sent_min = compute_intercept_word_delta(
                content=content,
                last_sent_min=last_sent_min,
            )
            if not delta_text.strip():
                return
            out_payload = {
                "event": "intercepts:item",
                "item_uuid": item_uuid,
                "session_uuid": str(p.get("session_uuid") or ""),
                "position_name": str(p.get("position_name") or ""),
                "unit_name": str(p.get("unit_name") or ""),
                "frequency": str(p.get("frequency") or ""),
                "group_code": str(p.get("group_code") or ""),
                "updated_by": str(p.get("updated_by") or ""),
                "updated_at": str(p.get("updated_at") or ""),
                "delta_text": delta_text,
                "full_content": content,
            }
            headers = {}
            forward_key = str(app.config.get("INTERCEPT_FORWARD_KEY") or "").strip()
            if forward_key:
                headers["X-Intercept-Key"] = forward_key
            ok, err = post_json_text(
                server_url=target_url,
                endpoint_path="/api/intercepts/telegram",
                payload=out_payload,
                headers=headers,
                timeout_sec=float(app.config.get("INTERCEPT_FORWARD_TIMEOUT_SEC") or 6),
            )
            if ok:
                set_intercept_txt_push_state(
                    conn,
                    item_uuid=item_uuid,
                    last_sent_min=new_last_sent_min,
                    last_error="",
                )
                return
            set_intercept_txt_push_state(
                conn,
                item_uuid=item_uuid,
                last_sent_min=last_sent_min,
                last_error=str(err or "")[:500],
            )
        except Exception:
            _log.debug("_maybe_forward_intercept_payload: suppressed error", exc_info=True)

    def _forward_intercept_payload_async(
        _conn: sqlite3.Connection, payload: dict | None
    ) -> None:
        """Не блокируем сохранение бланка HTTP-запросом на внешний получатель."""
        p = payload or {}
        if not str(p.get("uuid") or "").strip():
            return

        def _worker() -> None:
            try:
                dbp = db_path(DEFAULT_DB_NAME)
                ensure_db(dbp)
                bg = connect(dbp)
                try:
                    _maybe_forward_intercept_payload(bg, p)
                finally:
                    bg.close()
            except Exception:
                _log.debug("_worker: suppressed error", exc_info=True)

        threading.Thread(target=_worker, daemon=True, name="intercept-forward").start()

    def _bump_intercept_item_live(
        item_id: int, *, updated_at: str, content: str
    ) -> None:
        iid = int(item_id or 0)
        if iid <= 0:
            return
        sig = normalize_intercept_item_content_sig(
            compute_intercept_item_content_sig(
                str(updated_at or ""),
                str(content or ""),
            )
        )
        _intercept_item_live_bump(iid, item_sig=sig, updated_at=str(updated_at or ""))

    def _bump_intercept_item_live_from_sync(conn: sqlite3.Connection, payload: dict) -> None:
        p = payload or {}
        item_uuid = str(p.get("uuid") or "").strip()
        updated_at = str(p.get("updated_at") or "")
        content = str(p.get("content") or "")
        if not item_uuid:
            return
        try:
            row = conn.execute(
                "SELECT id FROM intercept_items WHERE uuid=? LIMIT 1",
                (item_uuid,),
            ).fetchone()
            if row:
                _bump_intercept_item_live(
                    int(row["id"]),
                    updated_at=updated_at,
                    content=content,
                )
        except Exception:
            _log.debug("_bump_intercept_item_live_from_sync: suppressed error", exc_info=True)

    # helper для проверки sync режима в роутах (доступна через замыкание)


    # ---- Proxy: хаб проксирует запросы перехватов чужих позиций на сервер ----
    import urllib.request as _urlreq
    import urllib.error as _urlerr

    def _proxy_to_upstream(upstream: str, position_name: str):
        """Forward the current Flask request to the upstream server.

        Copies method, path, query-string, body and adds
        ``X-Sync-Key`` + ``_proxy_position`` so the server knows
        which position to query. Returns a Flask ``Response`` built
        from the upstream answer.
        """
        # build target URL
        qs_parts: list[str] = []
        for k, v in request.args.items():
            qs_parts.append(
                f"{_urlreq.quote(str(k), safe='')}={_urlreq.quote(str(v), safe='')}"
            )
        qs_parts.append(f"_proxy_position={_urlreq.quote(position_name, safe='')}")
        target_url = f"{upstream}{request.path}"
        if qs_parts:
            target_url += "?" + "&".join(qs_parts)

        # body (for POST / PUT / PATCH)
        body_bytes: bytes | None = None
        if request.method in ("POST", "PUT", "PATCH"):
            body_bytes = request.get_data(as_text=False)

        hdrs = {
            "Content-Type": request.content_type or "application/json",
            "X-Sync-Key": SYNC_KEY,
        }
        req = _urlreq.Request(
            url=target_url,
            data=body_bytes,
            method=request.method,
            headers=hdrs,
        )
        try:
            with _urlreq.urlopen(req, timeout=10) as resp:
                resp_body = resp.read()
                ct = resp.headers.get("Content-Type", "application/json")
                return app.response_class(
                    response=resp_body,
                    status=resp.status,
                    content_type=ct,
                )
        except _urlerr.HTTPError as e:
            resp_body = b"{}"
            try:
                resp_body = e.read() or b"{}"
            except Exception:
                _log.debug("_proxy_to_upstream: suppressed error", exc_info=True)
            return app.response_class(
                response=resp_body,
                status=e.code,
                content_type="application/json",
            )
        except Exception as exc:
            return jsonify({"ok": False, "error": f"proxy error: {exc}"}), 502

    @app.before_request
    def _maybe_proxy_intercepts():
        """Hub: если выбрана чужая позиция — проксируем /api/intercepts/* на сервер."""
        if not request.path.startswith("/api/intercepts/"):
            return None
        # Аудиоперехваты (audio/state, audio/tasks, audio/list, audio/file и т.п.)
        # всегда обрабатываем ЛОКАЛЬНО на хабе, даже для "чужих" позиций,
        # т.к. путь к папке и сканирование файлов завязаны на файловую систему хаба.
        if request.path.startswith("/api/intercepts/audio/"):
            return None
        if not SYNC_UPSTREAM or not SYNC_KEY:
            return None  # это сервер, не хаб (или синк не настроен)
        if not SYNC_POSITIONS:
            return None  # позиции не заданы — работаем как раньше
        if not current_user.is_authenticated:
            return None  # не авторизован — пусть обработчик сам вернёт 401
        pos = get_selected_position()
        if not pos or pos in SYNC_POSITIONS:
            return None  # своя позиция — обрабатываем локально
        # Чужая позиция — проксируем на upstream-сервер
        return _proxy_to_upstream(SYNC_UPSTREAM, pos)

    # ---- Server: поддержка проксированных запросов от хабов ----
    @app.before_request
    def _auth_proxy_request():
        """Если запрос пришёл с валидным X-Sync-Key и _proxy_position,
        авторизуем его как служебного администратора, чтобы @login_required
        и @require_perm не блокировали."""
        sync_key = app.config.get("SYNC_KEY")
        if not sync_key:
            return None
        req_key = (request.headers.get("X-Sync-Key") or "").strip()
        if not req_key or not hmac.compare_digest(req_key, str(sync_key)):
            return None
        proxy_pos = (request.args.get("_proxy_position") or "").strip()
        if not proxy_pos:
            return None  # обычный sync-запрос, не proxy
        # Только для /api/intercepts/* — не для sync push/pull
        if not request.path.startswith("/api/intercepts/"):
            return None
        # Создаём синтетического админа для Flask-Login
        _proxy_rec = UserRecord(
            id=0,
            username="__hub_proxy__",
            callsign="proxy",
            role="admin",
            permissions=None,
        )
        _proxy_user = PortalUser(_proxy_rec)
        login_user(_proxy_user, remember=False)
        # Устанавливаем позицию в сессию, чтобы get_selected_position() её вернул
        session["position"] = proxy_pos

    # Функционал сеансов полностью удален

    # если это HUB (задан upstream) — запускаем фоновую синхронизацию
    if SYNC_UPSTREAM and SYNC_KEY:
        curr_series = []
        prev_series = []
        try:
            from web_portal.lib.sync_agent import run_sync_loop  # noqa: E402

            sync_interval_raw = (os.environ.get("WEB_PORTAL_SYNC_INTERVAL_SEC") or "5").strip()
            try:
                sync_interval_sec = max(3.0, min(120.0, float(sync_interval_raw)))
            except ValueError:
                sync_interval_sec = 5.0

            t = threading.Thread(
                target=run_sync_loop,
                kwargs={
                    "upstream_base": SYNC_UPSTREAM,
                    "sync_key": SYNC_KEY,
                    "interval_sec": sync_interval_sec,
                    "position_names": SYNC_POSITIONS,
                    "include_seanses": SYNC_SEANSES_ENABLED,
                },
                daemon=True,
            )
            t.start()
        except Exception:
            # не критично, портал должен работать и без синка
            pass

    # портал пользователей
    pconn = connect_portal(portal_db_path())
    try:
        ensure_default_admin(pconn)
        _init_portal_event_log(pconn)
    finally:
        pconn.close()

    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.init_app(app)

    # --- realtime typing (in-memory) ---
    # key: (position_name, session_id, catalog_id) -> { username: {"ts": float, "time_header": str} }


    _json_etag_response = json_etag_response

    @login_manager.user_loader
    def load_user(user_id: str):
        conn = connect_portal(portal_db_path())
        try:
            u = get_user_by_id(conn, int(user_id))
            return PortalUser(u) if u else None
        finally:
            conn.close()


    @app.after_request
    def _security_headers(resp):
        h = resp.headers
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        # Портал — аутентифицированный UI; встраивание в чужие iframe не нужно.
        h.setdefault("X-Frame-Options", "SAMEORIGIN")
        # Камера/микрофон/геолокация в приложении не используются.
        h.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        return resp

    @app.context_processor
    def inject_csrf_token():
        if not current_user.is_authenticated:
            return {"csrf_token": ""}
        return {"csrf_token": ensure_csrf_token(session)}

    @app.before_request
    def _csrf_protect():
        """CSRF-проверка для изменяющих запросов от сессионных пользователей.

        Запросы без сессии (sync-хаб с X-Sync-Key, telegram-приёмник) не несут
        cookie-авторизации, поэтому CSRF к ним неприменим и они не проверяются.
        """
        if request.method in CSRF_SAFE_METHODS:
            return None
        if not current_user.is_authenticated:
            return None
        if request.endpoint in ("login", "static"):
            # повторный вход уже залогиненного пользователя защищён паролем
            return None
        if csrf_request_valid(session, request):
            return None
        _log_portal_event(
            level="WARNING",
            category="security",
            action="csrf_rejected",
            message=f"CSRF-токен отсутствует/неверен: {request.path}",
            username=str(getattr(current_user, "username", "") or ""),
            ip=str(request.remote_addr or ""),
            path=str(request.path or ""),
            method=str(request.method or ""),
        )
        return jsonify({"ok": False, "error": "CSRF-токен отсутствует или неверен"}), 403

    @app.context_processor
    def inject_positions():
        if not current_user.is_authenticated:
            return {}
        allowed = allowed_positions_for_current_user()
        selected = get_selected_position()
        # Проверяем, является ли пользователь chief или admin для доступа к импорту/автопоиску
        can_import = False
        if current_user.role == "admin":
            can_import = True
        elif selected:
            pos_role = current_user_position_role(selected)
            can_import = pos_role == "chief" or pos_role == "admin"
        can_export_sessions = False
        if current_user.role == "admin":
            can_export_sessions = True
        elif selected:
            can_export_sessions = require_position_role(selected, "export")
        can_edit_session_unit = can_edit_session_unit_name()
        return {
            "allowed_positions": allowed,
            "selected_position": selected,
            "can_import_folder": can_import,
            "can_export_sessions": can_export_sessions,
            "can_edit_session_unit": can_edit_session_unit,
        }


    def _require_agent_token() -> bool:
        token_expected = os.environ.get("WEB_PORTAL_AGENT_TOKEN", "").strip()
        if not token_expected:
            # если токен не задан — запрещаем агентский вход
            return False
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()
        else:
            token = (request.args.get("token") or "").strip()
        return token == token_expected


    login_rate_limiter = LoginRateLimiter()

    # --- Targeting API ---



    # --- Перехваты API ---

    # --- Анализ API ---

    def _ai_created_by() -> str:
        return str(
            getattr(current_user, "callsign", "")
            or getattr(current_user, "username", "")
            or getattr(current_user, "id", "")
            or ""
        )

    def _create_ai_job_record(
        *, task_type: str, position_name: str, params: dict[str, object], created_by: str
    ) -> int:
        cfg = current_ai_config()
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            return create_ai_job(
                conn,
                task_type=task_type,
                position_name=str(position_name or ""),
                params=params,
                model_name=cfg.model,
                prompt_version=AI_PROMPT_VERSION,
                created_by=created_by,
            )
        finally:
            conn.close()

    def _submit_ai_job(job_id: int, name: str, fn) -> tuple[dict[str, object], int]:
        accepted = _background_jobs.submit(name, fn)
        if accepted:
            return {"ok": True, "job_id": int(job_id), "queued": True}, 202
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            update_ai_job(
                conn,
                int(job_id),
                status="failed",
                error_text="Очередь фоновых задач переполнена. Повторите запуск позже.",
            )
        finally:
            conn.close()
        return {
            "ok": False,
            "job_id": int(job_id),
            "error": "Очередь фоновых задач переполнена. По��торите запуск позже.",
        }, 503

    def _create_export_job_record(
        *, job_type: str, position_name: str, params: dict[str, object], created_by: str
    ) -> int:
        p = db_path(DEFAULT_DB_NAME)
        ensure_db(p)
        conn = connect(p)
        try:
            return _create_export_job(
                conn,
                job_type=job_type,
                position_name=str(position_name or ""),
                params=params,
                created_by=created_by,
            )
        finally:
            conn.close()

    def _submit_export_job(
        job_id: int, name: str, build_fn
    ) -> tuple[dict[str, object], int]:
        jid = int(job_id)
        accepted = _submit_export_task(
            name,
            lambda j=jid, bf=build_fn: _run_export_job_by_id(BASE_DIR, j, bf),
        )
        return {"ok": True, "job_id": jid, "queued": True, "worker": accepted}, 202

    def _can_view_export_position(position_name: str) -> bool:
        pos = str(position_name or "").strip()
        if pos == "__all__":
            return bool(current_user.role == "admin")
        if not pos:
            return False
        return bool(require_position_role(pos, "view"))

    def _build_sessions_word_export_result(job_id: int, params: dict[str, object]) -> dict[str, object]:
        return _build_sessions_word_export(BASE_DIR, job_id, params)

    def _build_sessions_excel_export_result(job_id: int, params: dict[str, object]) -> dict[str, object]:
        return _build_sessions_excel_export(BASE_DIR, job_id, params)

    def _build_intercepts_docx_export_result(job_id: int, params: dict[str, object]) -> dict[str, object]:
        return _build_intercepts_docx_export(BASE_DIR, job_id, params)


    def _build_aviation_word_export_result(job_id: int, params: dict[str, object]) -> dict[str, object]:
        return _build_aviation_word_export(BASE_DIR, job_id, params)

    _export_job_resubmit_once: set[int] = set()

    def _resubmit_export_job_if_possible(job: dict[str, object]) -> bool:
        """Повторная постановка только для зависших pending (после рестарта процесса)."""
        status = str(job.get("status") or "").lower()
        if status != "pending":
            return False
        if str(job.get("started_at") or "").strip():
            return False
        job_id = int(job.get("id") or 0)
        if not job_id or job_id in _export_job_resubmit_once:
            return False
        job_type = str(job.get("job_type") or "")
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        from web_portal.lib.export_job_builders import (
            build_analysis_callsigns_export,
            build_analysis_full_report_docx,
            build_analysis_network_summary_export,
        )

        def _build_analysis_callsigns_export_result(job_id: int, params: dict[str, object]) -> dict[str, object]:
            return build_analysis_callsigns_export(BASE_DIR, job_id, params)

        def _build_analysis_full_report_export_result(job_id: int, params: dict[str, object]) -> dict[str, object]:
            return build_analysis_full_report_docx(BASE_DIR, job_id, params)

        def _build_analysis_network_summary_export_result(job_id: int, params: dict[str, object]) -> dict[str, object]:
            return build_analysis_network_summary_export(BASE_DIR, job_id, params)

        builders = {
            "sessions_word": _build_sessions_word_export_result,
            "sessions_excel": _build_sessions_excel_export_result,
            "intercepts_docx": _build_intercepts_docx_export_result,
            "analysis_callsigns": _build_analysis_callsigns_export_result,
            "analysis_full_report": _build_analysis_full_report_export_result,
            "analysis_network_summary": _build_analysis_network_summary_export_result,
            "aviation_word": _build_aviation_word_export_result,
        }
        builder = builders.get(job_type)
        if builder is None:
            return False
        payload, status_code = _submit_export_job(
            job_id,
            f"recover-{job_type}",
            lambda: builder(job_id, params),
        )
        if payload.get("ok") and status_code == 202:
            _export_job_resubmit_once.add(job_id)
            return True
        return False

    def _xml_find_callsign(root: ET.Element, callsign_id: str) -> ET.Element | None:
        cid = str(callsign_id or "").strip()
        if not cid:
            return None
        for cs in root.findall("callsign"):
            cid_node = cs.find("id")
            if cid_node is not None and str(cid_node.text or "").strip() == cid:
                return cs
        return None




    def _xml_create_callsign(root: ET.Element, callsign_id: str) -> ET.Element:
        cs = ET.Element("callsign")
        cid = ET.SubElement(cs, "id")
        cid.text = str(callsign_id or "").strip()
        comment = ET.SubElement(cs, "comment")
        comment.text = ""
        root.append(cs)
        return cs








    def _ml_get_active_model(conn: sqlite3.Connection) -> sqlite3.Row | None:
        return conn.execute(
            """
            SELECT model_version, labels_json, feature_spec_json, metrics_json, artifact_path
            FROM ml_models
            WHERE is_active=1
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()


    # ========== Aviation API ==========



    def _bg_autostart_seans_watch() -> None:
        import time as _time

        _time.sleep(2.0)
        try:
            raw = _read_seans_watch_autostart()
            if not raw or not raw.get("enabled"):
                return
            pos = str(raw.get("position_name") or "").strip()
            fp = str(raw.get("folder_path") or "").strip()
            if not pos or not fp:
                return
            from web_portal.lib.safe_paths import probe_path

            probe = probe_path(fp)
            if not probe.ok or not probe.is_dir:
                return
            try:
                iv = float(raw.get("interval_sec") or 5)
            except Exception:
                iv = 5.0
            iv = max(1.0, min(60.0, iv))
            out = _launch_global_seans_watch_worker(app, pos, fp, iv)
            if out.get("ok"):
                logging.getLogger("web_portal.sessions").info(
                    "Автопоиск сеансов восстановлен после старта приложения: %s",
                    out.get("message") or "",
                )
        except Exception as exc:
            logging.getLogger("web_portal.sessions").warning(
                "seans watch autostart: %s", exc
            )

    threading.Thread(target=_bg_autostart_seans_watch, daemon=True).start()

    def _bg_seans_db_startup_hint() -> None:
        import time as _time_hint

        _time_hint.sleep(1.5)
        try:
            from web_portal.lib.seans_migrate import log_startup_seans_db_hint

            log_startup_seans_db_hint(logger)
        except Exception:
            _log.debug("_bg_seans_db_startup_hint: suppressed error", exc_info=True)

    threading.Thread(target=_bg_seans_db_startup_hint, daemon=True).start()

    def _bg_ai_agent_watch() -> None:
        import time as _time

        raw = (os.environ.get("WEB_PORTAL_AI_WATCH_INTERVAL_SEC") or "").strip()
        if not raw:
            return
        try:
            interval = max(60.0, float(raw))
        except Exception:
            interval = 3600.0
        _time.sleep(8.0)
        log_ai = logging.getLogger("web_portal.ai_agent_watch")
        while True:
            try:
                with app.app_context():
                    pconn = connect_portal(portal_db_path())
                    try:
                        snap = build_watch_snapshot(pconn, default_main_db_path())
                        save_watch_state(snap)
                        log_ai.debug(
                            "watch snapshot: actions_24h=%s",
                            snap.get("actions_total_24h"),
                        )
                    finally:
                        pconn.close()
            except Exception as exc:
                log_ai.warning("background watch: %s", exc)
            _time.sleep(interval)

    threading.Thread(target=_bg_ai_agent_watch, daemon=True).start()

    from web_portal.lib.request_hang_watchdog import install_request_hang_watchdog

    install_request_hang_watchdog(app)
    _install_request_event_logging(app)

    from web_portal.lib.admin_event_log_routes import register_admin_event_log_routes

    register_admin_event_log_routes(
        app,
        require_perm=require_perm,
        connect_portal=connect_portal,
        portal_db_path=portal_db_path,
        log_portal_event=_log_portal_event,
    )

    _start_embedded_export_jobs_worker(BASE_DIR)

    try:
        if asr_runtime is not None:
            asr_runtime.schedule_bootstrap("small")
    except Exception:
        logging.getLogger("web_portal.asr").warning(
            "ASR bootstrap scheduling failed", exc_info=True
        )

    # --- Единый DI-контекст и регистрация доменных маршрутов ---
    def _now_ts() -> str:
        # SQLite CURRENT_TIMESTAMP возвращает UTC, поэтому синк-таймстемпы держим в UTC.
        return _utc_now_str()

    ctx = AppContext(
        base_dir=BASE_DIR,
        sync_key=SYNC_KEY,
        sync_upstream=SYNC_UPSTREAM,
        ai_created_by=_ai_created_by,
        create_ai_job_record=_create_ai_job_record,
        submit_ai_job=_submit_ai_job,
        create_export_job_record=_create_export_job_record,
        submit_export_job=_submit_export_job,
        now_ts=_now_ts,
        build_intercepts_docx_export_result=_build_intercepts_docx_export_result,
        bump_intercept_item_live=_bump_intercept_item_live,
        bump_intercept_item_live_from_sync=_bump_intercept_item_live_from_sync,
        forward_intercept_payload_async=_forward_intercept_payload_async,
        intercepts_state_cache_clear=_intercepts_state_cache_clear,
        can_view_export_position=_can_view_export_position,
        resubmit_export_job_if_possible=_resubmit_export_job_if_possible,
        build_sessions_word_export_result=_build_sessions_word_export_result,
        build_sessions_excel_export_result=_build_sessions_excel_export_result,
        build_aviation_word_export_result=_build_aviation_word_export_result,
        login_rate_limiter=login_rate_limiter,
        log_portal_event=_log_portal_event,
    )

    register_misc_routes(app, ctx)
    register_aviation_routes(app, ctx)
    register_sessions_routes(app, ctx)
    register_admin_routes(app, ctx)
    register_chat_routes(app, ctx)
    register_online_search_routes(app, ctx)
    register_crypto_routes(app, ctx)
    register_intercepts_routes(app, ctx)
    register_analysis_routes(app, ctx)
    register_auth_pages_routes(app, ctx)
    register_shell_routes(app, ctx)
    register_jobs_routes(app, ctx)
    register_sync_routes(app, ctx)
    register_update_routes(app, ctx)

    return app


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--seans-watch-worker":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        from web_portal.seans_watch_child import main as _seans_watch_main

        _seans_watch_main()
        raise SystemExit(0)
    app = create_app()
    debug = os.environ.get("WEB_PORTAL_DEBUG", "0") == "1"
    port = int(os.environ.get("WEB_PORTAL_PORT", "5000"))
    from web_portal.lib.wsgi_server import run_wsgi_server

    run_wsgi_server(app, host="0.0.0.0", port=port, debug=debug)
