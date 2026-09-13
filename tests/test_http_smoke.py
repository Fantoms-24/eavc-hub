"""HTTP smoke-тесты: страховочная сетка перед рефакторингом app.py.

1. ``test_route_map_matches_snapshot`` — карта маршрутов (rule, endpoint,
   methods) сравнивается с эталонным снимком ``tests/route_map_snapshot.json``.
   Любое случайное переименование endpoint'а или изменение URL при выносе
   маршрутов в модули провалит тест. При отсутствии снимка он создаётся.

2. ``test_get_routes_do_not_500`` — логин под дефолтным админом и GET-обход
   всех маршрутов без обязательных path-параметров: ни один не должен
   вернуть 5xx.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

SNAPSHOT_PATH = Path(__file__).resolve().parent / "route_map_snapshot.json"

# GET-маршруты, которые нельзя дёргать в smoke-обходе.
SKIP_GET_RULES = {
    "/logout",  # разлогинит клиента посреди обхода
    # На Windows os.path.exists("D:\\") и т.п. может надолго зависнуть
    # на недоступных/сетевых дисках — не для smoke-сетки.
    "/api/pick-folder",
}

# Маршруты, которым разрешено отвечать 503 (сервис намеренно недоступен
# в окружении без опциональных ML/ASR-зависимостей).
ALLOWED_503_RULES = {
    "/api/intercepts/asr/bootstrap",
}


@pytest.fixture(scope="session")
def app():
    from web_portal.app import create_app

    application = create_app()
    application.config["TESTING"] = True
    return application


@pytest.fixture(scope="session")
def client(app):
    with app.test_client() as c:
        yield c


def _build_route_map(app) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for rule in app.url_map.iter_rules():
        methods = sorted(
            m for m in (rule.methods or set()) if m not in {"HEAD", "OPTIONS"}
        )
        result[f"{rule.rule} [{rule.endpoint}]"] = {
            "rule": rule.rule,
            "endpoint": rule.endpoint,
            "methods": methods,
        }
    return result


def test_route_map_matches_snapshot(app):
    current = _build_route_map(app)
    if not SNAPSHOT_PATH.is_file():
        SNAPSHOT_PATH.write_text(
            json.dumps(current, ensure_ascii=False, indent=1, sort_keys=True),
            encoding="utf-8",
        )
        pytest.skip("Снимок карты маршрутов создан; закоммитьте его как эталон.")
    snapshot = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))

    missing = sorted(set(snapshot) - set(current))
    added = sorted(set(current) - set(snapshot))
    changed = sorted(
        k for k in set(snapshot) & set(current) if snapshot[k] != current[k]
    )
    assert not missing and not changed, (
        f"Карта маршрутов разошлась со снимком.\n"
        f"Пропали: {missing[:10]}\nИзменились: {changed[:10]}\n"
        f"Если изменение намеренное — обновите tests/route_map_snapshot.json."
    )
    # Новые маршруты не ломают рефакторинг, но напомним обновить снимок.
    if added:
        pytest.skip(f"Появились новые маршруты (обновите снимок): {added[:10]}")


TEST_ADMIN_PASSWORD = "smoke-test-passw0rd"


def _login(client) -> None:
    # Первый вход меняет стандартный пароль (fixture session-scoped),
    # поэтому сначала пробуем уже сменённый, затем стандартный.
    resp = client.post(
        "/login",
        data={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        follow_redirects=False,
    )
    if resp.status_code not in (301, 302):
        resp = client.post(
            "/login",
            data={"username": "admin", "password": "admin"},
            follow_redirects=False,
        )
    # Успешный вход = redirect; страница с ошибкой = 200
    assert resp.status_code in (301, 302), (
        f"Не удалось войти под admin: status={resp.status_code}"
    )
    if "/force-password-change" in (resp.headers.get("Location") or ""):
        # Вход со стандартным паролем требует принудительной смены.
        page = client.get("/force-password-change")
        m = re.search(
            r'name="csrf_token"\s+value="([0-9a-f]+)"', page.get_data(as_text=True)
        )
        assert m, "На странице смены пароля нет csrf_token"
        resp = client.post(
            "/force-password-change",
            data={
                "new_password": TEST_ADMIN_PASSWORD,
                "confirm_password": TEST_ADMIN_PASSWORD,
                "csrf_token": m.group(1),
            },
            follow_redirects=False,
        )
        assert resp.status_code in (301, 302), (
            f"Принудительная смена пароля не сработала: status={resp.status_code}"
        )


def _iter_simple_get_rules(app):
    for rule in app.url_map.iter_rules():
        if "GET" not in (rule.methods or set()):
            continue
        if rule.arguments:  # требует path-параметры — пропускаем
            continue
        if rule.rule in SKIP_GET_RULES:
            continue
        if rule.endpoint == "static":
            continue
        yield rule


@pytest.mark.timeout(120)
def test_get_routes_do_not_500(app, client):
    _login(client)
    failures: list[str] = []
    for rule in _iter_simple_get_rules(app):
        resp = client.get(rule.rule)
        if resp.status_code == 503 and rule.rule in ALLOWED_503_RULES:
            continue
        if resp.status_code >= 500:
            failures.append(f"{rule.rule} [{rule.endpoint}] -> {resp.status_code}")
    assert not failures, "GET-маршруты вернули 5xx:\n" + "\n".join(failures)


def test_csrf_blocks_post_without_token(client):
    """Аутентифицированный POST без CSRF-токена отклоняется 403."""
    _login(client)
    resp = client.post("/api/chat/messages", json={"text": "csrf-check"})
    assert resp.status_code == 403, (
        f"POST без CSRF-токена должен вернуть 403, получили {resp.status_code}"
    )


def test_csrf_allows_post_with_token(client):
    """POST с корректным X-CSRF-Token проходит CSRF-проверку (не 403)."""
    _login(client)
    page = client.get("/", follow_redirects=True)
    m = re.search(
        r'name="csrf-token" content="([0-9a-f]+)"', page.get_data(as_text=True)
    )
    assert m, "В base.html нет meta csrf-token"
    resp = client.post(
        "/api/chat/messages",
        json={"text": "csrf-check"},
        headers={"X-CSRF-Token": m.group(1)},
    )
    assert resp.status_code != 403, "POST с корректным токеном не должен давать 403"


def test_security_headers_present(client):
    """Базовые security-заголовки присутствуют в ответах."""
    _login(client)
    resp = client.get("/", follow_redirects=True)
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "camera=()" in (resp.headers.get("Permissions-Policy") or "")
