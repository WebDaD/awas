from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text

from awas.models import AuditLog, Recording, RecordingSchedule, Stream, WebSession
from awas.models.auth import utc_now
from awas.services.auth import create_user
from tests.conftest import form_token, login


def set_database_revision(app: FastAPI) -> None:
    with app.state.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS alembic_version "
                "(version_num VARCHAR(32) NOT NULL)"
            )
        )
        connection.execute(text("DELETE FROM alembic_version"))
        connection.execute(
            text("INSERT INTO alembic_version (version_num) VALUES ('0021')")
        )


def test_admin_exports_complete_database(
    app: FastAPI,
    client: TestClient,
    admin,
    tmp_path: Path,
) -> None:
    set_database_revision(app)
    with app.state.session_factory() as db:
        db.add(
            Stream(
                name="Export Stream",
                stream_url="https://radio.example/export",
                created_by_id=admin.id,
            )
        )
        db.commit()
    assert login(client, "admin", "a-secure-admin-password").status_code == 303

    response = client.get("/admin/storage/database/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.sqlite3"
    assert "awas-database-" in response.headers["content-disposition"]
    assert response.content.startswith(b"SQLite format 3\x00")
    export_path = tmp_path / "export.db"
    export_path.write_bytes(response.content)
    with sqlite3.connect(export_path) as connection:
        assert connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone() == ("0021",)
        assert connection.execute(
            "SELECT name FROM streams WHERE name = 'Export Stream'"
        ).fetchone() == ("Export Stream",)
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {
        "users",
        "sessions",
        "streams",
        "recordings",
        "recording_files",
        "recording_schedules",
        "recurring_schedules",
        "recorder_settings",
        "retention_policy",
        "storage_configuration",
    } <= tables
    with app.state.session_factory() as db:
        assert db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.action == "database.exported")
        ) == 1


def test_database_export_and_import_require_admin(
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
    page = client.get("/")

    assert client.get("/admin/storage/database/export").status_code == 403
    imported = client.post(
        "/admin/storage/database/import",
        data={"csrf_token": form_token(page.text)},
        files={"database_file": ("backup.db", b"not a database")},
    )
    assert imported.status_code == 403


def test_admin_imports_backup_and_keeps_only_current_session(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    set_database_revision(app)
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    with app.state.session_factory() as db:
        db.add(
            Stream(
                name="Stand der Sicherung",
                stream_url="https://radio.example/backup",
                created_by_id=admin.id,
            )
        )
        db.add(
            WebSession(
                token_hash="f" * 64,
                user_id=admin.id,
                created_at=utc_now(),
                last_seen_at=utc_now(),
                expires_at=utc_now() + timedelta(days=1),
                ip_address="127.0.0.1",
                user_agent="stale test session",
            )
        )
        db.commit()

    backup = client.get("/admin/storage/database/export")
    assert backup.status_code == 200
    with app.state.session_factory() as db:
        stream = db.scalar(select(Stream).where(Stream.name == "Stand der Sicherung"))
        assert stream is not None
        stream.name = "Geänderter Live-Stand"
        db.commit()

    page = client.get("/admin/storage")
    imported = client.post(
        "/admin/storage/database/import",
        data={"csrf_token": form_token(page.text)},
        files={
            "database_file": (
                "awas-backup.db",
                backup.content,
                "application/vnd.sqlite3",
            )
        },
        follow_redirects=False,
    )

    assert imported.status_code == 303
    assert imported.headers["location"] == "/admin/storage?status=database-imported"
    assert client.get("/").status_code == 200
    with app.state.session_factory() as db:
        assert db.scalar(select(Stream.name)) == "Stand der Sicherung"
        assert db.scalar(select(func.count(WebSession.id))) == 1
        assert db.scalar(
            select(func.count(AuditLog.id)).where(AuditLog.action == "database.imported")
        ) == 1


def test_database_round_trip_preserves_schedule_history(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    set_database_revision(app)
    now = utc_now()
    with app.state.session_factory() as db:
        stream = Stream(
            name="Historienstream",
            stream_url="https://radio.example/history",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        for position, (title, status) in enumerate(
            (
                ("Abgeschlossene Historie", "completed"),
                ("Verpasste Historie", "missed"),
                ("Fehlgeschlagene Historie", "failed"),
                ("Verworfener Zeitplan", "cancelled"),
            )
        ):
            starts_at = now - timedelta(hours=position + 2)
            db.add(
                RecordingSchedule(
                    stream_id=stream.id,
                    title=title,
                    file_name_base=f"history-{position}",
                    recorder="ffmpeg",
                    file_type="mp3",
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=30),
                    status=status,
                    is_hidden=False,
                    created_by_id=admin.id,
                )
            )
        db.commit()

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    before_export = client.get("/history")
    assert "Abgeschlossene Historie" in before_export.text
    assert "Verpasste Historie" in before_export.text
    assert "Fehlgeschlagene Historie" in before_export.text
    assert "Verworfener Zeitplan" not in before_export.text

    backup = client.get("/admin/storage/database/export")
    assert backup.status_code == 200

    with app.state.session_factory() as db:
        db.execute(delete(RecordingSchedule))
        db.commit()
    without_history = client.get("/history")
    assert "Abgeschlossene Historie" not in without_history.text

    page = client.get("/admin/storage")
    imported = client.post(
        "/admin/storage/database/import",
        data={"csrf_token": form_token(page.text)},
        files={
            "database_file": (
                "awas-history-backup.db",
                backup.content,
                "application/vnd.sqlite3",
            )
        },
        follow_redirects=False,
    )

    assert imported.status_code == 303
    assert imported.headers["location"] == "/admin/storage?status=database-imported"
    after_import = client.get("/history")
    assert "Abgeschlossene Historie" in after_import.text
    assert "Verpasste Historie" in after_import.text
    assert "Fehlgeschlagene Historie" in after_import.text
    assert "Verworfener Zeitplan" not in after_import.text
    with app.state.session_factory() as db:
        statuses = set(db.scalars(select(RecordingSchedule.status)))
        assert statuses == {"completed", "missed", "failed", "cancelled"}


def test_database_import_rejects_invalid_file(
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    page = client.get("/admin/storage")

    response = client.post(
        "/admin/storage/database/import",
        data={"csrf_token": form_token(page.text)},
        files={"database_file": ("broken.db", b"kein sqlite")},
    )

    assert response.status_code == 400
    assert "keine SQLite-Datenbank" in response.text


def test_database_import_is_blocked_while_recording_is_active(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    set_database_revision(app)
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    backup = client.get("/admin/storage/database/export")
    assert backup.status_code == 200
    with app.state.session_factory() as db:
        stream = Stream(
            name="Running Stream",
            stream_url="https://radio.example/running",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name="running.mp3",
            recorder="ffmpeg",
            file_type="mp3",
            status="recording",
            started_at=utc_now(),
            started_by_id=admin.id,
        )
        db.add(recording)
        db.commit()
        recording_id = recording.id

    page = client.get("/admin/storage")
    response = client.post(
        "/admin/storage/database/import",
        data={"csrf_token": form_token(page.text)},
        files={"database_file": ("backup.db", backup.content)},
    )

    assert response.status_code == 400
    assert "solange Aufnahmen laufen" in response.text
    with app.state.session_factory() as db:
        assert db.get(Recording, recording_id) is not None
