from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from awas.models import AuditLog, Recording, RecordingSchedule, Stream, User, WebSession
from awas.models.auth import utc_now
from awas.services.auth import create_user
from tests.conftest import form_token, login


def test_username_can_contain_period(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/users/new")
    assert 'pattern="[a-z][a-z0-9._-]{2,31}"' in page.text

    response = client.post(
        "/admin/users",
        data={
            "username": "radio.user",
            "display_name": "Radio User",
            "role": "user",
            "password": "x",
            "password_confirmation": "x",
            "csrf_token": form_token(page.text),
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with app.state.session_factory() as db:
        assert db.scalar(select(User).where(User.username == "radio.user")) is not None

    client.cookies.clear()
    signed_in = login(client, "RADIO.USER", "x")
    assert signed_in.status_code == 303
    assert signed_in.headers["location"] == "/account/password"


def test_admin_creates_and_disables_user(app: FastAPI, client: TestClient, admin) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/users/new")
    response = client.post(
        "/admin/users",
        data={
            "username": "operator",
            "display_name": "Operator",
            "role": "user",
            "password": "temporary-password-123",
            "password_confirmation": "temporary-password-123",
            "csrf_token": form_token(page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    listing = client.get("/admin/users")
    assert 'data-live-interval="5000"' in listing.text
    assert ">Ändern</a>" in listing.text
    assert "Verwalten" not in listing.text

    with app.state.session_factory() as db:
        operator = db.scalar(select(User).where(User.username == "operator"))
        assert operator is not None
        assert operator.must_change_password is True
        operator_id = operator.id

    detail = client.get(f"/admin/users/{operator_id}")
    disabled = client.post(
        f"/admin/users/{operator_id}/status",
        data={"enabled": "false", "csrf_token": form_token(detail.text)},
        follow_redirects=False,
    )
    assert disabled.status_code == 303
    with app.state.session_factory() as db:
        assert db.get(User, operator_id).is_active is False
        actions = list(db.scalars(select(AuditLog.action).order_by(AuditLog.id)))
        assert "user.created" in actions
        assert "user.disabled" in actions

    client.cookies.clear()
    rejected = login(client, "operator", "temporary-password-123")
    assert rejected.status_code == 401
    assert "Benutzername oder Passwort ist falsch" in rejected.text


def test_admin_deletes_user_and_retains_anonymous_attribution(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    now = utc_now()
    with app.state.session_factory() as db:
        operator = create_user(
            db,
            username="operator",
            display_name="Operator",
            password="temporary-password-123",
            password_confirmation="temporary-password-123",
            role="user",
            must_change_password=False,
        )
        operator_id = operator.id
        stream = Stream(
            name="Deletion Test",
            stream_url="https://radio.example/delete-test",
            created_by_id=operator_id,
        )
        db.add(stream)
        db.flush()
        upcoming = RecordingSchedule(
            stream_id=stream.id,
            title="Geplante Aufnahme",
            file_name_base="geplant",
            recorder="ffmpeg",
            file_type="mp3",
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            status="scheduled",
            created_by_id=operator_id,
        )
        history = RecordingSchedule(
            stream_id=stream.id,
            title="Historische Aufnahme",
            file_name_base="historisch",
            recorder="ffmpeg",
            file_type="mp3",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
            status="completed",
            created_by_id=operator_id,
        )
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name="historisch.mp3",
            recorder="ffmpeg",
            file_type="mp3",
            status="completed",
            started_at=history.starts_at,
            ended_at=history.ends_at,
            file_size_bytes=1234,
            started_by_id=operator_id,
            schedule=history,
        )
        db.add_all((upcoming, history, recording))
        db.add(
            WebSession(
                token_hash="d" * 64,
                user_id=operator_id,
                created_at=now,
                last_seen_at=now,
                expires_at=now + timedelta(hours=1),
            )
        )
        db.commit()
        upcoming_id = upcoming.id
        history_id = history.id
        recording_id = recording.id

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    listing = client.get("/admin/users")
    assert "Wirklich löschen?" in listing.text

    unconfirmed = client.post(
        f"/admin/users/{operator_id}/delete",
        data={
            "delete_confirmed": "",
            "csrf_token": form_token(listing.text),
        },
    )
    assert unconfirmed.status_code == 400
    with app.state.session_factory() as db:
        assert db.get(User, operator_id).deleted_at is None

    listing = client.get("/admin/users")
    deleted = client.post(
        f"/admin/users/{operator_id}/delete",
        data={
            "delete_confirmed": "true",
            "csrf_token": form_token(listing.text),
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/admin/users?status=deleted"

    with app.state.session_factory() as db:
        tombstone = db.get(User, operator_id)
        assert tombstone is not None
        assert tombstone.deleted_at is not None
        assert tombstone.display_name == "Gelöschter Benutzer"
        assert tombstone.username.startswith("deleted-")
        assert tombstone.username != "operator"
        assert tombstone.is_active is False
        assert tombstone.role == "user"
        assert tombstone.must_change_password is False
        assert tombstone.last_login_at is None
        assert db.scalar(select(User).where(User.username == "operator")) is None
        assert db.scalar(select(WebSession).where(WebSession.user_id == operator_id)) is None
        assert db.get(RecordingSchedule, upcoming_id).created_by.display_name == (
            "Gelöschter Benutzer"
        )
        assert db.get(RecordingSchedule, history_id).created_by.display_name == (
            "Gelöschter Benutzer"
        )
        assert db.get(Recording, recording_id).started_by.display_name == "Gelöschter Benutzer"
        assert db.scalar(
            select(AuditLog).where(
                AuditLog.action == "user.deleted",
                AuditLog.target_id == operator_id,
            )
        ) is not None

    listing = client.get("/admin/users")
    assert "@operator" not in listing.text
    assert "Operator" not in listing.text
    assert client.get(f"/admin/users/{operator_id}").status_code == 404
    assert "Gelöschter Benutzer" in client.get("/").text
    assert "Gelöschter Benutzer" in client.get("/history").text
    assert "Gelöschter Benutzer" in client.get("/recordings").text

    client.cookies.clear()
    rejected = login(client, "operator", "temporary-password-123")
    assert rejected.status_code == 401


def test_admin_cannot_delete_own_account(app: FastAPI, client: TestClient, admin) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    detail = client.get(f"/admin/users/{admin.id}")
    assert f'/admin/users/{admin.id}/delete' not in detail.text

    response = client.post(
        f"/admin/users/{admin.id}/delete",
        data={
            "delete_confirmed": "true",
            "csrf_token": form_token(detail.text),
        },
    )

    assert response.status_code == 400
    assert "eigene Konto kann nicht gelöscht" in response.text
    with app.state.session_factory() as db:
        assert db.get(User, admin.id).deleted_at is None


def test_normal_user_cannot_access_administration(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as db:
        create_user(
            db,
            username="listener",
            display_name="Listener",
            password="a-secure-listener-password",
            password_confirmation="a-secure-listener-password",
            role="user",
            must_change_password=False,
        )
    assert login(client, "listener", "a-secure-listener-password").status_code == 303
    response = client.get("/admin/users")
    assert response.status_code == 403
    assert "Administratorrechte" in response.text


def test_forced_password_change_invalidates_session(app: FastAPI, client: TestClient) -> None:
    with app.state.session_factory() as db:
        create_user(
            db,
            username="operator",
            display_name="Operator",
            password="temporary-password-123",
            password_confirmation="temporary-password-123",
            role="user",
            must_change_password=True,
        )
    signed_in = login(client, "operator", "temporary-password-123")
    assert signed_in.headers["location"] == "/account/password"
    page = client.get("/account/password")
    changed = client.post(
        "/account/password",
        data={
            "current_password": "temporary-password-123",
            "new_password": "a-new-secure-password-456",
            "new_password_confirmation": "a-new-secure-password-456",
            "csrf_token": form_token(page.text),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    assert changed.headers["location"] == "/login?status=password-changed"
    with app.state.session_factory() as db:
        user = db.scalar(select(User).where(User.username == "operator"))
        assert user.must_change_password is False
        assert db.scalar(select(WebSession).where(WebSession.user_id == user.id)) is None


def test_own_admin_account_cannot_be_disabled(client: TestClient, admin) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    detail = client.get(f"/admin/users/{admin.id}")
    response = client.post(
        f"/admin/users/{admin.id}/status",
        data={"enabled": "false", "csrf_token": form_token(detail.text)},
    )
    assert response.status_code == 400
    assert "eigene Konto" in response.text


def test_authenticated_csrf_is_required(client: TestClient, admin) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    response = client.post(
        f"/admin/users/{admin.id}/role",
        data={"role": "user", "csrf_token": "invalid"},
    )
    assert response.status_code == 403
