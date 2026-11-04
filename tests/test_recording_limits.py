import re
import sys
import time
from datetime import timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from awas.models import AuditLog, Recording, RecordingSchedule, RecurringSchedule, Stream
from awas.models.auth import utc_now
from awas.services.auth import create_user
from tests.conftest import form_token, login
from tests.test_recordings import install_fake_ffmpeg, wait_for_status
from tests.test_streams import add_stream


@pytest.fixture
def running_recordings(app: FastAPI, admin, tmp_path, monkeypatch):
    install_fake_ffmpeg(tmp_path, monkeypatch)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Limits",
            stream_url="https://radio.example/limits",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.commit()
        stream_id = stream.id

    def start(*, started_at, is_test=False, planned=False):
        with app.state.session_factory() as db:
            schedule_id = None
            if planned:
                schedule = RecordingSchedule(
                    stream_id=stream_id,
                    title="Long planned recording",
                    starts_at=started_at,
                    ends_at=utc_now() + timedelta(hours=1),
                    status="running",
                    recorder="ffmpeg",
                    file_type="mp3",
                    created_by_id=admin.id,
                )
                db.add(schedule)
                db.flush()
                schedule_id = schedule.id
            recording = app.state.recording_manager.start_recording(
                db,
                stream=db.get(Stream, stream_id),
                actor=admin,
                ip_address="127.0.0.1",
                schedule_id=schedule_id,
                is_test=is_test,
            )
            recording.started_at = started_at
            db.commit()
            recording_id = recording.id
            output = app.state.recording_manager.output_path(recording)
        deadline = time.monotonic() + 3
        while not output.is_file() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert output.is_file()
        return recording_id

    yield start
    app.state.recording_manager.shutdown()


def test_exact_24_hour_and_60_second_limits_keep_other_recordings_running(
    app: FastAPI, running_recordings
) -> None:
    now = utc_now()
    expired = running_recordings(started_at=now - timedelta(hours=24))
    younger = running_recordings(started_at=now - timedelta(hours=24) + timedelta(seconds=1))
    test = running_recordings(started_at=now - timedelta(seconds=59), is_test=True)
    planned = running_recordings(started_at=now - timedelta(hours=48), planned=True)
    app.state.recording_scheduler.run_due(now - timedelta(microseconds=1))
    with app.state.session_factory() as db:
        assert all(
            db.get(Recording, id_).status == "recording"
            for id_ in (expired, younger, test, planned)
        )
    app.state.recording_scheduler.run_due(now)
    wait_for_status(app, expired, "completed")
    with app.state.session_factory() as db:
        assert all(db.get(Recording, id_).status == "recording" for id_ in (younger, test, planned))
    app.state.recording_scheduler.run_due(now + timedelta(seconds=1))
    wait_for_status(app, younger, "completed")
    wait_for_status(app, test, "completed")
    app.state.recording_scheduler.run_due(now + timedelta(seconds=2))
    with app.state.session_factory() as db:
        assert db.get(Recording, planned).status == "recording"
        assert (
            db.scalar(
                select(func.count(AuditLog.id)).where(AuditLog.action == "recording.stop_requested")
            )
            == 3
        )
        for audit in db.scalars(
            select(AuditLog).where(AuditLog.action == "recording.stop_requested")
        ):
            assert audit.details["reason"] == "duration_limit"


def test_duration_limit_force_stops_an_unresponsive_recorder(
    app: FastAPI, running_recordings, monkeypatch
) -> None:
    now = utc_now()
    recording_id = running_recordings(started_at=now - timedelta(seconds=60), is_test=True)
    monkeypatch.setattr("awas.services.recording.RECORDING_STOP_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        app.state.recording_manager, "_terminate_process_group", lambda process: None
    )
    app.state.recording_scheduler.run_due(now)
    recording = wait_for_status(app, recording_id, "completed")
    assert recording.is_test and recording.error_message is None


@pytest.mark.parametrize(
    ("stream_name", "file_name_base"),
    (
        ("Radio Eins", "radio-eins"),
        ("Radio Köln / Live", "radio-koln-live"),
        ("X" * 128, "x" * 128),
    ),
)
def test_test_button_starts_a_named_recording_with_stream_defaults(
    app: FastAPI, client: TestClient, tmp_path, monkeypatch, stream_name, file_name_base
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    with app.state.session_factory() as db:
        user = create_user(
            db,
            username="tester",
            display_name="Tester",
            password="tester",
            password_confirmation="tester",
            role="user",
            must_change_password=False,
        )
        user_id = user.id
    assert login(client, "tester", "tester").status_code == 303
    assert add_stream(client, name=stream_name, preferred_file_type="flac").status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    page = client.get("/streams")
    assert client.get(f"/streams/{stream_id}/recordings/test").status_code == 405
    assert (
        client.post(
            f"/streams/{stream_id}/recordings/test", data={"csrf_token": "invalid"}
        ).status_code
        == 403
    )
    started = client.post(
        f"/streams/{stream_id}/recordings/test",
        data={"csrf_token": form_token(page.text), "recorder": "mpv", "file_type": "mp3"},
        follow_redirects=False,
    )
    assert started.status_code == 303
    with app.state.session_factory() as db:
        recording = db.scalar(select(Recording))
        recording_id, started_at = recording.id, recording.started_at
        assert recording.is_test and recording.schedule_id is None
        assert recording.recorder == "ffmpeg" and recording.file_type == "flac"
        assert recording.started_by_id == user_id
        assert re.fullmatch(
            rf"\d{{4}}-\d{{2}}-\d{{2}}_\d{{2}}-\d{{2}}-\d{{2}}_"
            rf"{file_name_base}_testaufnahme_[0-9a-f]{{6}}\.flac",
            recording.file_name,
        )
        file_name = recording.file_name
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "recording.started"))
        assert audit.details["file_name_base"] == f"{stream_name}_testaufnahme"
        assert db.scalar(select(func.count(RecordingSchedule.id))) == 0
    for path in ("/", "/recordings"):
        html = client.get(path).text
        assert "<strong>Testaufnahme</strong>" in html
        assert "24 Stunden" not in html and "24 Std" not in html
    normal = client.post(
        f"/streams/{stream_id}/recordings/start", data={"csrf_token": form_token(page.text)}
    )
    assert normal.status_code == 200
    app.state.recording_scheduler.run_due(started_at + timedelta(seconds=60))
    wait_for_status(app, recording_id, "completed")
    with app.state.session_factory() as db:
        spontaneous = db.scalar(select(Recording).where(Recording.is_test.is_(False)))
        assert spontaneous.status == "recording"
        assert f"_{file_name_base}_" in spontaneous.file_name
        assert "_testaufnahme_" not in spontaneous.file_name
        assert db.get(Recording, recording_id).is_test
    assert "<strong>Testaufnahme</strong>" in client.get("/recordings").text
    download = client.get(f"/recordings/{recording_id}/download")
    assert download.status_code == 200
    assert file_name in download.headers["content-disposition"]
    assert download.content.startswith(b"AWAS-test-recording")


def test_a_test_recorder_that_exits_early_does_not_report_success(
    app: FastAPI, admin, monkeypatch
) -> None:
    monkeypatch.setattr(
        "awas.services.recording.build_recorder_command",
        lambda *args, **kwargs: [sys.executable, "-c", "pass"],
    )
    with app.state.session_factory() as db:
        stream = Stream(
            name="Early exit",
            stream_url="https://radio.example/early",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.commit()
        recording = app.state.recording_manager.start_recording(
            db, stream=stream, actor=admin, ip_address="127.0.0.1", is_test=True
        )
        recording_id = recording.id
    failed = wait_for_status(app, recording_id, "failed")
    assert "vor dem Ende der Testaufnahme" in failed.error_message
    app.state.recording_manager.shutdown()


def test_history_type_search_recognizes_wiederholend(app: FastAPI, client: TestClient, admin):
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    now = utc_now()
    with app.state.session_factory() as db:
        stream = db.scalar(select(Stream))
        rule = RecurringSchedule(
            stream_id=stream.id,
            title="Rule A",
            recurrence_type="weekly",
            interval_count=1,
            weekday_mask=127,
            start_minute=600,
            duration_minutes=30,
            valid_from=now.date(),
            is_hidden=True,
            created_by_id=admin.id,
        )
        db.add(rule)
        db.flush()
        for title, recurrence_id in (("Sendung A", rule.id), ("Sendung B", None)):
            db.add(
                RecordingSchedule(
                    stream_id=stream.id,
                    stream_name=stream.name,
                    stream_url=stream.stream_url,
                    title=title,
                    starts_at=now - timedelta(hours=2),
                    ends_at=now - timedelta(hours=1),
                    status="completed",
                    recurrence_id=recurrence_id,
                    created_by_id=admin.id,
                )
            )
        db.commit()
    page = client.get("/history?q=Wiederholend")
    assert page.status_code == 200
    assert "Sendung A" in page.text and "Sendung B" not in page.text
