from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from awas.models import AuditLog, Recording, RecordingSchedule, RecurringSchedule, Stream
from awas.models.auth import utc_now
from awas.services.auth import create_user
from awas.services.streams import StreamCheckResult
from tests.conftest import form_token, login


def add_stream(
    client: TestClient,
    *,
    name: str = "Radio Eins",
    stream_url: str = "https://radio.example/stream",
    preferred_recorder: str = "ffmpeg",
    preferred_file_type: str = "mp3",
):
    page = client.get("/admin/streams/new")
    data = {
        "name": name,
        "stream_url": stream_url,
        "preferred_recorder": preferred_recorder,
        "preferred_file_type": preferred_file_type,
        "csrf_token": form_token(page.text),
    }
    return client.post("/admin/streams", data=data, follow_redirects=False)


def test_admin_manages_stream_lifecycle(
    app: FastAPI, client: TestClient, admin
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    created = add_stream(client)
    assert created.status_code == 303
    assert created.headers["location"] == "/streams?status=created"

    with app.state.session_factory() as db:
        stream = db.scalar(select(Stream).where(Stream.name == "Radio Eins"))
        assert stream is not None
        assert stream.preferred_file_type == "mp3"
        stream_id = stream.id

    stream_page = client.get("/streams")
    assert "Radio Eins" in stream_page.text
    assert 'data-filter-input="stream-list"' in stream_page.text
    assert 'placeholder="Liste filtern"' in stream_page.text
    assert "Streams filtern" not in stream_page.text
    assert 'data-live-interval="5000"' in stream_page.text
    assert "Letzte Aufnahme" in stream_page.text
    assert "<th>Stream-URL</th>" not in stream_page.text
    assert 'class="stream-url-row"' in stream_page.text
    assert 'data-filter-text="https://radio.example/stream"' in stream_page.text
    assert 'data-filter-companion="stream-' in stream_page.text
    assert 'data-copy-stream-url="https://radio.example/stream"' in stream_page.text
    assert 'aria-label="Stream-URL kopieren"' in stream_page.text
    assert "Aufnahme jetzt starten" in stream_page.text
    assert 'class="record-dot"' in stream_page.text
    assert "Stream hinzufügen" in stream_page.text
    assert ">Ändern</a>" in stream_page.text
    assert 'class="action-initial-label">Löschen</span>' in stream_page.text
    assert "Wirklich löschen?" in stream_page.text
    assert "Verwalten" not in stream_page.text
    assert "Stream ist für Aufnahmen verfügbar" not in stream_page.text
    assert "<th>Status</th>" not in stream_page.text

    detail = client.get(f"/admin/streams/{stream_id}")
    assert 'class="panel settings-card danger-zone"' in detail.text
    assert 'class="panel settings-card settings-card-wide danger-zone"' not in detail.text
    updated = client.post(
        f"/admin/streams/{stream_id}",
        data={
            "name": "Radio Zwei",
            "stream_url": "http://radio.example:8000/live",
            "preferred_recorder": "mpv",
            "preferred_file_type": "flac",
            "csrf_token": form_token(detail.text),
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    assert updated.headers["location"] == "/streams?status=updated"
    with app.state.session_factory() as db:
        stream = db.get(Stream, stream_id)
        assert stream.name == "Radio Zwei"
        assert stream.preferred_recorder == "mpv"
        assert stream.preferred_file_type == "flac"

    assert "Radio Zwei" in client.get("/streams").text

    assert client.get(f"/admin/streams/{stream_id}/delete").status_code == 405
    confirmation = client.get("/streams")
    deleted = client.post(
        f"/admin/streams/{stream_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    with app.state.session_factory() as db:
        assert db.get(Stream, stream_id) is None
        actions = set(db.scalars(select(AuditLog.action)))
        assert {
            "stream.created",
            "stream.updated",
            "stream.deleted",
        } <= actions


def test_stream_delete_preserves_visible_history_snapshot_and_recordings(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    now = utc_now()
    with app.state.session_factory() as db:
        stream = Stream(
            name="Antenne Münster",
            stream_url="https://radio.example/antenne-muenster",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        rule = RecurringSchedule(
            stream_id=stream.id,
            title="Morgensendung",
            recorder="ffmpeg",
            file_type="mp3",
            recurrence_type="weekly",
            interval_count=1,
            weekday_mask=1,
            start_minute=480,
            duration_minutes=60,
            valid_from=date(2026, 9, 1),
            is_active=False,
            is_hidden=True,
            created_by_id=admin.id,
        )
        db.add(rule)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            stream_name="Antenne Münster",
            stream_url="https://radio.example/antenne-muenster",
            title="Morgensendung am Montag",
            recorder="ffmpeg",
            file_type="mp3",
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
            status="completed",
            recurrence_id=rule.id,
            occurrence_date=date(2026, 9, 21),
            is_hidden=False,
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.flush()
        recording = Recording(
            stream_id=stream.id,
            stream_name=stream.name,
            file_name="antenne-muenster-history.mp3",
            recorder="ffmpeg",
            file_type="mp3",
            status="completed",
            started_at=schedule.starts_at,
            ended_at=schedule.ends_at,
            schedule_id=schedule.id,
            started_by_id=admin.id,
        )
        db.add(recording)
        db.commit()
        stream_id = stream.id
        rule_id = rule.id
        schedule_id = schedule.id
        recording_id = recording.id

    assert login(client, "admin", "a-secure-admin-password").status_code == 303

    history_before = client.get("/history")
    assert "Morgensendung am Montag" in history_before.text
    assert "Antenne Münster" in history_before.text
    assert "https://radio.example/antenne-muenster" in history_before.text
    assert f'href="/schedules/{schedule_id}/copy"' in history_before.text

    confirmation = client.get("/streams")
    deleted = client.post(
        f"/admin/streams/{stream_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303

    with app.state.session_factory() as db:
        assert db.get(Stream, stream_id) is None
        retained_rule = db.get(RecurringSchedule, rule_id)
        retained_schedule = db.get(RecordingSchedule, schedule_id)
        retained_recording = db.get(Recording, recording_id)
        assert retained_rule is not None
        assert retained_rule.stream_id is None
        assert retained_schedule is not None
        assert retained_schedule.stream_id is None
        assert retained_schedule.recurrence_id == rule_id
        assert retained_schedule.is_hidden is False
        assert retained_schedule.stream_name == "Antenne Münster"
        assert retained_schedule.stream_url == "https://radio.example/antenne-muenster"
        assert retained_recording is not None
        assert retained_recording.stream_id is None
        assert retained_recording.schedule_id == schedule_id
        assert retained_recording.stream_name == "Antenne Münster"
        assert db.execute(text("PRAGMA foreign_key_check")).all() == []

    schedule_history = client.get("/history")
    assert "Morgensendung am Montag" in schedule_history.text
    assert "Antenne Münster" in schedule_history.text
    assert "https://radio.example/antenne-muenster" in schedule_history.text
    assert f'href="/schedules/{schedule_id}/copy"' not in schedule_history.text
    assert f'action="/schedules/{schedule_id}/delete"' in schedule_history.text
    assert client.get(f"/schedules/{schedule_id}/copy").status_code == 409

    recordings = client.get("/recordings")
    assert "Morgensendung am Montag" in recordings.text
    assert "Antenne Münster" in recordings.text


def test_stream_delete_is_blocked_by_active_schedule_and_recurrence(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    now = utc_now()
    with app.state.session_factory() as db:
        stream = Stream(
            name="Belegter Stream",
            stream_url="https://radio.example/belegt",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        schedule = RecordingSchedule(
            stream_id=stream.id,
            stream_name=stream.name,
            stream_url=stream.stream_url,
            title="Anstehende Aufnahme",
            starts_at=now + timedelta(hours=1),
            ends_at=now + timedelta(hours=2),
            status="scheduled",
            created_by_id=admin.id,
        )
        db.add(schedule)
        db.commit()
        stream_id = stream.id
        schedule_id = schedule.id

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    confirmation = client.get("/streams")
    blocked_by_schedule = client.post(
        f"/admin/streams/{stream_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
    )
    assert blocked_by_schedule.status_code == 400
    assert "besitzt Zeitpläne" in blocked_by_schedule.text

    with app.state.session_factory() as db:
        db.get(RecordingSchedule, schedule_id).is_hidden = True
        rule = RecurringSchedule(
            stream_id=stream_id,
            title="Aktive Wiederholung",
            recurrence_type="weekly",
            interval_count=1,
            weekday_mask=1,
            start_minute=480,
            duration_minutes=60,
            valid_from=date(2026, 9, 1),
            is_active=False,
            is_hidden=False,
            created_by_id=admin.id,
        )
        db.add(rule)
        db.commit()

    confirmation = client.get("/streams")
    blocked_by_recurrence = client.post(
        f"/admin/streams/{stream_id}/delete",
        data={
            "csrf_token": form_token(confirmation.text),
            "delete_confirmed": "true",
        },
    )
    assert blocked_by_recurrence.status_code == 400
    assert "besitzt Wiederholungen" in blocked_by_recurrence.text


def test_stream_name_is_unique_and_url_must_be_http(
    client: TestClient, admin
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    invalid = add_stream(client, stream_url="ftp://radio.example/stream")
    assert invalid.status_code == 400
    assert "http:// oder https://" in invalid.text

    assert add_stream(client).status_code == 303
    duplicate = add_stream(
        client,
        name="radio eins",
        stream_url="https://other.example/live",
    )
    assert duplicate.status_code == 400
    assert "bereits vorhanden" in duplicate.text


def test_streamripper_rejects_https_stream_url(client: TestClient, admin) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303

    rejected = add_stream(
        client,
        stream_url="https://radio.example/stream",
        preferred_recorder="streamripper",
    )
    assert rejected.status_code == 400
    assert "streamripper unterstützt keine Stream-Adresse mit https://" in rejected.text

    accepted = add_stream(
        client,
        stream_url="http://radio.example/stream",
        preferred_recorder="streamripper",
    )
    assert accepted.status_code == 303


def test_new_stream_form_starts_empty_and_offers_file_types(
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303

    page = client.get("/admin/streams/new")

    assert page.status_code == 200
    assert 'name="name" value=""' in page.text
    assert 'name="stream_url" value=""' in page.text
    assert 'name="preferred_recorder" required' in page.text
    assert 'name="preferred_file_type" required' in page.text
    assert "Dateityp auswählen" in page.text
    assert ">Stream hinzufügen</button>" in page.text


def test_stream_connection_result_is_persisted(
    app: FastAPI, client: TestClient, admin, monkeypatch
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))

    monkeypatch.setattr(
        "awas.web.streams.check_stream_url",
        lambda _: StreamCheckResult(True, "Erreichbar (HTTP 200, audio/mpeg)."),
    )
    detail = client.get(f"/admin/streams/{stream_id}")
    checked = client.post(
        f"/admin/streams/{stream_id}/test",
        data={"csrf_token": form_token(detail.text)},
        follow_redirects=False,
    )
    assert checked.status_code == 303
    assert checked.headers["location"].endswith("?status=test-ok")
    with app.state.session_factory() as db:
        stream = db.get(Stream, stream_id)
        assert stream.last_check_ok is True
        assert stream.last_checked_at is not None
        assert stream.last_check_message == "Erreichbar (HTTP 200, audio/mpeg)."
        assert db.scalar(select(AuditLog).where(AuditLog.action == "stream.tested"))


def test_normal_user_can_create_and_edit_streams_but_not_delete_them(
    app: FastAPI, client: TestClient
) -> None:
    with app.state.session_factory() as db:
        existing = Stream(
            name="Existing Stream",
            stream_url="https://radio.example/existing",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
        )
        db.add(existing)
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
        existing_id = existing.id
    assert login(client, "listener", "listener").status_code == 303
    listing = client.get("/streams")
    assert listing.status_code == 200
    assert "Stream hinzufügen" in listing.text
    assert ">Ändern</a>" in listing.text
    assert 'class="action-initial-label">Löschen</span>' not in listing.text

    created = add_stream(client, name="User Stream")
    assert created.status_code == 303
    detail = client.get(f"/admin/streams/{existing_id}")
    assert detail.status_code == 200
    assert "Stream löschen" not in detail.text
    updated = client.post(
        f"/admin/streams/{existing_id}",
        data={
            "name": "Edited by User",
            "stream_url": "https://radio.example/edited",
            "preferred_recorder": "ffmpeg",
            "preferred_file_type": "mp3",
            "csrf_token": form_token(detail.text),
        },
        follow_redirects=False,
    )
    assert updated.status_code == 303
    rejected = client.post(
        f"/admin/streams/{existing_id}/delete",
        data={
            "csrf_token": form_token(detail.text),
            "delete_confirmed": "true",
        },
    )
    assert rejected.status_code == 403
    with app.state.session_factory() as db:
        assert db.get(Stream, existing_id).name == "Edited by User"


def test_streams_are_sorted_case_insensitively_with_nonletters_first(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    names = ("zulu", "Beta", "alpha", "9 Radio", "!Sonderzeichen")
    with app.state.session_factory() as db:
        db.add_all(
            Stream(
                name=name,
                stream_url=f"https://radio.example/{index}",
                preferred_recorder="ffmpeg",
                created_by_id=admin.id,
            )
            for index, name in enumerate(names)
        )
        db.commit()

    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    expected = ("!Sonderzeichen", "9 Radio", "alpha", "Beta", "zulu")
    for path in ("/streams", "/schedules/new", "/schedules/recurring/new"):
        page = client.get(path)
        positions = [page.text.index(name) for name in expected]
        assert positions == sorted(positions)
