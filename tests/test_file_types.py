from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from awas.models import (
    AuditLog,
    FileTypeSetting,
    Recording,
    RecordingSchedule,
    RecurringSchedule,
    Stream,
)
from awas.models.auth import utc_now
from awas.services.auth import create_user
from awas.services.file_types import configured_file_types
from tests.conftest import form_token, login
from tests.test_recordings import install_fake_ffmpeg, wait_for_status
from tests.test_recurrence import local_today, post_recurring
from tests.test_schedules import add_schedule
from tests.test_streams import add_stream


def save_file_types(client: TestClient, value: str):
    page = client.get("/admin/recorders")
    return client.post(
        "/admin/recorders/file-types",
        data={"file_types": value, "csrf_token": form_token(page.text)},
        follow_redirects=False,
    )


def test_admin_configures_ordered_file_types_used_by_streams_and_plans(
    app: FastAPI, client: TestClient, admin
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/recorders")
    assert page.text.index('name="file_types"') < page.text.index('name="arguments"')
    saved = save_file_types(client, " .MKA, TS, mka, .AAC, ")
    assert saved.status_code == 303
    with app.state.session_factory() as db:
        assert configured_file_types(db) == ("mka", "ts", "aac")
        assert db.get(FileTypeSetting, 1).updated_by_id == admin.id
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "recorder.file_types_updated"))
        assert audit is not None

    assert add_stream(client, preferred_file_type="mka").status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))

    for path in (
        "/admin/streams/new",
        f"/admin/streams/{stream_id}",
        "/schedules/new",
        "/schedules/recurring/new",
    ):
        html = client.get(path).text
        assert html.index('<option value="mka"') < html.index('<option value="ts"')
        assert html.index('<option value="ts"') < html.index('<option value="aac"')
        assert '<option value="mp3"' not in html

    assert add_schedule(client, stream_id=stream_id, file_type="aac").status_code == 303
    day = local_today(app) + timedelta(days=1)
    assert (
        post_recurring(client, stream_id=stream_id, valid_from=day, valid_until=day).status_code
        == 303
    )
    with app.state.session_factory() as db:
        assert db.scalar(select(RecurringSchedule.file_type)) == "mka"
        assert (
            db.scalar(
                select(RecordingSchedule.file_type).where(RecordingSchedule.recurrence_id.is_(None))
            )
            == "aac"
        )
    rejected = add_stream(client, name="Removed type", preferred_file_type="mp3")
    assert rejected.status_code == 400
    assert "Dateityp ist ungültig" in rejected.text


@pytest.mark.parametrize(
    "value",
    [
        " , , ",
        "mp3, ../wav",
        "mp3;wav",
        "mp3, a-b",
        "a" * 17,
        ",".join(f"{index:015d}" for index in range(128)),
    ],
)
def test_invalid_file_type_list_does_not_replace_saved_configuration(
    app: FastAPI, client: TestClient, admin, value: str
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert save_file_types(client, "ts, mp3").status_code == 303
    rejected = save_file_types(client, value)
    assert rejected.status_code == 400
    with app.state.session_factory() as db:
        assert configured_file_types(db) == ("ts", "mp3")


@pytest.mark.parametrize("use", ["stream", "schedule", "paused-rule", "recording"])
def test_file_type_in_use_cannot_be_removed(
    app: FastAPI, client: TestClient, admin, use: str
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    now = utc_now()
    with app.state.session_factory() as db:
        if use == "stream":
            item = Stream(
                name="Keep", stream_url="https://radio.example/keep", preferred_file_type="mp3"
            )
        elif use == "schedule":
            item = RecordingSchedule(
                title="Keep",
                starts_at=now + timedelta(hours=1),
                ends_at=now + timedelta(hours=2),
                status="scheduled",
                file_type="mp3",
            )
        elif use == "paused-rule":
            stream = Stream(
                name="Keep", stream_url="https://radio.example/keep", preferred_file_type="ts"
            )
            db.add(stream)
            db.flush()
            item = RecurringSchedule(
                stream_id=stream.id,
                title="Keep",
                file_type="mp3",
                recurrence_type="weekly",
                interval_count=1,
                weekday_mask=127,
                start_minute=600,
                duration_minutes=30,
                valid_from=local_today(app),
                is_active=False,
            )
        else:
            item = Recording(
                stream_name="Keep", file_name="keep.mp3", file_type="mp3", status="recording"
            )
        db.add(item)
        db.commit()
    rejected = save_file_types(client, "ts, aac")
    assert rejected.status_code == 400
    assert "müssen in der Liste bleiben: mp3" in rejected.text
    with app.state.session_factory() as db:
        assert "mp3" in configured_file_types(db)


def test_historical_file_type_can_leave_the_list_without_altering_history(
    app: FastAPI, client: TestClient, admin
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    now = utc_now()
    with app.state.session_factory() as db:
        schedule = RecordingSchedule(
            title="Old",
            stream_name="Old stream",
            file_type="mp3",
            status="completed",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )
        db.add(schedule)
        db.flush()
        recording = Recording(
            stream_name="Old stream",
            file_name="old.mp3",
            file_type="mp3",
            status="completed",
            started_at=schedule.starts_at,
            ended_at=schedule.ends_at,
            schedule_id=schedule.id,
        )
        db.add(recording)
        db.commit()
        schedule_id, recording_id = schedule.id, recording.id
    assert save_file_types(client, "aac").status_code == 303
    with app.state.session_factory() as db:
        assert db.get(RecordingSchedule, schedule_id).file_type == "mp3"
        assert db.get(Recording, recording_id).file_name == "old.mp3"
    assert "Dateityp: mp3" in client.get("/history").text
    assert "old.mp3" in client.get("/recordings").text


def test_custom_suffix_reaches_the_recording_process(
    app: FastAPI, client: TestClient, admin, tmp_path: Path, monkeypatch
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert save_file_types(client, "mka, ts").status_code == 303
    assert add_stream(client, preferred_file_type="mka").status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    page = client.get("/streams")
    started = client.post(
        f"/streams/{stream_id}/recordings/start",
        data={"csrf_token": form_token(page.text)},
        follow_redirects=False,
    )
    assert started.status_code == 303
    with app.state.session_factory() as db:
        recording = db.scalar(select(Recording))
        recording_id = recording.id
        assert recording.file_type == "mka" and recording.file_name.endswith(".mka")
        app.state.recording_manager.stop_recording(
            db, recording=recording, actor=admin, ip_address="127.0.0.1"
        )
    wait_for_status(app, recording_id, "completed")


def test_only_admin_with_valid_csrf_can_change_file_types(
    app: FastAPI, client: TestClient, admin
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert (
        client.post(
            "/admin/recorders/file-types", data={"file_types": "mka", "csrf_token": "invalid"}
        ).status_code
        == 403
    )
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
    client.cookies.clear()
    assert login(client, "listener", "listener").status_code == 303
    page = client.get("/streams")
    assert (
        client.post(
            "/admin/recorders/file-types",
            data={"file_types": "mka", "csrf_token": form_token(page.text)},
        ).status_code
        == 403
    )
    with app.state.session_factory() as db:
        assert "mp3" in configured_file_types(db)


def test_invalid_stream_edit_renders_configured_choices_without_flushing_invalid_data(
    app: FastAPI, client: TestClient, admin
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert save_file_types(client, "mka, ts").status_code == 303
    assert add_stream(client, name="Erster", preferred_file_type="mka").status_code == 303
    assert add_stream(client, name="Zweiter", preferred_file_type="mka").status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id).where(Stream.name == "Erster"))
    page = client.get(f"/admin/streams/{stream_id}")
    rejected = client.post(
        f"/admin/streams/{stream_id}",
        data={
            "name": "Zweiter",
            "stream_url": "https://radio.example/new",
            "preferred_recorder": "ffmpeg",
            "preferred_file_type": "mka",
            "csrf_token": form_token(page.text),
        },
    )
    assert rejected.status_code == 400
    assert "Namen ist bereits vorhanden" in rejected.text
    assert '<option value="mka"' in rejected.text
    with app.state.session_factory() as db:
        assert set(db.scalars(select(Stream.name))) == {"Erster", "Zweiter"}
