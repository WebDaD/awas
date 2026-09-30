from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from awas.models import (
    AuditLog,
    Recording,
    RetentionPolicy,
    StorageConfiguration,
    Stream,
)
from awas.models.auth import utc_now
from awas.services import retention as retention_service
from awas.services.auth import create_user
from awas.services.retention import update_retention_policy
from tests.conftest import form_token, login
from tests.test_recordings import install_fake_ffmpeg, wait_for_status
from tests.test_streams import add_stream


def create_recording(
    app: FastAPI,
    admin,
    *,
    file_name: str,
    age_days: int,
    status: str = "completed",
    contents: bytes = b"retention-test-audio",
) -> tuple[int, Path]:
    ended_at = None if status in {"starting", "recording", "stopping"} else (
        utc_now() - timedelta(days=age_days)
    )
    with app.state.session_factory() as db:
        stream = Stream(
            name=f"Retention Stream {file_name}",
            stream_url=f"https://radio.example/{file_name}",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name=file_name,
            status=status,
            started_at=utc_now() - timedelta(days=age_days, hours=1),
            ended_at=ended_at,
            file_size_bytes=len(contents),
            started_by_id=admin.id,
        )
        db.add(recording)
        db.commit()
        recording_id = recording.id
        path = app.state.recording_manager.output_path(recording)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(contents)
    return recording_id, path


def test_storage_settings_are_admin_only(
    app: FastAPI,
    client: TestClient,
    admin,
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
    assert client.get("/admin/storage").status_code == 403
    client.post(
        "/logout",
        data={"csrf_token": form_token(client.get("/").text)},
    )
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/storage")
    assert "Aufnahmen öffnen" not in page.text
    assert page.status_code == 200
    assert "Automatische Aufbewahrung" in page.text
    assert "Automatik deaktiviert" in page.text
    assert 'data-live-interval="5000"' in page.text
    assert "normal-meta" in page.text
    assert '<p class="eyebrow">Administration</p>' in page.text
    assert "Aufnahmepfad" in page.text
    assert "awas-service" in page.text


def test_admin_changes_recording_directory_only_for_new_recordings(
    app: FastAPI,
    client: TestClient,
    admin,
    tmp_path: Path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    old_id, old_path = create_recording(
        app,
        admin,
        file_name="old-location.mp3",
        age_days=1,
    )
    new_directory = tmp_path / "new-recordings"
    new_directory.mkdir()

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client, name="New Location Stream").status_code == 303
    storage_page = client.get("/admin/storage")
    default_directory = app.state.settings.recording.directory.resolve()
    assert f'value="{default_directory}"' in storage_page.text

    saved = client.post(
        "/admin/storage/directory",
        data={
            "recording_directory": str(new_directory),
            "csrf_token": form_token(storage_page.text),
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/admin/storage?status=directory-saved"
    assert app.state.recording_manager.recording_directory == new_directory.resolve()
    with app.state.session_factory() as db:
        configuration = db.get(StorageConfiguration, 1)
        assert configuration.recording_directory == str(new_directory.resolve())
        assert configuration.updated_by_id == admin.id
        assert db.scalar(
            select(AuditLog).where(AuditLog.action == "storage.directory.updated")
        )
        stream_id = db.scalar(
            select(Stream.id).where(Stream.name == "New Location Stream")
        )

    stream_page = client.get("/streams")
    started = client.post(
        f"/streams/{stream_id}/recordings/start",
        data={"csrf_token": form_token(stream_page.text)},
        follow_redirects=False,
    )
    assert started.status_code == 303
    with app.state.session_factory() as db:
        recording = db.scalar(
            select(Recording)
            .where(Recording.stream_id == stream_id)
            .order_by(Recording.id.desc())
        )
        assert recording.storage_directory == str(new_directory.resolve())
        new_recording_id = recording.id
        assert app.state.recording_manager.output_path(recording).parent == new_directory.resolve()

    recordings_page = client.get("/recordings")
    stopped = client.post(
        f"/recordings/{new_recording_id}/stop",
        data={
            "csrf_token": form_token(recordings_page.text),
            "stop_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert stopped.status_code == 303
    wait_for_status(app, new_recording_id, "completed")
    assert old_path.exists()
    assert client.get(f"/recordings/{old_id}/download").status_code == 200


def test_recording_directory_rejects_relative_or_missing_paths(
    client: TestClient,
    admin,
    tmp_path: Path,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/storage")
    relative = client.post(
        "/admin/storage/directory",
        data={
            "recording_directory": "relative/path",
            "csrf_token": form_token(page.text),
        },
    )
    assert relative.status_code == 400
    assert "muss absolut sein" in relative.text

    missing = client.post(
        "/admin/storage/directory",
        data={
            "recording_directory": str(tmp_path / "missing"),
            "csrf_token": form_token(relative.text),
        },
    )
    assert missing.status_code == 400
    assert "existiert nicht" in missing.text


def test_admin_updates_retention_policy(
    app: FastAPI,
    client: TestClient,
    admin,
    monkeypatch,
) -> None:
    monkeypatch.setattr(app.state.retention_manager, "wake", lambda: None)
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/storage")
    invalid = client.post(
        "/admin/storage",
        data={
            "retention_days": "0",
            "enabled": "on",
            "csrf_token": form_token(page.text),
        },
    )
    assert invalid.status_code == 400
    assert "zwischen 1 und 3650 Tagen" in invalid.text

    saved = client.post(
        "/admin/storage",
        data={
            "retention_days": "30",
            "enabled": "on",
            "csrf_token": form_token(invalid.text),
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert saved.headers["location"] == "/admin/storage?status=saved"
    with app.state.session_factory() as db:
        policy = db.get(RetentionPolicy, 1)
        assert policy.enabled is True
        assert policy.retention_days == 30
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "retention.policy.updated")
        )
        assert audit is not None
        assert audit.actor_user_id == admin.id
        assert audit.details["previous"] == {"enabled": False, "retention_days": 90}


def test_manual_cleanup_deletes_only_expired_terminal_recordings(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    old_id, old_path = create_recording(
        app,
        admin,
        file_name="old.mka",
        age_days=100,
    )
    recent_id, recent_path = create_recording(
        app,
        admin,
        file_name="recent.mka",
        age_days=10,
    )
    running_id, running_path = create_recording(
        app,
        admin,
        file_name="running-retention.mka",
        age_days=100,
        status="recording",
    )
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/storage")
    assert "1 abgelaufene Aufnahme" in page.text
    assert client.get("/admin/storage/cleanup").status_code == 405
    rejected = client.post(
        "/admin/storage/cleanup",
        data={"csrf_token": form_token(page.text)},
    )
    assert rejected.status_code == 400
    assert old_path.exists()

    cleaned = client.post(
        "/admin/storage/cleanup",
        data={
            "delete_confirmed": "true",
            "csrf_token": form_token(page.text),
        },
        follow_redirects=False,
    )
    assert cleaned.status_code == 303
    assert cleaned.headers["location"] == "/admin/storage?status=cleaned"
    assert not old_path.exists()
    assert recent_path.exists()
    assert running_path.exists()
    with app.state.session_factory() as db:
        old_recording = db.get(Recording, old_id)
        assert old_recording is not None
        assert old_recording.file_deleted_at is not None
        assert old_recording.file_delete_reason == "retention.manual"
        assert db.get(Recording, recent_id) is not None
        assert db.get(Recording, running_id) is not None
        deleted = db.scalar(
            select(AuditLog).where(AuditLog.action == "recording.file_deleted")
        )
        assert deleted.details["reason"] == "retention.manual"
        cleanup = db.scalar(
            select(AuditLog).where(AuditLog.action == "retention.cleanup.completed")
        )
        assert cleanup.details["deleted_count"] == 1


def test_automatic_cleanup_honors_enabled_setting(app: FastAPI, admin) -> None:
    recording_id, output_path = create_recording(
        app,
        admin,
        file_name="automatic.mka",
        age_days=100,
    )
    manager = app.state.retention_manager
    disabled = manager.run_automatic()
    assert disabled.skipped is True
    assert output_path.exists()

    with app.state.session_factory() as db:
        policy = db.get(RetentionPolicy, 1)
        update_retention_policy(
            db,
            policy,
            enabled=True,
            retention_days=30,
            actor=admin,
            ip_address="127.0.0.1",
        )
    result = manager.run_automatic()
    assert result.skipped is False
    assert result.deleted_count == 1
    assert not output_path.exists()
    with app.state.session_factory() as db:
        recording = db.get(Recording, recording_id)
        assert recording is not None
        assert recording.file_deleted_at is not None
        assert recording.file_delete_reason == "retention.automatic"
        policy = db.get(RetentionPolicy, 1)
        assert policy.last_run_mode == "automatic"
        assert policy.last_deleted_count == 1
        audit = db.scalar(
            select(AuditLog).where(AuditLog.action == "recording.file_deleted")
        )
        assert audit.details["reason"] == "retention.automatic"


def test_cleanup_continues_after_unsafe_path(app: FastAPI, admin, tmp_path: Path) -> None:
    outside_path = tmp_path / "outside-retention.mka"
    outside_path.write_bytes(b"keep-me")
    with app.state.session_factory() as db:
        stream = Stream(
            name="Unsafe Retention Stream",
            stream_url="https://radio.example/unsafe-retention",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        unsafe = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name="../outside-retention.mka",
            status="completed",
            started_at=utc_now() - timedelta(days=121),
            ended_at=utc_now() - timedelta(days=120),
            file_size_bytes=outside_path.stat().st_size,
            started_by_id=admin.id,
        )
        db.add(unsafe)
        db.commit()
        unsafe_id = unsafe.id
    good_id, good_path = create_recording(
        app,
        admin,
        file_name="safe-after-error.mka",
        age_days=100,
    )

    result = app.state.retention_manager.run_cleanup(mode="manual", actor=admin)
    assert result.deleted_count == 1
    assert result.failed_count == 1
    assert outside_path.read_bytes() == b"keep-me"
    assert not good_path.exists()
    with app.state.session_factory() as db:
        assert db.get(Recording, unsafe_id) is not None
        good_recording = db.get(Recording, good_id)
        assert good_recording is not None
        assert good_recording.file_deleted_at is not None
        policy = db.get(RetentionPolicy, 1)
        assert policy.last_failed_count == 1
        assert policy.last_error is not None


def test_cleanup_respects_per_run_limit(app: FastAPI, admin, monkeypatch) -> None:
    recording_ids = [
        create_recording(
            app,
            admin,
            file_name=f"limited-{index}.mka",
            age_days=100 + index,
        )[0]
        for index in range(3)
    ]
    monkeypatch.setattr(retention_service, "MAX_DELETIONS_PER_RUN", 2)

    result = app.state.retention_manager.run_cleanup(mode="manual", actor=admin)
    assert result.eligible_count == 3
    assert result.deleted_count == 2
    with app.state.session_factory() as db:
        deleted = [
            recording_id
            for recording_id in recording_ids
            if db.get(Recording, recording_id).file_deleted_at is not None
        ]
        assert len(deleted) == 2
        assert db.scalar(select(Recording.id).where(Recording.file_deleted_at.is_(None)))


def test_cleanup_counts_only_bytes_removed_from_disk(app: FastAPI, admin) -> None:
    recording_id, output_path = create_recording(
        app,
        admin,
        file_name="already-missing.mka",
        age_days=100,
    )
    output_path.unlink()

    result = app.state.retention_manager.run_cleanup(mode="manual", actor=admin)
    assert result.deleted_count == 1
    assert result.freed_bytes == 0
    with app.state.session_factory() as db:
        recording = db.get(Recording, recording_id)
        assert recording is not None
        assert recording.file_deleted_at is not None
        policy = db.get(RetentionPolicy, 1)
        assert policy.last_freed_bytes == 0


def test_retention_cleans_all_attempts_and_files_as_one_recording(
    app: FastAPI,
    admin,
) -> None:
    first_id, first_path = create_recording(
        app,
        admin,
        file_name="group-first.mka",
        age_days=110,
        contents=b"first",
    )
    second_id, second_path = create_recording(
        app,
        admin,
        file_name="group-second.mka",
        age_days=100,
        contents=b"second",
    )
    with app.state.session_factory() as db:
        first = db.get(Recording, first_id)
        second = db.get(Recording, second_id)
        second.group_key = first.group_key
        db.commit()

    result = app.state.retention_manager.run_cleanup(mode="manual", actor=admin)

    assert result.eligible_count == 1
    assert result.deleted_count == 1
    assert result.freed_bytes == len(b"firstsecond")
    assert not first_path.exists()
    assert not second_path.exists()
    with app.state.session_factory() as db:
        assert db.get(Recording, first_id).file_deleted_at is not None
        assert db.get(Recording, second_id).file_deleted_at is not None
