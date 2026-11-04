from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from awas.models import RecordingSchedule, Stream
from awas.services.auth import create_user
from awas.web import schedules as schedules_web
from tests.conftest import login


@pytest.fixture
def searchable_history(app: FastAPI, client: TestClient, admin):
    with app.state.session_factory() as db:
        owner = create_user(
            db,
            username="hidden-login",
            display_name="Köln Anzeigename",
            password="history-owner",
            password_confirmation="history-owner",
            role="user",
            must_change_password=False,
        )
        stream = Stream(
            name="Zielradio",
            stream_url="https://url-exklusiv.example/live",
            preferred_recorder="ffmpeg",
            preferred_file_type="flac",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        start = datetime(2026, 10, 24, 22, 10)
        db.add(
            RecordingSchedule(
                stream_id=stream.id,
                stream_name=stream.name,
                stream_url=stream.stream_url,
                title="Suchsendung 50%_Mix",
                file_name_base="dateiname-exklusiv",
                recorder="ffmpeg",
                file_type="flac",
                starts_at=start,
                ends_at=start + timedelta(minutes=80),
                status="failed",
                error_message="fehlertext-exklusiv",
                created_by_id=owner.id,
            )
        )
        db.add(
            RecordingSchedule(
                stream_name="Kontrollradio",
                title="Kontrollsendung",
                recorder="mpv",
                file_type="mp3",
                starts_at=start - timedelta(days=2),
                ends_at=start - timedelta(days=2) + timedelta(hours=1),
                status="completed",
                created_by_id=admin.id,
            )
        )
        db.commit()
        owner_id = owner.id
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    return owner_id


@pytest.mark.parametrize(
    ("query", "count"),
    (
        ("Suchsendung", 1),
        ("Zielradio", 1),
        ("ffmpeg", 1),
        ("flac", 1),
        ("ffmpeg Dateityp: flac", 1),
        ("Einmalig", 2),
        ("von Köln Anzeigename", 1),
        ("KÖLN", 1),
        ("25.10.2026 00:10", 1),
        ("25.10.2026 01:30", 1),
        ("50%_Mix", 1),
        ("%", 1),
        ("_", 1),
        ("50%_Other", 0),
        ("url-exklusiv", 0),
        ("fehlertext-exklusiv", 0),
        ("Fehlerhaft", 0),
        ("Abgeschlossen", 0),
        ("Kopieren", 0),
        ("Löschen", 0),
        ("hidden-login", 0),
        ("dateiname-exklusiv", 0),
        ("01:20:00", 0),
        ("2026-10-24", 0),
    ),
)
def test_history_searches_only_the_selected_displayed_columns(
    client: TestClient, searchable_history, query, count
):
    response = client.get("/history", params={"q": query})
    assert response.status_code == 200
    assert response.text.count("data-history-entry") == count


def test_history_date_search_follows_the_selected_timezone(
    app: FastAPI, client: TestClient, searchable_history
):
    app.state.timezone = "UTC"
    for value in ("24.10.2026 22:10", "24.10.2026 23:30"):
        response = client.get("/history", params={"q": value})
        assert response.status_code == 200
        assert response.text.count("data-history-entry") == 1
        assert value in response.text
    berlin_time = client.get("/history", params={"q": "25.10.2026 00:10"})
    assert berlin_time.text.count("data-history-entry") == 0


def test_history_column_filter_combines_with_the_user_filter(
    client: TestClient, admin, searchable_history
):
    own = client.get("/history", params={"q": "Einmalig", "user_id": admin.id})
    assert own.text.count("data-history-entry") == 1
    assert "Kontrollsendung" in own.text and "Suchsendung 50%_Mix" not in own.text
    other = client.get("/history", params={"q": "Einmalig", "user_id": searchable_history})
    assert other.text.count("data-history-entry") == 1
    assert "Suchsendung 50%_Mix" in other.text and "Kontrollsendung" not in other.text


def test_history_filters_both_dst_occurrences_before_pagination(
    app: FastAPI, client: TestClient, admin, monkeypatch
):
    monkeypatch.setattr(schedules_web, "HISTORY_PAGE_SIZE", 1)
    with app.state.session_factory() as db:
        for hour, title in ((0, "Vor Zeitwechsel"), (1, "Nach Zeitwechsel")):
            start = datetime(2026, 10, 25, hour, 30)
            db.add(
                RecordingSchedule(
                    title=title,
                    recorder="ffmpeg",
                    file_type="mp3",
                    starts_at=start,
                    ends_at=start + timedelta(minutes=10),
                    status="completed",
                    created_by_id=admin.id,
                )
            )
        db.commit()
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    for page, title in ((1, "Nach Zeitwechsel"), (2, "Vor Zeitwechsel")):
        response = client.get("/history", params={"q": "25.10.2026 02:30", "page": page})
        assert response.status_code == 200
        assert response.text.count("data-history-entry") == 1
        assert title in response.text
        assert f"Seite {page} von 2" in response.text
