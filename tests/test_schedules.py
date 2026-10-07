from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from awas.models import AuditLog, Recording, RecordingSchedule, Stream
from awas.models.auth import utc_now
from awas.services.auth import create_user
from awas.services.recorders import RECORDER_CHOICES
from awas.services.recording import RecordingError
from awas.services.scheduling import (
    RETRY_BACKOFF_SECONDS,
    RecordingScheduler,
    ScheduleInputError,
    datetime_local_value,
    parse_local_datetime,
)
from tests.conftest import form_token, login
from tests.test_recordings import install_fake_ffmpeg, wait_for_status
from tests.test_streams import add_stream


def add_schedule(
    client: TestClient,
    *,
    stream_id: int,
    title: str = "Morgensendung",
    file_name_base: str | None = None,
    recorder: str | None = None,
    file_type: str | None = None,
    start_offset: timedelta = timedelta(hours=1),
    duration: timedelta = timedelta(minutes=30),
):
    timezone = client.app.state.settings.general.timezone
    starts_at = (utc_now() + start_offset).replace(second=0, microsecond=0)
    ends_at = starts_at + duration
    page = client.get("/schedules/new")
    data = {
        "title": title,
        "stream_id": str(stream_id),
        "starts_at": datetime_local_value(starts_at, timezone),
        "ends_at": datetime_local_value(ends_at, timezone),
        "csrf_token": form_token(page.text),
    }
    if file_name_base is not None:
        data["file_name_base"] = file_name_base
    if recorder is not None:
        data["recorder"] = recorder
    if file_type is not None:
        data["file_type"] = file_type
    return client.post(
        "/schedules",
        data=data,
        follow_redirects=False,
    )


def test_user_creates_edits_and_cancels_schedule(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))

    created = add_schedule(client, stream_id=stream_id)
    assert created.status_code == 303
    assert created.headers["location"] == "/?status=created"

    with app.state.session_factory() as db:
        schedule = db.scalar(select(RecordingSchedule))
        assert schedule is not None
        schedule_id = schedule.id
        assert schedule.title == "Morgensendung"
        assert schedule.recorder == "ffmpeg"
        assert schedule.file_type == "mp3"
        assert schedule.status == "scheduled"

    listing = client.get("/")
    assert "Morgensendung" in listing.text
    assert "<h2>Anstehend (1)</h2>" in listing.text
    assert listing.text.count('class="button button-primary"') >= 2
    assert 'data-live-interval="5000"' in listing.text
    assert listing.text.index("<small>Einmalig</small>") < listing.text.index(
        "<small>von AWAS Admin</small>"
    )
    assert f'href="/schedules/{schedule_id}/copy"' in listing.text
    edit_page = client.get(f"/schedules/{schedule_id}/edit")
    assert 'data-preferred-recorder="ffmpeg"' in edit_page.text
    assert 'data-preferred-file-type="mp3"' in edit_page.text
    timezone = app.state.settings.general.timezone
    new_start = (utc_now() + timedelta(hours=2)).replace(second=0, microsecond=0)
    changed = client.post(
        f"/schedules/{schedule_id}",
        data={
            "title": "Abendsendung",
            "stream_id": str(stream_id),
            "recorder": "mpv",
            "file_type": "ogg",
            "starts_at": datetime_local_value(new_start, timezone),
            "ends_at": datetime_local_value(new_start + timedelta(hours=1), timezone),
            "csrf_token": form_token(edit_page.text),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        stream = db.get(Stream, stream_id)
        assert schedule.recorder == "mpv"
        assert schedule.file_type == "ogg"
        assert stream.preferred_recorder == "ffmpeg"
        assert stream.preferred_file_type == "mp3"

    listing = client.get("/")
    assert "Verwerfen" not in listing.text
    assert "Wirklich löschen?" in listing.text
    assert 'name="delete_confirmed"' in listing.text
    unconfirmed = client.post(
        f"/schedules/{schedule_id}/cancel",
        data={"csrf_token": form_token(listing.text)},
    )
    assert unconfirmed.status_code == 400
    with app.state.session_factory() as db:
        assert db.get(RecordingSchedule, schedule_id).status == "scheduled"

    cancelled = client.post(
        f"/schedules/{schedule_id}/cancel",
        data={
            "csrf_token": form_token(listing.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert cancelled.status_code == 303
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        assert schedule.title == "Abendsendung"
        assert schedule.recorder == "mpv"
        assert schedule.file_type == "ogg"
        assert schedule.status == "cancelled"
        assert schedule.is_hidden is True
        actions = set(db.scalars(select(AuditLog.action)))
        assert {"schedule.created", "schedule.updated", "schedule.cancelled"} <= actions

    assert "Abendsendung" not in client.get("/").text
    history = client.get("/history")
    assert "Abendsendung" not in history.text
    assert "Verworfen" not in history.text
    assert "Abgesagt" not in history.text


def test_new_schedule_form_has_empty_times_and_save_button(
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303

    page = client.get("/schedules/new")

    assert page.status_code == 200
    assert 'name="starts_at" value=""' in page.text
    assert 'name="ends_at" value=""' in page.text
    assert 'name="file_name_base" value=""' in page.text
    assert "data-file-name-base" in page.text
    assert "Zeitplan anlegen" not in page.text
    assert ">Speichern</button>" in page.text


def test_upcoming_schedule_can_be_copied_without_changing_the_source(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))

    created = add_schedule(
        client,
        stream_id=stream_id,
        title="Vorlage Abendmagazin",
        file_name_base="abendmagazin_vorlage",
        recorder="mpv",
        file_type="ogg",
        start_offset=timedelta(hours=2),
        duration=timedelta(hours=1),
    )
    assert created.status_code == 303
    with app.state.session_factory() as db:
        source = db.scalar(select(RecordingSchedule))
        source_id = source.id
        source_start = source.starts_at
        source_end = source.ends_at

    copied_form = client.get(f"/schedules/{source_id}/copy")

    assert copied_form.status_code == 200
    assert "<h1>Aufnahme planen</h1>" in copied_form.text
    assert 'form method="post" action="/schedules"' in copied_form.text
    assert 'name="title" value="Vorlage Abendmagazin"' in copied_form.text
    assert 'name="file_name_base" value="abendmagazin_vorlage"' in copied_form.text
    assert f'<option value="{stream_id}"' in copied_form.text
    selected_stream_option = (
        f'<option value="{stream_id}" data-preferred-recorder="ffmpeg" '
        'data-preferred-file-type="mp3" selected>'
    )
    assert selected_stream_option in copied_form.text
    assert '<option value="mpv" selected>mpv</option>' in copied_form.text
    assert '<option value="ogg" selected>ogg</option>' in copied_form.text
    with app.state.session_factory() as db:
        assert len(list(db.scalars(select(RecordingSchedule)))) == 1

    timezone = app.state.settings.general.timezone
    new_start = source_start + timedelta(days=1)
    saved_copy = client.post(
        "/schedules",
        data={
            "title": "Kopie Abendmagazin",
            "file_name_base": "abendmagazin_kopie",
            "stream_id": str(stream_id),
            "recorder": "vlc",
            "file_type": "ts",
            "starts_at": datetime_local_value(new_start, timezone),
            "ends_at": datetime_local_value(source_end + timedelta(days=1), timezone),
            "csrf_token": form_token(copied_form.text),
        },
        follow_redirects=False,
    )

    assert saved_copy.status_code == 303
    assert saved_copy.headers["location"] == "/?status=created"
    with app.state.session_factory() as db:
        schedules = list(db.scalars(select(RecordingSchedule).order_by(RecordingSchedule.id)))
        stream = db.get(Stream, stream_id)
        assert len(schedules) == 2
        assert schedules[0].id == source_id
        assert schedules[0].title == "Vorlage Abendmagazin"
        assert schedules[0].recorder == "mpv"
        assert schedules[0].file_type == "ogg"
        assert schedules[1].title == "Kopie Abendmagazin"
        assert schedules[1].recorder == "vlc"
        assert schedules[1].file_type == "ts"
        assert stream.preferred_recorder == "ffmpeg"
        assert stream.preferred_file_type == "mp3"


def test_history_schedule_can_be_copied_without_changing_the_source(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    now = utc_now().replace(second=0, microsecond=0)
    with app.state.session_factory() as db:
        stream = db.scalar(select(Stream))
        schedule = RecordingSchedule(
            stream_id=stream.id,
            stream_name="Historischer Streamname",
            stream_url="https://radio.example/tatsaechlich-verwendet",
            title="Historischer Titel",
            file_name_base="historischer_titel",
            recorder="ffmpeg",
            file_type="mp3",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
            status="failed",
            error_message="Bestehender Fehlertext",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.commit()
        schedule_id = schedule.id
        stream_id = stream.id
        stream.name = "Aktueller Streamname"
        stream.stream_url = "https://radio.example/aktuell"
        db.commit()

    history = client.get("/history")
    assert history.status_code == 200
    assert f'href="/schedules/{schedule_id}/copy"' in history.text
    assert f'href="/schedules/{schedule_id}/edit"' not in history.text
    assert f'action="/schedules/{schedule_id}/delete"' in history.text
    assert "Eintrag löschen" not in history.text
    assert "Historischer Streamname" in history.text
    assert "https://radio.example/tatsaechlich-verwendet" in history.text
    assert "https://radio.example/aktuell" not in history.text
    assert 'class="stream-url-row"' in history.text

    copied_form = client.get(f"/schedules/{schedule_id}/copy")
    assert copied_form.status_code == 200
    assert "<h1>Aufnahme planen</h1>" in copied_form.text
    assert 'form method="post" action="/schedules"' in copied_form.text
    assert 'name="title" value="Historischer Titel"' in copied_form.text
    assert 'name="file_name_base" value="historischer_titel"' in copied_form.text
    assert '<option value="ffmpeg" selected>ffmpeg</option>' in copied_form.text
    assert '<option value="mp3" selected>mp3</option>' in copied_form.text
    assert "Aktueller Streamname" in copied_form.text
    assert client.get(f"/schedules/{schedule_id}/edit").status_code == 409
    with app.state.session_factory() as db:
        assert len(list(db.scalars(select(RecordingSchedule)))) == 1

    timezone = app.state.settings.general.timezone
    copied_start = now + timedelta(hours=3)
    saved_copy = client.post(
        "/schedules",
        data={
            "title": "Kopie des historischen Titels",
            "file_name_base": "kopierte_historie",
            "stream_id": str(stream_id),
            "recorder": "mpv",
            "file_type": "ogg",
            "starts_at": datetime_local_value(copied_start, timezone),
            "ends_at": datetime_local_value(
                copied_start + timedelta(minutes=45), timezone
            ),
            "csrf_token": form_token(copied_form.text),
        },
        follow_redirects=False,
    )

    assert saved_copy.status_code == 303
    assert saved_copy.headers["location"] == "/?status=created"
    with app.state.session_factory() as db:
        schedules = list(db.scalars(select(RecordingSchedule).order_by(RecordingSchedule.id)))
        source = schedules[0]
        copied = schedules[1]
        stream = db.get(Stream, stream_id)
        assert len(schedules) == 2
        assert source.id == schedule_id
        assert source.title == "Historischer Titel"
        assert source.stream_name == "Historischer Streamname"
        assert source.stream_url == "https://radio.example/tatsaechlich-verwendet"
        assert source.file_name_base == "historischer_titel"
        assert source.recorder == "ffmpeg"
        assert source.file_type == "mp3"
        assert source.status == "failed"
        assert source.error_message == "Bestehender Fehlertext"
        assert copied.title == "Kopie des historischen Titels"
        assert copied.stream_name == "Aktueller Streamname"
        assert copied.stream_url == "https://radio.example/aktuell"
        assert copied.file_name_base == "kopierte_historie"
        assert copied.recorder == "mpv"
        assert copied.file_type == "ogg"
        assert copied.starts_at == copied_start
        assert copied.status == "scheduled"
        assert copied.error_message is None
        assert stream.preferred_recorder == "ffmpeg"
        assert stream.preferred_file_type == "mp3"


def test_schedule_stores_custom_file_name_base(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))

    response = add_schedule(
        client,
        stream_id=stream_id,
        title="Morgensendung",
        file_name_base="Meine_Aufnahme für Münster",
    )

    assert response.status_code == 303
    with app.state.session_factory() as db:
        schedule = db.scalar(select(RecordingSchedule))
        assert schedule.file_name_base == "meine_aufnahme-fur-munster"


def test_overlapping_schedules_for_same_stream_are_accepted(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))

    assert add_schedule(client, stream_id=stream_id).status_code == 303
    overlapping = add_schedule(client, stream_id=stream_id, title="Überschneidung")
    assert overlapping.status_code == 303
    with app.state.session_factory() as db:
        assert len(list(db.scalars(select(RecordingSchedule.id)))) == 2


def test_normal_user_can_plan_but_not_edit_another_users_schedule(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    assert add_schedule(client, stream_id=stream_id).status_code == 303
    with app.state.session_factory() as db:
        schedule_id = db.scalar(select(RecordingSchedule.id))
        create_user(
            db,
            username="listener",
            display_name="Listener",
            password="listener",
            password_confirmation="listener",
            role="user",
            must_change_password=False,
        )

    page = client.get("/")
    client.post("/logout", data={"csrf_token": form_token(page.text)})
    assert login(client, "listener", "listener").status_code == 303
    assert client.get("/").status_code == 200
    assert client.get(f"/schedules/{schedule_id}/edit").status_code == 403
    assert client.get(f"/schedules/{schedule_id}/copy").status_code == 403

    own = add_schedule(
        client,
        stream_id=stream_id,
        title="Eigene Sendung",
        start_offset=timedelta(hours=3),
    )
    assert own.status_code == 303
    with app.state.session_factory() as db:
        own_schedule_id = db.scalar(
            select(RecordingSchedule.id).where(
                RecordingSchedule.title == "Eigene Sendung"
            )
        )
    assert client.get(f"/schedules/{own_schedule_id}/edit").status_code == 200

    planning = client.get("/")
    cancelled = client.post(
        f"/schedules/{own_schedule_id}/cancel",
        data={
            "csrf_token": form_token(planning.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert cancelled.status_code == 303
    history = client.get("/history")
    assert "Eigene Sendung" not in history.text
    assert f'action="/schedules/{own_schedule_id}/delete"' not in history.text
    with app.state.session_factory() as db:
        assert db.get(RecordingSchedule, own_schedule_id).is_hidden is True


def test_scheduler_starts_and_stops_recording(
    app: FastAPI,
    client: TestClient,
    admin,
    tmp_path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Scheduled Stream",
            stream_url="https://radio.example/scheduled",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            stream_name="Scheduled Stream",
            stream_url="https://radio.example/originally-planned",
            title="Geplante Sendung",
            recorder="ffmpeg",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=1),
            status="scheduled",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.commit()
        schedule_id = schedule.id
        stream.stream_url = "https://radio.example/actually-recorded"
        db.commit()

    app.state.recording_scheduler.run_due(now)
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        recording = db.scalar(select(Recording).where(Recording.schedule_id == schedule_id))
        assert schedule.status == "running"
        assert schedule.stream_name == "Scheduled Stream"
        assert schedule.stream_url == "https://radio.example/actually-recorded"
        assert recording is not None
        assert recording.status == "recording"
        assert "geplante-sendung" in recording.file_name
        recording_id = recording.id

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    planning = client.get("/")
    assert (
        '<tr class="recording-data-row recording-data-row-with-file recording-active-row">'
        in planning.text
    )
    assert recording.file_name in planning.text
    assert f'href="/recordings/{recording_id}/download"' in planning.text
    assert f'action="/recordings/{recording_id}/stop"' in planning.text
    assert 'name="stop_confirmed"' in planning.text
    assert "Wirklich stoppen?" in planning.text

    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        schedule.ends_at = now - timedelta(seconds=1)
        db.commit()

    app.state.recording_scheduler.run_due(now)
    wait_for_status(app, recording_id, "completed")
    app.state.recording_scheduler.run_due(now)
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        assert schedule.status == "completed"
        actions = set(db.scalars(select(AuditLog.action)))
        assert {"schedule.started", "schedule.completed"} <= actions


def test_scheduler_and_manual_recordings_run_in_parallel_for_same_stream(
    app: FastAPI,
    admin,
    tmp_path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Parallel Stream",
            stream_url="https://radio.example/parallel",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        for title in ("Planung A", "Planung B"):
            db.add(
                RecordingSchedule(
                    stream_id=stream.id,
                    title=title,
                    recorder="ffmpeg",
                    file_type="mp3",
                    starts_at=now - timedelta(seconds=10),
                    ends_at=now + timedelta(minutes=5),
                    status="scheduled",
                    created_by_id=admin.id,
                )
            )
        db.commit()
        stream_id = stream.id
        app.state.recording_manager.start_recording(
            db,
            stream=stream,
            actor=admin,
            ip_address="127.0.0.1",
        )

    app.state.recording_scheduler.run_due(now)

    with app.state.session_factory() as db:
        recordings = list(
            db.scalars(
                select(Recording)
                .where(Recording.stream_id == stream_id)
                .order_by(Recording.id)
            )
        )
        assert len(recordings) == 3
        assert {recording.status for recording in recordings} == {"recording"}
        assert sum(recording.schedule_id is None for recording in recordings) == 1
        schedule_ids = {
            recording.schedule_id for recording in recordings if recording.schedule_id
        }
        assert len(schedule_ids) == 2
        assert len({recording.file_name for recording in recordings}) == 3
        recording_ids = [recording.id for recording in recordings]
        for recording in recordings:
            app.state.recording_manager.stop_recording(
                db,
                recording=recording,
                actor=admin,
                ip_address="127.0.0.1",
            )

    for recording_id in recording_ids:
        wait_for_status(app, recording_id, "completed")


def test_scheduler_marks_expired_schedule_as_missed(app: FastAPI, admin) -> None:
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Offline Stream",
            stream_url="https://radio.example/offline",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            title="Verpasste Sendung",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
            status="scheduled",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.commit()
        schedule_id = schedule.id

    app.state.recording_scheduler.run_due(now)
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        assert schedule.status == "missed"
        assert "abgelaufen" in schedule.error_message
        assert db.scalar(select(Recording.id)) is None


def test_scheduler_resumes_interrupted_schedule(
    app: FastAPI,
    admin,
    tmp_path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Restart Stream",
            stream_url="https://radio.example/restart",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            title="Fortgesetzte Sendung",
            recorder="ffmpeg",
            starts_at=now - timedelta(minutes=5),
            ends_at=now + timedelta(minutes=5),
            status="running",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.flush()
        db.add(
            Recording(
                stream_id=stream.id,
                stream_name=stream.name,
                file_name="first-segment.mka",
                status="recording",
                started_at=now - timedelta(minutes=5),
                started_by_id=admin.id,
                schedule_id=schedule.id,
            )
        )
        db.commit()
        schedule_id = schedule.id

    app.state.recording_manager.reconcile_interrupted()
    with app.state.session_factory() as db:
        interrupted_at = db.scalar(
            select(Recording.ended_at).where(Recording.schedule_id == schedule_id)
        )
    assert interrupted_at is not None

    app.state.recording_scheduler.run_due(
        interrupted_at + timedelta(seconds=RETRY_BACKOFF_SECONDS[0] - 1)
    )
    with app.state.session_factory() as db:
        recordings = list(
            db.scalars(
                select(Recording)
                .where(Recording.schedule_id == schedule_id)
                .order_by(Recording.id)
            )
        )
        assert [item.status for item in recordings] == ["interrupted"]
        assert "automatisch erneut" in db.get(
            RecordingSchedule, schedule_id
        ).error_message

    retry_at = interrupted_at + timedelta(seconds=RETRY_BACKOFF_SECONDS[0])
    app.state.recording_scheduler.run_due(retry_at)
    with app.state.session_factory() as db:
        recordings = list(
            db.scalars(
                select(Recording)
                .where(Recording.schedule_id == schedule_id)
                .order_by(Recording.id)
            )
        )
        assert [item.status for item in recordings] == ["interrupted", "recording"]
        active_id = recordings[-1].id
        schedule = db.get(RecordingSchedule, schedule_id)
        schedule.ends_at = retry_at - timedelta(seconds=1)
        db.commit()

    app.state.recording_scheduler.run_due(retry_at)
    wait_for_status(app, active_id, "completed")
    app.state.recording_scheduler.run_due(retry_at)
    with app.state.session_factory() as db:
        assert db.get(RecordingSchedule, schedule_id).status == "completed"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "schedule.resumed"))


def test_user_stops_retrying_schedule_after_unexpected_recorder_exit(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Retry Stop Stream",
            stream_url="https://radio.example/retry-stop",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            title="Retry stoppen",
            recorder="ffmpeg",
            file_type="ts",
            starts_at=now - timedelta(minutes=2),
            ends_at=now + timedelta(minutes=10),
            status="running",
            error_message="AWAS versucht die Aufnahme automatisch erneut.",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.flush()
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name="retry-stop.ts",
            recorder="ffmpeg",
            file_type="ts",
            status="interrupted",
            started_at=now - timedelta(minutes=1),
            ended_at=now,
            started_by_id=admin.id,
            schedule_id=schedule.id,
        )
        db.add(recording)
        db.commit()
        schedule_id = schedule.id
        recording_id = recording.id

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    planning = client.get("/")
    assert "<h2>Laufend (1)</h2>" in planning.text
    assert f'action="/schedules/{schedule_id}/stop"' in planning.text
    assert "Wirklich stoppen?" in planning.text

    recordings = client.get("/recordings")
    assert f'action="/schedules/{schedule_id}/stop"' in recordings.text
    assert f'action="/recordings/{recording_id}/delete"' in recordings.text

    unconfirmed = client.post(
        f"/schedules/{schedule_id}/stop",
        data={"csrf_token": form_token(recordings.text), "return_to": "/recordings"},
    )
    assert unconfirmed.status_code == 400

    stopped = client.post(
        f"/schedules/{schedule_id}/stop",
        data={
            "csrf_token": form_token(recordings.text),
            "return_to": "/recordings",
            "stop_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert stopped.status_code == 303
    assert stopped.headers["location"] == "/recordings?status=stopped"

    app.state.recording_scheduler.run_due(now + timedelta(minutes=5))
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        assert schedule.status == "completed"
        assert schedule.error_message is None
        assert db.scalar(
            select(AuditLog).where(AuditLog.action == "schedule.stopped")
        )
        attempts = list(
            db.scalars(select(Recording).where(Recording.schedule_id == schedule_id))
        )
        assert [attempt.id for attempt in attempts] == [recording_id]


@pytest.mark.parametrize("recorder", [key for key, _ in RECORDER_CHOICES])
def test_shutdown_interrupts_and_resumes_every_recorder(
    app: FastAPI,
    admin,
    tmp_path,
    monkeypatch,
    recorder: str,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    fake_recorder = tmp_path / "ffmpeg"

    def build_fake_command(*_args, output_path, **_kwargs):
        return [str(fake_recorder), str(output_path)]

    monkeypatch.setattr(
        "awas.services.recording.build_recorder_command",
        build_fake_command,
    )
    generated_file_names = iter(
        (
            f"2026-09-30_14-30-00_restart-{recorder}_aaaaaa.mp3",
            f"2026-09-30_14-30-15_restart-{recorder}_bbbbbb.mp3",
        )
    )

    def generate_file_name(*_args, **_kwargs):
        return next(generated_file_names)

    monkeypatch.setattr(
        "awas.services.recording.recording_file_name",
        generate_file_name,
    )
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name=f"Restart {recorder}",
            stream_url="http://radio.example/restart",
            preferred_recorder=recorder,
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            title=f"Restart {recorder}",
            file_name_base=f"restart-{recorder}",
            recorder=recorder,
            file_type="mp3",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=5),
            status="running",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.flush()
        first = app.state.recording_manager.start_recording(
            db,
            stream=stream,
            actor=admin,
            ip_address="127.0.0.1",
            schedule_id=schedule.id,
            file_name_base=schedule.file_name_base,
            recorder=recorder,
            file_type="mp3",
        )
        schedule_id = schedule.id
        first_id = first.id
        schedule.status = "running"
        db.commit()

    app.state.recording_manager.shutdown()
    interrupted = wait_for_status(app, first_id, "interrupted")
    assert interrupted.recorder == recorder
    assert interrupted.ended_at is not None

    retry_at = interrupted.ended_at + timedelta(seconds=RETRY_BACKOFF_SECONDS[0])
    app.state.recording_scheduler.run_due(retry_at - timedelta(seconds=1))
    with app.state.session_factory() as db:
        recordings = list(
            db.scalars(
                select(Recording)
                .where(Recording.schedule_id == schedule_id)
                .order_by(Recording.id)
            )
        )
        assert [item.status for item in recordings] == ["interrupted"]

    app.state.recording_scheduler.run_due(retry_at)
    with app.state.session_factory() as db:
        recordings = list(
            db.scalars(
                select(Recording)
                .where(Recording.schedule_id == schedule_id)
                .order_by(Recording.id)
            )
        )
        assert [item.status for item in recordings] == ["interrupted", "recording"]
        assert {item.recorder for item in recordings} == {recorder}
        assert [item.file_name for item in recordings] == [
            f"2026-09-30_14-30-00_restart-{recorder}_aaaaaa.mp3",
            f"2026-09-30_14-30-15_restart-{recorder}_bbbbbb.mp3",
        ]
        assert len({item.group_key for item in recordings}) == 1
        groups = app.state.recording_manager.recording_groups(db, recordings)
        assert len(groups) == 1
        assert len(groups[0].attempts) == 2
        resumed_id = recordings[-1].id
        schedule = db.get(RecordingSchedule, schedule_id)
        schedule.ends_at = retry_at
        db.commit()

    app.state.recording_scheduler.run_due(retry_at + timedelta(seconds=1))
    wait_for_status(app, resumed_id, "completed")
    app.state.recording_scheduler.run_due(retry_at + timedelta(seconds=1))
    with app.state.session_factory() as db:
        assert db.get(RecordingSchedule, schedule_id).status == "completed"


@pytest.mark.parametrize("recorder", [key for key, _ in RECORDER_CHOICES])
@pytest.mark.parametrize("return_code", (0, 23))
def test_early_exit_stays_resumable_for_every_recorder(
    app: FastAPI,
    admin,
    tmp_path,
    monkeypatch,
    recorder: str,
    return_code: int,
) -> None:
    fake_recorder = tmp_path / "quick-recorder"
    fake_recorder.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "import sys\n"
        "pathlib.Path(sys.argv[1]).write_bytes(b'partial')\n"
        f"raise SystemExit({return_code})\n",
        encoding="utf-8",
    )
    fake_recorder.chmod(0o755)

    def build_fake_command(*_args, output_path, **_kwargs):
        return [str(fake_recorder), str(output_path)]

    monkeypatch.setattr(
        "awas.services.recording.build_recorder_command",
        build_fake_command,
    )
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name=f"Early exit {recorder}",
            stream_url="http://radio.example/early-exit",
            preferred_recorder=recorder,
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            title=f"Early exit {recorder}",
            recorder=recorder,
            file_type="mp3",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=5),
            status="running",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.flush()
        recording = app.state.recording_manager.start_recording(
            db,
            stream=stream,
            actor=admin,
            ip_address="127.0.0.1",
            schedule_id=schedule.id,
            recorder=recorder,
            file_type="mp3",
        )
        recording_id = recording.id
        db.commit()

    interrupted = wait_for_status(app, recording_id, "interrupted")
    assert interrupted.recorder == recorder
    assert f"Status {return_code}" in interrupted.error_message


def test_scheduler_uses_progressive_retry_delay(
    app: FastAPI,
    admin,
    tmp_path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Retry Stream",
            stream_url="https://radio.example/retry",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            title="Retry Sendung",
            recorder="ffmpeg",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(minutes=10),
            status="running",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.flush()
        for index in range(2):
            ended_at = now - timedelta(seconds=1 - index)
            db.add(
                Recording(
                    stream_id=stream.id,
                    stream_name=stream.name,
                    file_name=f"retry-{index}.mp3",
                    recorder="ffmpeg",
                    file_type="mp3",
                    status="interrupted",
                    started_at=ended_at - timedelta(seconds=1),
                    ended_at=ended_at,
                    schedule_id=schedule.id,
                )
            )
        db.commit()
        schedule_id = schedule.id

    assert RETRY_BACKOFF_SECONDS == (15, 30, 60, 120, 300)
    app.state.recording_scheduler.run_due(now + timedelta(seconds=29))
    with app.state.session_factory() as db:
        assert len(
            list(db.scalars(select(Recording).where(Recording.schedule_id == schedule_id)))
        ) == 2

    app.state.recording_scheduler.run_due(now + timedelta(seconds=30))
    with app.state.session_factory() as db:
        recordings = list(
            db.scalars(
                select(Recording)
                .where(Recording.schedule_id == schedule_id)
                .order_by(Recording.id)
            )
        )
        assert [item.status for item in recordings] == [
            "interrupted",
            "interrupted",
            "recording",
        ]
        active = recordings[-1]
        app.state.recording_manager.stop_recording(
            db,
            recording=active,
            actor=admin,
            ip_address="127.0.0.1",
        )

    wait_for_status(app, active.id, "completed")


def test_retry_backoff_reaches_five_minutes_and_resets_after_stable_attempt() -> None:
    now = utc_now().replace(microsecond=0)
    quick_attempts = [
        Recording(
            stream_name="Retry Stream",
            file_name=f"quick-{index}.mp3",
            status="interrupted",
            started_at=now - timedelta(seconds=index + 2),
            ended_at=now - timedelta(seconds=index + 1),
        )
        for index in range(5)
    ]

    for count, expected_seconds in enumerate(RETRY_BACKOFF_SECONDS, start=1):
        assert RecordingScheduler._retry_delay(
            quick_attempts[:count]
        ) == timedelta(seconds=expected_seconds)

    stable_attempt = Recording(
        stream_name="Retry Stream",
        file_name="stable.mp3",
        status="interrupted",
        started_at=now - timedelta(minutes=2),
        ended_at=now,
    )
    assert RecordingScheduler._retry_delay(
        [stable_attempt, *quick_attempts]
    ) == timedelta(seconds=RETRY_BACKOFF_SECONDS[0])


def test_scheduler_retries_start_errors_until_end(
    app: FastAPI,
    admin,
    monkeypatch,
) -> None:
    now = utc_now().replace(microsecond=0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Unavailable Stream",
            stream_url="https://radio.example/unavailable",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            title="Retry bis Ende",
            recorder="ffmpeg",
            starts_at=now - timedelta(minutes=1),
            ends_at=now + timedelta(seconds=45),
            status="scheduled",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.commit()
        schedule_id = schedule.id

    attempts: list[int] = []

    def fail_start(*_args, **_kwargs):
        attempts.append(1)
        raise RecordingError("Rekorder vorübergehend nicht verfügbar.")

    monkeypatch.setattr(app.state.recording_manager, "start_recording", fail_start)

    app.state.recording_scheduler.run_due(now)
    app.state.recording_scheduler.run_due(now + timedelta(seconds=14))
    assert len(attempts) == 1

    app.state.recording_scheduler.run_due(now + timedelta(seconds=15))
    assert len(attempts) == 2

    app.state.recording_scheduler.run_due(now + timedelta(seconds=45))
    assert len(attempts) == 2
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        assert schedule.status == "failed"
        assert "bis zum geplanten Ende" in schedule.error_message


def test_local_time_parser_rejects_dst_gaps_and_ambiguity() -> None:
    assert parse_local_datetime(
        "2026-09-23T12:00", "Europe/Berlin", "Die Startzeit"
    ) == datetime(2026, 9, 23, 10, 0)

    with pytest.raises(ScheduleInputError, match="existiert"):
        parse_local_datetime("2026-03-29T02:30", "Europe/Berlin", "Die Startzeit")
    with pytest.raises(ScheduleInputError, match="nicht eindeutig"):
        parse_local_datetime("2026-10-25T02:30", "Europe/Berlin", "Die Startzeit")
