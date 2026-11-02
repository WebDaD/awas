from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from awas.auth.tokens import (
    csrf_from_session_token,
    session_cookie_name,
    user_filter_cookie_name,
)
from awas.models import RecordingSchedule
from awas.models.auth import utc_now
from awas.services.auth import create_user
from tests.conftest import form_token, login
from tests.test_recordings import create_finished_recording


@pytest.fixture
def filter_user(app: FastAPI):
    with app.state.session_factory() as db:
        return create_user(
            db,
            username="filter.user",
            display_name="Filterbenutzer",
            password="filter-user",
            password_confirmation="filter-user",
            role="user",
            must_change_password=False,
        )


def set_filter_cookie(client: TestClient, user_id: str, *, scope: str | None = None) -> None:
    https = client.base_url.scheme == "https"
    session = next(
        cookie for cookie in client.cookies.jar if cookie.name == session_cookie_name(https=https)
    )
    marker = scope or csrf_from_session_token(session.value)
    client.cookies.set(
        user_filter_cookie_name(https=https),
        f"{marker}.{user_id}",
        domain=session.domain,
        path="/",
    )


def assert_selected(client: TestClient, user_id: int) -> None:
    for path in ("/", "/history", "/recordings"):
        page = client.get(path)
        assert page.status_code == 200
        assert f'<option value="{user_id}" selected>' in page.text


def test_session_filter_is_shared_by_lists_and_survives_deleting_a_recording(
    app: FastAPI, client: TestClient, admin, filter_user
) -> None:
    recording_id, output = create_finished_recording(app, filter_user, with_schedule=True)
    now = utc_now()
    with app.state.session_factory() as db:
        db.add(
            RecordingSchedule(
                title="Andere Historie",
                starts_at=now - timedelta(hours=2),
                ends_at=now - timedelta(hours=1),
                status="completed",
                created_by_id=admin.id,
            )
        )
        db.commit()
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    set_filter_cookie(client, str(filter_user.id))
    assert_selected(client, filter_user.id)
    history = client.get("/history")
    assert "Stored schedule" in history.text and "Andere Historie" not in history.text
    page = client.get("/recordings")
    deleted = client.post(
        f"/recordings/{recording_id}/delete",
        data={"csrf_token": form_token(page.text), "delete_confirmed": "true"},
        follow_redirects=True,
    )
    assert deleted.status_code == 200
    assert not output.exists()
    assert f'<option value="{filter_user.id}" selected>' in deleted.text
    assert_selected(client, filter_user.id)
    with app.state.session_factory() as db:
        schedule_id = db.scalar(
            select(RecordingSchedule.id).where(RecordingSchedule.title == "Stored schedule")
        )
    page = client.get("/history")
    hidden = client.post(
        f"/schedules/{schedule_id}/delete",
        data={"csrf_token": form_token(page.text), "delete_confirmed": "true"},
        follow_redirects=True,
    )
    assert hidden.status_code == 200
    assert f'<option value="{filter_user.id}" selected>' in hidden.text
    assert_selected(client, filter_user.id)


def test_explicit_filter_in_history_url_overrides_the_saved_selection(
    client: TestClient, admin, filter_user
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    set_filter_cookie(client, str(filter_user.id))
    page = client.get(f"/history?user_id={admin.id}")
    assert f'<option value="{admin.id}" selected>' in page.text
    all_users = client.get("/history?user_id=")
    assert '<option value="" selected>Alle</option>' in all_users.text
    set_filter_cookie(client, "all")
    for path in ("/", "/history", "/recordings"):
        assert f'<option value="{filter_user.id}" selected>' not in client.get(path).text


@pytest.mark.parametrize("value", ["99999999999999999999", "-1", "invalid", "9999999"])
def test_invalid_saved_user_filter_falls_back_to_all_users(
    client: TestClient, admin, value: str
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    set_filter_cookie(client, value)
    page = client.get("/history")
    assert page.status_code == 200
    assert '<option value="" selected>Alle</option>' in page.text


def test_filter_does_not_carry_over_to_a_new_login_session(
    client: TestClient, admin, filter_user
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    old_scope = form_token(client.get("/").text)
    set_filter_cookie(client, str(filter_user.id))
    page = client.get("/")
    logged_out = client.post("/logout", data={"csrf_token": form_token(page.text)})
    assert logged_out.status_code == 200
    assert client.cookies.get(user_filter_cookie_name(https=False)) is None
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    set_filter_cookie(client, str(filter_user.id), scope=old_scope)
    for path in ("/", "/history", "/recordings"):
        assert f'<option value="{filter_user.id}" selected>' not in client.get(path).text


def test_http_and_https_have_separate_session_filters(app: FastAPI, admin, filter_user) -> None:
    with TestClient(app, base_url="https://testserver") as client:
        assert login(client, "admin", "a-secure-admin-password").status_code == 303
        token = form_token(client.get("/").text)
        client.cookies.set(user_filter_cookie_name(https=False), f"{token}.{filter_user.id}")
        page = client.get("/history")
        assert '<option value="" selected>Alle</option>' in page.text
        set_filter_cookie(client, str(filter_user.id))
        assert_selected(client, filter_user.id)
        page = client.get("/")
        client.post("/logout", data={"csrf_token": form_token(page.text)})
        assert client.cookies.get(user_filter_cookie_name(https=True)) is None
