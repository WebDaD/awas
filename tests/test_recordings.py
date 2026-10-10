import io
import os
import subprocess
import time
import zipfile
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from awas.models import AuditLog, Recording, RecordingFile, RecordingSchedule, Stream
from awas.models.auth import utc_now
from awas.services.auth import create_user
from tests.conftest import form_token, login
from tests.test_streams import add_stream


def install_fake_ffmpeg(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "ffmpeg"
    executable.write_text(
        """#!/usr/bin/env python3
import signal
import sys
import time

running = True

def stop(*_):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
with open(sys.argv[-1], "wb") as output:
    output.write(b"AWAS-test-recording")
    output.flush()
    while running:
        output.write(b".")
        output.flush()
        time.sleep(0.02)
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ.get('PATH', '')}")


def wait_for_status(app: FastAPI, recording_id: int, expected: str) -> Recording:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with app.state.session_factory() as db:
            recording = db.get(Recording, recording_id)
            if recording is not None and recording.status == expected:
                return recording
        time.sleep(0.02)
    raise AssertionError(f"Recording {recording_id} did not reach status {expected}")


def test_empty_recording_list_has_no_stream_prompt(client: TestClient, admin) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303

    page = client.get("/recordings")

    assert page.status_code == 200
    assert "Keine Aufnahmen vorhanden" in page.text
    assert "Laufende Aufnahmen und Aufnahmeverlauf." not in page.text
    assert "Spontanaufnahmen können unter Streams gestartet werden." not in page.text
    assert "Streams öffnen" not in page.text
    assert 'data-filter-input="recording-list"' in page.text
    assert 'data-filter-user="recording-list"' in page.text


def test_manual_recording_start_stop_and_download(
    app: FastAPI,
    client: TestClient,
    admin,
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))

    dashboard = client.get("/streams")
    started = client.post(
        f"/streams/{stream_id}/recordings/start",
        data={"csrf_token": form_token(dashboard.text)},
        follow_redirects=False,
    )
    assert started.status_code == 303
    assert started.headers["location"] == "/streams?status=started"

    with app.state.session_factory() as db:
        recording = db.scalar(select(Recording))
        assert recording is not None
        recording_id = recording.id
        assert recording.status == "recording"
        assert recording.recorder == "ffmpeg"
        assert recording.file_name.endswith(".mp3")
        assert recording.file_type == "mp3"
        output_path = app.state.recording_manager.output_path(recording)

    deadline = time.monotonic() + 2
    while not output_path.is_file() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert output_path.is_file()

    planning = client.get("/")
    assert "Spontanaufnahme" in planning.text
    assert recording.file_name in planning.text
    assert f'href="/recordings/{recording_id}/download"' in planning.text
    assert f'action="/recordings/{recording_id}/stop"' in planning.text
    assert "Wirklich stoppen?" in planning.text

    recordings_page = client.get("/recordings")
    assert 'data-live-interval="5000"' in recordings_page.text
    assert "Speicher verwalten" not in recordings_page.text
    assert f'href="/recordings/{recording_id}/download"' in recordings_page.text
    assert (
        'class="recording-data-row recording-data-row-with-file recording-active-row"'
        in recordings_page.text
    )
    assert 'class="recording-file-row recording-active-row"' in recordings_page.text
    assert 'class="table-detail-value"' in recordings_page.text
    assert recording.file_name in recordings_page.text
    assert recordings_page.text.index("<small>Spontan</small>") < recordings_page.text.index(
        "<small>von AWAS Admin</small>"
    )
    file_name_position = recordings_page.text.index(recording.file_name)
    file_size_position = recordings_page.text.index('class="table-detail-value"')
    assert file_name_position < file_size_position
    running_download = client.get(f"/recordings/{recording_id}/download")
    assert running_download.status_code == 200
    assert running_download.content.startswith(b"AWAS-test-recording")
    assert int(running_download.headers["content-length"]) == len(running_download.content)
    streams_page = client.get("/streams")
    assert 'class="stream-data-row recording-active-row"' in streams_page.text
    assert 'class="stream-url-row recording-active-row"' in streams_page.text
    second = client.post(
        f"/streams/{stream_id}/recordings/start",
        data={"csrf_token": form_token(recordings_page.text)},
        follow_redirects=False,
    )
    assert second.status_code == 303
    with app.state.session_factory() as db:
        recording_ids = list(db.scalars(select(Recording.id).order_by(Recording.id)))
    assert len(recording_ids) == 2
    second_recording_id = recording_ids[-1]

    unconfirmed_stop = client.post(
        f"/recordings/{recording_id}/stop",
        data={"csrf_token": form_token(recordings_page.text)},
    )
    assert unconfirmed_stop.status_code == 400
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id).status == "recording"

    stopped = client.post(
        f"/recordings/{recording_id}/stop",
        data={
            "csrf_token": form_token(recordings_page.text),
            "stop_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert stopped.status_code == 303
    recording = wait_for_status(app, recording_id, "completed")
    assert recording.ended_at is not None
    assert recording.file_size_bytes is not None
    assert recording.file_size_bytes > 0

    download = client.get(f"/recordings/{recording_id}/download")
    assert download.status_code == 200
    assert download.content.startswith(b"AWAS-test-recording")
    assert "attachment" in download.headers["content-disposition"]

    page = client.get("/recordings")
    stopped_second = client.post(
        f"/recordings/{second_recording_id}/stop",
        data={
            "csrf_token": form_token(page.text),
            "stop_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert stopped_second.status_code == 303
    wait_for_status(app, second_recording_id, "completed")

    with app.state.session_factory() as db:
        actions = set(db.scalars(select(AuditLog.action)))
        assert {
            "recording.started",
            "recording.stop_requested",
            "recording.completed",
        } <= actions

    confirmation = client.get("/streams")
    deleted_stream = client.post(
        f"/admin/streams/{stream_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted_stream.status_code == 303
    assert deleted_stream.headers["location"] == "/streams?status=deleted"

    with app.state.session_factory() as db:
        recording = db.get(Recording, recording_id)
        assert recording is not None
        assert recording.stream_id is None
        assert recording.stream_name == "Radio Eins"
        assert db.get(Stream, stream_id) is None

    history = client.get("/recordings")
    assert recording.file_name in history.text
    assert client.get(f"/recordings/{recording_id}/download").status_code == 200


def test_startup_marks_orphaned_recording_as_interrupted(
    app: FastAPI,
    admin,
) -> None:
    with app.state.session_factory() as db:
        stream = Stream(
            name="Orphan Stream",
            stream_url="https://radio.example/orphan",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name="orphan.mka",
            status="recording",
            started_at=utc_now(),
            started_by_id=admin.id,
        )
        db.add(recording)
        db.commit()
        recording_id = recording.id

    app.state.recording_manager.reconcile_interrupted()

    with app.state.session_factory() as db:
        recording = db.get(Recording, recording_id)
        assert recording.status == "interrupted"
        assert recording.ended_at is not None
        assert "neu gestartet" in recording.error_message


def test_recorder_stderr_is_inherited_instead_of_buffered(
    app: FastAPI,
    admin,
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    real_popen = subprocess.Popen
    captured_kwargs: dict[str, object] = {}

    def capturing_popen(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return real_popen(*args, **kwargs)

    monkeypatch.setattr("awas.services.recording.subprocess.Popen", capturing_popen)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Standardfehler Stream",
            stream_url="https://radio.example/stderr",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        recording = app.state.recording_manager.start_recording(
            db,
            stream=stream,
            actor=admin,
            ip_address="127.0.0.1",
        )
        recording_id = recording.id
        assert "stderr" not in captured_kwargs
        app.state.recording_manager.stop_recording(
            db,
            recording=recording,
            actor=admin,
            ip_address="127.0.0.1",
        )
    wait_for_status(app, recording_id, "completed")


def test_streamripper_cue_file_is_removed_when_recording_ends(
    app: FastAPI,
    admin,
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "fake-streamripper"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "import sys\n"
        "output = pathlib.Path(sys.argv[1])\n"
        "output.write_bytes(b'recorded-audio')\n"
        "output.with_suffix('.cue').write_text('cue data', encoding='utf-8')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    def build_fake_command(*_args, output_path, **_kwargs):
        return [str(executable), str(output_path)]

    monkeypatch.setattr(
        "awas.services.recording.build_recorder_command",
        build_fake_command,
    )
    with app.state.session_factory() as db:
        stream = Stream(
            name="Cue Stream",
            stream_url="http://radio.example/cue",
            preferred_recorder="streamripper",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        recording = app.state.recording_manager.start_recording(
            db,
            stream=stream,
            actor=admin,
            ip_address="127.0.0.1",
        )
        recording_id = recording.id
        output_path = Path(recording.storage_directory) / recording.file_name

    wait_for_status(app, recording_id, "completed")
    assert output_path.is_file()
    assert not output_path.with_suffix(".cue").exists()


def test_streamripper_segments_are_listed_downloaded_as_zip_and_deleted_together(
    app: FastAPI,
    client: TestClient,
    admin,
    tmp_path: Path,
    monkeypatch,
) -> None:
    executable = tmp_path / "segmented-streamripper"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib\n"
        "import sys\n"
        "output = pathlib.Path(sys.argv[1])\n"
        "stable = output.stem[20:]\n"
        "first = output.with_name(f'2026_09_30_13_40_00_{stable}{output.suffix}')\n"
        "first.write_bytes(b'first-segment')\n"
        "second = output.with_name(f'2026_09_30_14_10_00_{stable}{output.suffix}')\n"
        "second.write_bytes(b'second-segment')\n"
        "output.write_bytes(b'legacy-segment')\n"
        "legacy = output.with_name(f'{output.stem} (1){output.suffix}')\n"
        "legacy.write_bytes(b'legacy-numbered-segment')\n"
        "first.with_suffix('.cue').write_text('cue', encoding='utf-8')\n"
        "second.with_suffix('.cue').write_text('cue', encoding='utf-8')\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)

    def build_fake_command(*_args, output_path, **_kwargs):
        return [str(executable), str(output_path)]

    monkeypatch.setattr(
        "awas.services.recording.build_recorder_command",
        build_fake_command,
    )
    with app.state.session_factory() as db:
        stream = Stream(
            name="Segment Stream",
            stream_url="http://radio.example/segments",
            preferred_recorder="streamripper",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        recording = app.state.recording_manager.start_recording(
            db,
            stream=stream,
            actor=admin,
            ip_address="127.0.0.1",
        )
        recording_id = recording.id
        output_path = Path(recording.storage_directory) / recording.file_name

    wait_for_status(app, recording_id, "completed")
    stable_stem = output_path.stem[20:]
    segment_paths = [
        output_path.with_name(
            f"2026_09_30_13_40_00_{stable_stem}{output_path.suffix}"
        ),
        output_path.with_name(
            f"2026_09_30_14_10_00_{stable_stem}{output_path.suffix}"
        ),
        output_path,
        output_path.with_name(f"{output_path.stem} (1){output_path.suffix}"),
    ]
    assert all(path.is_file() for path in segment_paths)
    assert not segment_paths[0].with_suffix(".cue").exists()
    assert not segment_paths[1].with_suffix(".cue").exists()

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    listing = client.get("/recordings")
    assert listing.status_code == 200
    assert all(path.name in listing.text for path in segment_paths)
    with app.state.session_factory() as db:
        assert len(
            list(
                db.scalars(
                    select(RecordingFile).where(
                        RecordingFile.recording_id == recording_id
                    )
                )
            )
        ) == 4

    download = client.get(f"/recordings/{recording_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(download.content)) as archive:
        assert set(archive.namelist()) == {path.name for path in segment_paths}
        assert archive.read(segment_paths[0].name) == b"first-segment"
        assert archive.read(segment_paths[1].name) == b"second-segment"
        assert archive.read(segment_paths[2].name) == b"legacy-segment"
        assert archive.read(segment_paths[3].name) == b"legacy-numbered-segment"

    deleted = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(listing.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert not any(path.exists() for path in segment_paths)
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is None
        assert db.scalar(select(RecordingFile.id)) is None


def test_normal_user_can_start_and_stop_recording(
    app: FastAPI,
    client: TestClient,
    admin,
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    with app.state.session_factory() as db:
        stream = Stream(
            name="User Stream",
            stream_url="https://radio.example/user",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        create_user(
            db,
            username="listener",
            display_name="Listener",
            password="listener",
            password_confirmation="listener",
            role="user",
            must_change_password=False,
        )
        db.commit()
        stream_id = stream.id

    assert login(client, "listener", "listener").status_code == 303
    dashboard = client.get("/streams")
    started = client.post(
        f"/streams/{stream_id}/recordings/start",
        data={"csrf_token": form_token(dashboard.text)},
        follow_redirects=False,
    )
    assert started.status_code == 303
    with app.state.session_factory() as db:
        recording_id = db.scalar(select(Recording.id))

    page = client.get("/recordings")
    stopped = client.post(
        f"/recordings/{recording_id}/stop",
        data={
            "csrf_token": form_token(page.text),
            "stop_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert stopped.status_code == 303
    wait_for_status(app, recording_id, "completed")


def create_finished_recording(
    app: FastAPI,
    admin,
    *,
    file_name: str = "finished.mka",
    status: str = "completed",
    create_file: bool = True,
    with_schedule: bool = False,
) -> tuple[int, Path]:
    with app.state.session_factory() as db:
        stream = Stream(
            name="Stored Stream",
            stream_url="https://radio.example/stored",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = None
        if with_schedule:
            starts_at = utc_now()
            schedule = RecordingSchedule(
                stream_id=stream.id,
                title="Stored schedule",
                recorder="ffmpeg",
                starts_at=starts_at,
                ends_at=starts_at + timedelta(minutes=30),
                status="completed",
                created_by_id=admin.id,
            )
            db.add(schedule)
            db.flush()
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name=file_name,
            recorder="ffmpeg",
            status=status,
            started_at=utc_now(),
            ended_at=utc_now() if status != "recording" else None,
            file_size_bytes=18 if create_file else None,
            started_by_id=admin.id,
            schedule_id=schedule.id if schedule else None,
        )
        db.add(recording)
        db.commit()
        recording_id = recording.id
        output_path = app.state.recording_manager.output_path(recording)
    if create_file:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"stored-audio-bytes")
    return recording_id, output_path


def test_admin_deletes_recording_and_file_but_keeps_schedule(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    recording_id, output_path = create_finished_recording(app, admin, with_schedule=True)
    assert login(client, "admin", "a-secure-admin-password").status_code == 303

    listing = client.get("/recordings")
    assert "Speicherübersicht" in listing.text
    assert "Aufnahmeeinträge" not in listing.text
    assert "<span>Aufnahmen</span>" in listing.text
    assert f"Aufnahmepfad {app.state.recording_manager.recording_directory}" in listing.text
    assert "Auf dem Aufnahmedatenträger" not in listing.text
    assert f'/recordings/{recording_id}/delete"' in listing.text
    assert f'data-filter-user-id="{admin.id}"' in listing.text
    assert 'data-filter-row="recording-list"' in listing.text
    assert 'data-filter-companion="recording-' in listing.text
    assert "data-copy-stream-url" not in listing.text
    assert "Datei löschen" not in listing.text
    assert "Eintrag löschen" not in listing.text
    assert listing.text.index("<small>Zeitplan</small>") < listing.text.index(
        "<small>von AWAS Admin</small>"
    )
    assert client.get(f"/recordings/{recording_id}/delete").status_code == 405
    assert 'data-action-confirm' in listing.text
    assert "Wirklich löschen?" in listing.text

    deleted = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(listing.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert deleted.headers["location"] == "/recordings?status=deleted"
    assert not output_path.exists()
    assert not list(output_path.parent.glob(".awas-delete-*.pending"))
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is None
        schedule = db.scalar(select(RecordingSchedule))
        assert schedule is not None
        assert schedule.title == "Stored schedule"
        assert schedule.status == "completed"
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "recording.deleted"))
        assert audit is not None
        assert audit.target_id == recording_id
        assert audit.details["file_name"] == "finished.mka"
        assert audit.details["file_removed"] is True

    history = client.get("/history")
    assert "Stored schedule" in history.text
    assert "Abgeschlossen" in history.text


def test_missing_recording_file_and_entry_can_be_deleted(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    recording_id, output_path = create_finished_recording(
        app,
        admin,
        file_name="missing.mka",
        create_file=False,
    )
    assert not output_path.exists()
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    confirmation = client.get("/recordings")
    deleted = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is None
        audit = db.scalar(select(AuditLog).where(AuditLog.action == "recording.deleted"))
        assert audit is not None
        assert audit.details["file_removed"] is False


def test_running_recording_cannot_be_deleted(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    recording_id, output_path = create_finished_recording(
        app,
        admin,
        file_name="running.mka",
        status="recording",
    )
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    confirmation = client.get("/recordings")
    assert f'/recordings/{recording_id}/delete"' not in confirmation.text
    rejected = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
    )
    assert rejected.status_code == 400
    assert output_path.exists()
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is not None


def test_normal_user_cannot_delete_another_users_recording(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    recording_id, output_path = create_finished_recording(app, admin)
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
    listing = client.get("/recordings")
    assert f'href="/recordings/{recording_id}/download"' in listing.text
    assert client.get(f"/recordings/{recording_id}/download").status_code == 200
    assert f'/recordings/{recording_id}/delete"' not in listing.text
    rejected = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(listing.text),
            "delete_confirmed": "true",
        },
    )
    assert rejected.status_code == 403
    assert output_path.exists()
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is not None


def test_normal_user_sees_but_cannot_stop_another_users_running_recording(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    recording_id, output_path = create_finished_recording(
        app,
        admin,
        file_name="admin-running.mp3",
        status="recording",
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
    assert login(client, "listener", "listener").status_code == 303

    planning = client.get("/")
    assert "Spontanaufnahme" in planning.text
    assert "admin-running.mp3" in planning.text
    assert f'href="/recordings/{recording_id}/download"' in planning.text
    assert f'action="/recordings/{recording_id}/stop"' not in planning.text
    assert client.get(f"/recordings/{recording_id}/download").status_code == 200

    rejected = client.post(
        f"/recordings/{recording_id}/stop",
        data={
            "csrf_token": form_token(planning.text),
            "stop_confirmed": "true",
        },
    )
    assert rejected.status_code == 403
    assert output_path.exists()
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id).status == "recording"


def test_normal_user_deletes_own_recording_and_file(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    with app.state.session_factory() as db:
        owner = create_user(
            db,
            username="listener",
            display_name="Listener",
            password="listener",
            password_confirmation="listener",
            role="user",
            must_change_password=False,
        )
    recording_id, output_path = create_finished_recording(
        app,
        owner,
        file_name="listener-own.mp3",
    )
    assert login(client, "listener", "listener").status_code == 303

    listing = client.get("/recordings")
    assert f'/recordings/{recording_id}/delete"' in listing.text
    unconfirmed = client.post(
        f"/recordings/{recording_id}/delete",
        data={"csrf_token": form_token(listing.text)},
    )
    assert unconfirmed.status_code == 400
    assert output_path.exists()

    deleted = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(listing.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    assert not output_path.exists()
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is None


def test_recording_delete_rejects_path_outside_storage(
    app: FastAPI,
    client: TestClient,
    admin,
    tmp_path: Path,
) -> None:
    outside_path = tmp_path / "outside.mka"
    outside_path.write_bytes(b"must-stay")
    with app.state.session_factory() as db:
        stream = Stream(
            name="Unsafe Path Stream",
            stream_url="https://radio.example/unsafe",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name="../outside.mka",
            status="completed",
            started_at=utc_now(),
            ended_at=utc_now(),
            file_size_bytes=outside_path.stat().st_size,
            started_by_id=admin.id,
        )
        db.add(recording)
        db.commit()
        recording_id = recording.id

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    confirmation = client.get("/recordings")
    rejected = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
    )
    assert rejected.status_code == 400
    assert "Ungültiger Aufnahmepfad" in rejected.text
    assert outside_path.read_bytes() == b"must-stay"
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is not None


def test_recording_delete_rejects_symbolic_link(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    recording_id, output_path = create_finished_recording(
        app,
        admin,
        file_name="linked.mka",
        create_file=False,
    )
    target_path = output_path.parent / "link-target.mka"
    target_path.write_bytes(b"must-stay")
    output_path.symlink_to(target_path.name)

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    confirmation = client.get("/recordings")
    rejected = client.post(
        f"/recordings/{recording_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
    )
    assert rejected.status_code == 400
    assert "Ungültiger Aufnahmepfad" in rejected.text
    assert output_path.is_symlink()
    assert target_path.read_bytes() == b"must-stay"
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is not None


def test_interrupted_deletion_is_reconciled(app: FastAPI, admin) -> None:
    recording_id, output_path = create_finished_recording(
        app,
        admin,
        create_file=False,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staged_path = output_path.parent / f".awas-delete-{recording_id}-deadbeef.pending"
    staged_path.write_bytes(b"recover-me")

    app.state.recording_manager.reconcile_staged_deletions()
    assert output_path.read_bytes() == b"recover-me"
    assert not staged_path.exists()

    with app.state.session_factory() as db:
        db.delete(db.get(Recording, recording_id))
        db.commit()
    output_path.replace(staged_path)
    app.state.recording_manager.reconcile_staged_deletions()
    assert not staged_path.exists()
    assert not output_path.exists()
