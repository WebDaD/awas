from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from awas.models import AuditLog, RecorderSetting
from awas.services.auth import create_user
from awas.services.recorders import RECORDER_PROFILES
from tests.conftest import form_token, login


def test_admin_views_and_updates_recorder_parameters(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303

    page = client.get("/admin/recorders")
    assert page.status_code == 200
    assert '<p class="eyebrow">Administration</p>' in page.text
    assert "<h1>Rekorder</h1>" in page.text
    assert "Tools" not in page.text
    assert len(RECORDER_PROFILES) == page.text.count('name="arguments"')
    assert page.text.count("<h2>vlc</h2>") == 1
    assert "yt-dlp" not in page.text
    assert "-metadata title=" not in page.text
    assert "-y " not in page.text

    arguments = "-nostdin -i {url} -map 0:a:0 -c:a copy {output}"
    updated = client.post(
        "/admin/recorders/ffmpeg",
        data={
            "arguments": arguments,
            "csrf_token": form_token(page.text),
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert updated.headers["location"] == "/admin/recorders?status=updated"

    with app.state.session_factory() as db:
        setting = db.get(RecorderSetting, "ffmpeg")
        assert setting.arguments == arguments
        assert setting.updated_by_id == admin.id
        assert db.scalar(select(AuditLog).where(AuditLog.action == "recorder.updated"))


def test_recorder_parameters_require_output_placeholder(
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/recorders")

    rejected = client.post(
        "/admin/recorders/ffmpeg",
        data={
            "arguments": "-nostdin -i {url} -c:a copy",
            "csrf_token": form_token(page.text),
        },
    )

    assert rejected.status_code == 400
    assert "fehlt der Platzhalter {output}" in rejected.text


def test_normal_user_cannot_manage_recorder_parameters(
    app: FastAPI,
    client: TestClient,
) -> None:
    with app.state.session_factory() as db:
        create_user(
            db,
            username="listener",
            display_name="Listener",
            password="listener",
            password_confirmation="listener",
            role="user",
            must_change_password=False,
        )
    assert login(client, "listener", "listener").status_code == 303

    response = client.get("/admin/recorders")

    assert response.status_code == 403
    assert "Administratorrechte" in response.text
