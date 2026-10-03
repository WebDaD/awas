from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from awas.auth.tokens import HTTPS_LOGIN_CSRF_COOKIE, HTTPS_SESSION_COOKIE, SESSION_COOKIE
from awas.models import AuditLog, LoginAttempt, WebSession
from awas.models.auth import utc_now
from tests.conftest import form_token, login


def test_health_and_protected_pages(client: TestClient) -> None:
    planning = client.get("/", follow_redirects=False)
    history = client.get("/history", follow_redirects=False)
    health = client.get("/health")

    assert planning.status_code == 303
    assert planning.headers["location"].startswith("/login")
    assert history.status_code == 303
    assert history.headers["location"].startswith("/login")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "3.0.8", "database": "ok"}
    assert "frame-ancestors 'none'" in health.headers["content-security-policy"]
    assert health.headers["cache-control"] == "no-store"

    login_page = client.get("/login")
    assert 'rel="icon" type="image/png"' in login_page.text
    assert 'class="brand-mark"' in login_page.text
    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"] == "image/x-icon"
    stylesheet = client.get("/static/app.css")
    assert "--bg: #d8d7f5" in stylesheet.text
    assert "background: #3B35CE" in stylesheet.text
    assert ".page { width: 90%;" in stylesheet.text
    assert "--recording-active: #fde7dc" in stylesheet.text
    assert ".recording-active-row > td { background: var(--recording-active); }" in stylesheet.text
    assert ".brand-copy strong { font-size: 1.05rem; letter-spacing: 0; }" in stylesheet.text
    assert ".header-navigation { display: none;" in stylesheet.text
    assert (
        ".recording-file-row td, .stream-url-row td { padding-top: .65rem; border-top: 0; "
        "background: transparent; }"
    ) in stylesheet.text
    assert (
        ".recording-file-row, .stream-url-row { border-top: 0; padding-top: 0; }"
        in stylesheet.text
    )
    assert (
        ".recording-data-row-with-file.recording-active-row { padding-bottom: 0; }"
        in stylesheet.text
    )
    assert ".recording-file-row td > .recording-file-entry," in stylesheet.text
    assert ".recording-file-row td > .table-detail-line { grid-column: 2; }" in stylesheet.text
    assert ".stream-data-row.recording-active-row," in stylesheet.text
    assert (
        ".stream-url-row.recording-active-row { background: var(--recording-active); }"
        in stylesheet.text
    )
    assert "tr[hidden] { display: none; }" in stylesheet.text
    script = client.get("/static/app.js")
    assert "initializeMobileMenu" in script.text
    assert "window.confirm" not in script.text
    assert '[data-action-confirm]' in script.text
    assert "danger-confirm-blink" in stylesheet.text
    assert "resetActionConfirmation(button), 5000" in script.text
    assert (
        ".action-confirm-button > span { grid-area: 1 / 1; white-space: nowrap; }"
        in stylesheet.text
    )


def test_admin_can_login_and_logout(client: TestClient, admin) -> None:
    response = login(client, "admin", "a-secure-admin-password")

    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert "awas_session=" in response.headers["set-cookie"]
    assert "Secure" not in response.headers["set-cookie"]
    planning = client.get("/")
    assert planning.status_code == 200
    assert "<h1>Planung</h1>" in planning.text
    assert planning.text.index("<h2>Laufend (0)</h2>") < planning.text.index(
        "<h2>Anstehend (0)</h2>"
    )
    assert planning.text.index("<h2>Anstehend (0)</h2>") < planning.text.index(
        "<h2>Wiederholungen (0)</h2>"
    )
    assert 'data-live-interval="5000"' in planning.text
    assert 'data-menu-toggle' in planning.text
    assert 'aria-controls="main-navigation"' in planning.text
    assert ">Übersicht</a>" not in planning.text
    nav_labels = [">Planung</a>", ">Historie</a>", ">Streams</a>", ">Aufnahmen</a>"]
    nav_positions = [planning.text.index(label) for label in nav_labels]
    assert nav_positions == sorted(nav_positions)
    admin_labels = [">Einstellungen</a>", ">Rekorder</a>", ">Benutzer</a>"]
    admin_positions = [planning.text.index(label) for label in admin_labels]
    assert nav_positions[-1] < admin_positions[0]
    assert admin_positions == sorted(admin_positions)
    assert "Hallo" not in planning.text
    assert "Willkommen" not in planning.text
    assert "Grundsystem" not in planning.text
    assert "Bereit zur Aufnahme" not in planning.text

    history = client.get("/history")
    assert history.status_code == 200
    assert "<h1>Historie</h1>" in history.text

    logout = client.post(
        "/logout",
        data={"csrf_token": form_token(planning.text)},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert client.get("/", follow_redirects=False).status_code == 303


def test_login_rejects_external_redirect(client: TestClient, admin) -> None:
    page = client.get("/login?next=https://example.com")
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "a-secure-admin-password",
            "csrf_token": form_token(page.text),
            "next_url": "https://example.com",
        },
        follow_redirects=False,
    )
    assert response.headers["location"] == "/"


def test_login_csrf_is_required(client: TestClient, admin) -> None:
    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "a-secure-admin-password",
            "csrf_token": "invalid",
            "next_url": "/",
        },
    )
    assert response.status_code == 403
    assert "abgelaufen" in response.text


def test_login_is_rate_limited(app: FastAPI, client: TestClient, admin) -> None:
    for _ in range(3):
        response = login(client, "admin", "wrong-password")
        assert response.status_code == 401

    blocked = login(client, "admin", "a-secure-admin-password")
    assert blocked.status_code == 429
    assert "Zu viele Anmeldeversuche" in blocked.text

    with app.state.session_factory() as db:
        failed_attempts = db.scalar(
            select(func.count(LoginAttempt.id)).where(LoginAttempt.succeeded.is_(False))
        )
        assert failed_attempts == 3
        assert (
            db.scalar(select(func.count(AuditLog.id)).where(AuditLog.action == "login.blocked"))
            == 1
        )


def test_session_is_hashed_and_expiry_is_enforced(app: FastAPI, client: TestClient, admin) -> None:
    response = login(client, "admin", "a-secure-admin-password")
    assert response.status_code == 303
    raw_token = client.cookies.get(SESSION_COOKIE)
    assert raw_token

    with app.state.session_factory() as db:
        web_session = db.scalar(select(WebSession))
        assert web_session is not None
        assert web_session.token_hash != raw_token
        assert len(web_session.token_hash) == 64
        web_session.expires_at = utc_now() - timedelta(seconds=1)
        db.commit()

    dashboard = client.get("/", follow_redirects=False)
    assert dashboard.status_code == 303
    assert dashboard.headers["location"].startswith("/login")
    assert client.cookies.get(SESSION_COOKIE) is None


def test_https_uses_separate_secure_cookies(app: FastAPI, admin) -> None:
    with TestClient(app, base_url="https://testserver") as https_client:
        login_page = https_client.get("/login")
        login_cookie_header = login_page.headers["set-cookie"]
        assert f"{HTTPS_LOGIN_CSRF_COOKIE}=" in login_cookie_header
        assert "Secure" in login_cookie_header
        assert "Path=/" in login_cookie_header

        response = login(https_client, "admin", "a-secure-admin-password")

        assert response.status_code == 303
        assert f"{HTTPS_SESSION_COOKIE}=" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]
        assert https_client.cookies.get(HTTPS_SESSION_COOKIE)
        assert https_client.cookies.get(SESSION_COOKIE) is None
        assert https_client.get("/").status_code == 200


def test_https_ignores_the_http_session_cookie(app: FastAPI, admin) -> None:
    with TestClient(app, base_url="http://testserver") as http_client:
        assert login(http_client, "admin", "a-secure-admin-password").status_code == 303
        http_token = http_client.cookies.get(SESSION_COOKIE)
        assert http_token

    with TestClient(app, base_url="https://testserver") as https_client:
        https_client.cookies.set(SESSION_COOKIE, http_token)
        response = https_client.get("/", follow_redirects=False)

        assert response.status_code == 303
        assert response.headers["location"].startswith("/login")
