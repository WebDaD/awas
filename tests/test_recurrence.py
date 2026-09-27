from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from awas.models import AuditLog, Recording, RecordingSchedule, RecurringSchedule, Stream
from awas.models.auth import utc_now
from awas.services.auth import create_user
from awas.services.recurrence import (
    RecurringInputError,
    calculate_duration,
    create_recurring_schedule,
    occurrence_interval,
    parse_clock,
    parse_weekday_mask,
    refresh_recurring_occurrences,
)
from tests.conftest import form_token, login
from tests.test_recordings import install_fake_ffmpeg, wait_for_status
from tests.test_streams import add_stream


def local_today(app: FastAPI) -> date:
    timezone = ZoneInfo(app.state.settings.general.timezone)
    return utc_now().replace(tzinfo=UTC).astimezone(timezone).date()


def post_recurring(
    client: TestClient,
    *,
    stream_id: int,
    title: str = "Tägliche Sendung",
    file_name_base: str | None = None,
    weekdays: list[str] | None = None,
    start_time: str = "23:00",
    end_time: str = "23:30",
    valid_from: date,
    valid_until: date | None,
):
    page = client.get("/schedules/recurring/new")
    data = {
        "title": title,
        "stream_id": str(stream_id),
        "recurrence_type": "weekly",
        "weekdays": weekdays or [str(day) for day in range(7)],
        "start_time": start_time,
        "end_time": end_time,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat() if valid_until else "",
        "csrf_token": form_token(page.text),
    }
    if file_name_base is not None:
        data["file_name_base"] = file_name_base
    return client.post(
        "/schedules/recurring",
        data=data,
        follow_redirects=False,
    )


def test_recurring_route_create_edit_pause_and_resume(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    first_day = local_today(app) + timedelta(days=1)

    created = post_recurring(
        client,
        stream_id=stream_id,
        valid_from=first_day,
        valid_until=first_day + timedelta(days=6),
    )
    assert created.status_code == 303
    assert created.headers["location"] == "/?status=recurrence-created"

    with app.state.session_factory() as db:
        rule = db.scalar(select(RecurringSchedule))
        assert rule is not None
        rule_id = rule.id
        assert rule.recorder == "ffmpeg"
        assert rule.file_type == "mp3"
        assert rule.recurrence_type == "weekly"
        assert rule.weekday_mask == 127
        assert rule.duration_minutes == 30
        assert rule.is_active is True
        assert db.scalar(select(func.count(RecordingSchedule.id))) == 7

    listing = client.get("/")
    assert "Tägliche Sendung" in listing.text
    assert "Täglich" in listing.text
    edit_page = client.get(f"/schedules/recurring/{rule_id}/edit")
    assert 'data-preferred-recorder="ffmpeg"' in edit_page.text
    changed = client.post(
        f"/schedules/recurring/{rule_id}",
        data={
            "title": "Werktagsmagazin",
            "stream_id": str(stream_id),
            "recorder": "streamlink-hls-dash",
            "file_type": "ts",
            "recurrence_type": "weekly",
            "interval_count": "1",
            "weekdays": ["0", "1", "2", "3", "4"],
            "start_time": "22:15",
            "end_time": "23:45",
            "valid_from": first_day.isoformat(),
            "valid_until": (first_day + timedelta(days=13)).isoformat(),
            "csrf_token": form_token(edit_page.text),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 303
    with app.state.session_factory() as db:
        rule = db.get(RecurringSchedule, rule_id)
        assert rule.title == "Werktagsmagazin"
        assert rule.recorder == "streamlink-hls-dash"
        assert rule.file_type == "ts"
        assert rule.interval_count == 1
        assert rule.weekday_mask == 31
        assert rule.start_minute == 22 * 60 + 15
        assert rule.duration_minutes == 90
        stream = db.get(Stream, stream_id)
        assert stream.preferred_recorder == "ffmpeg"
        assert stream.preferred_file_type == "mp3"
        generated_count = db.scalar(
            select(func.count(RecordingSchedule.id)).where(
                RecordingSchedule.recurrence_id == rule_id
            )
        )
        assert 9 <= generated_count <= 10

    listing = client.get("/")
    paused = client.post(
        f"/schedules/recurring/{rule_id}/status",
        data={"enabled": "false", "csrf_token": form_token(listing.text)},
        follow_redirects=False,
    )
    assert paused.status_code == 303
    with app.state.session_factory() as db:
        assert db.get(RecurringSchedule, rule_id).is_active is False
        assert db.scalar(
            select(func.count(RecordingSchedule.id)).where(
                RecordingSchedule.recurrence_id == rule_id
            )
        ) == 0

    listing = client.get("/")
    enabled = client.post(
        f"/schedules/recurring/{rule_id}/status",
        data={"enabled": "true", "csrf_token": form_token(listing.text)},
        follow_redirects=False,
    )
    assert enabled.status_code == 303
    with app.state.session_factory() as db:
        assert db.get(RecurringSchedule, rule_id).is_active is True
        assert db.scalar(
            select(func.count(RecordingSchedule.id)).where(
                RecordingSchedule.recurrence_id == rule_id
            )
        ) > 0
        actions = set(db.scalars(select(AuditLog.action)))
        assert {
            "recurrence.created",
            "recurrence.updated",
            "recurrence.disabled",
            "recurrence.enabled",
        } <= actions

    listing = client.get("/")
    deleted = client.post(
        f"/schedules/recurring/{rule_id}/delete",
        data={
            "csrf_token": form_token(listing.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert deleted.status_code == 303
    with app.state.session_factory() as db:
        rule = db.get(RecurringSchedule, rule_id)
        assert rule.is_hidden is True
        assert rule.is_active is False
        assert db.scalar(
            select(func.count(RecordingSchedule.id)).where(
                RecordingSchedule.recurrence_id == rule_id,
                RecordingSchedule.status == "scheduled",
            )
        ) == 0
        assert db.scalar(
            select(AuditLog).where(AuditLog.action == "recurrence.entry_deleted")
        )
    assert "Werktagsmagazin" not in client.get("/").text


def test_recurring_form_requires_a_weekday(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    first_day = local_today(app) + timedelta(days=1)
    page = client.get("/schedules/recurring/new")
    response = client.post(
        "/schedules/recurring",
        data={
            "title": "Ungültig",
            "stream_id": str(stream_id),
            "start_time": "10:00",
            "end_time": "11:00",
            "valid_from": first_day.isoformat(),
            "valid_until": "",
            "csrf_token": form_token(page.text),
        },
    )
    assert response.status_code == 400
    assert "Mindestens ein Wochentag" in response.text


def test_recurring_occurrences_are_only_listed_while_running(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    first_day = local_today(app) + timedelta(days=1)
    assert post_recurring(
        client,
        stream_id=stream_id,
        title="Nur als Wiederholung",
        valid_from=first_day,
        valid_until=first_day,
    ).status_code == 303

    planning = client.get("/").text
    upcoming = planning.split('data-live-region="upcoming-schedules"', 1)[1].split(
        'data-live-region="recurring-schedules"', 1
    )[0]
    recurring = planning.split('data-live-region="recurring-schedules"', 1)[1]
    assert "Nur als Wiederholung" not in upcoming
    assert "Nur als Wiederholung" in recurring

    with app.state.session_factory() as db:
        occurrence = db.scalar(
            select(RecordingSchedule).where(RecordingSchedule.recurrence_id.is_not(None))
        )
        occurrence.status = "running"
        db.commit()

    planning = client.get("/").text
    running = planning.split('data-live-region="running-schedules"', 1)[1].split(
        'data-live-region="upcoming-schedules"', 1
    )[0]
    assert "Nur als Wiederholung" in running


def test_recurring_schedule_copies_custom_file_name_to_occurrences(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    first_day = local_today(app) + timedelta(days=1)

    page = client.get("/schedules/recurring/new")
    assert 'name="file_name_base" value=""' in page.text
    assert "data-file-name-base" in page.text
    response = post_recurring(
        client,
        stream_id=stream_id,
        file_name_base="Monats-Rückblick 2026",
        valid_from=first_day,
        valid_until=first_day + timedelta(days=1),
    )

    assert response.status_code == 303
    with app.state.session_factory() as db:
        rule = db.scalar(select(RecurringSchedule))
        assert rule.file_name_base == "monats-ruckblick-2026"
        occurrences = list(
            db.scalars(
                select(RecordingSchedule).where(
                    RecordingSchedule.recurrence_id == rule.id
                )
            )
        )
        assert occurrences
        assert {item.file_name_base for item in occurrences} == {
            "monats-ruckblick-2026"
        }


def test_normal_user_can_create_but_not_edit_another_recurrence(
    app: FastAPI,
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303
    with app.state.session_factory() as db:
        stream_id = db.scalar(select(Stream.id))
    first_day = local_today(app) + timedelta(days=1)
    assert post_recurring(
        client,
        stream_id=stream_id,
        valid_from=first_day,
        valid_until=first_day,
    ).status_code == 303
    with app.state.session_factory() as db:
        admin_rule_id = db.scalar(select(RecurringSchedule.id))
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
    assert client.get(f"/schedules/recurring/{admin_rule_id}/edit").status_code == 403
    own_day = first_day + timedelta(days=7)
    own = post_recurring(
        client,
        stream_id=stream_id,
        title="Eigene Wiederholung",
        valid_from=own_day,
        valid_until=own_day,
    )
    assert own.status_code == 303
    with app.state.session_factory() as db:
        assert db.scalar(select(func.count(RecurringSchedule.id))) == 2
        own_rule_id = db.scalar(
            select(RecurringSchedule.id).where(
                RecurringSchedule.title == "Eigene Wiederholung"
            )
        )
    assert client.get(f"/schedules/recurring/{own_rule_id}/edit").status_code == 200
    planning = client.get("/")
    hidden = client.post(
        f"/schedules/recurring/{own_rule_id}/delete",
        data={
            "csrf_token": form_token(planning.text),
            "delete_confirmed": "true",
        },
        follow_redirects=False,
    )
    assert hidden.status_code == 303
    with app.state.session_factory() as db:
        assert db.get(RecurringSchedule, own_rule_id).is_hidden is True


def test_recurring_occurrence_runs_through_scheduler(
    app: FastAPI,
    admin,
    tmp_path,
    monkeypatch,
) -> None:
    install_fake_ffmpeg(tmp_path, monkeypatch)
    now = utc_now().replace(microsecond=0)
    timezone = app.state.settings.general.timezone
    local_now = now.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone))
    with app.state.session_factory() as db:
        stream = Stream(
            name="Series Stream",
            stream_url="https://radio.example/series",
            preferred_recorder="ffmpeg",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        rule = create_recurring_schedule(
            db,
            stream=stream,
            title="Serientest",
            weekday_mask=1 << local_now.weekday(),
            start_minute=local_now.hour * 60 + local_now.minute,
            duration_minutes=2,
            valid_from=local_now.date(),
            valid_until=local_now.date(),
            timezone=timezone,
            actor=admin,
            ip_address="127.0.0.1",
            now=now,
        )
        rule_id = rule.id
        schedule = db.scalar(
            select(RecordingSchedule).where(RecordingSchedule.recurrence_id == rule_id)
        )
        assert schedule is not None
        schedule_id = schedule.id

    app.state.recording_scheduler.run_due(now)
    with app.state.session_factory() as db:
        schedule = db.get(RecordingSchedule, schedule_id)
        recording = db.scalar(select(Recording).where(Recording.schedule_id == schedule_id))
        assert schedule.status == "running"
        assert recording is not None
        recording_id = recording.id
        stop_time = schedule.ends_at

    app.state.recording_scheduler.run_due(stop_time)
    wait_for_status(app, recording_id, "completed")
    app.state.recording_scheduler.run_due(stop_time)
    with app.state.session_factory() as db:
        assert db.get(RecordingSchedule, schedule_id).status == "completed"


def test_recurring_horizon_is_replenished(app: FastAPI, admin) -> None:
    now = utc_now().replace(microsecond=0)
    timezone = app.state.settings.general.timezone
    local_now = now.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone))
    with app.state.session_factory() as db:
        stream = Stream(
            name="Horizon Stream",
            stream_url="https://radio.example/horizon",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        rule = RecurringSchedule(
            stream_id=stream.id,
            title="Horizon",
            weekday_mask=127,
            start_minute=23 * 60,
            duration_minutes=30,
            valid_from=local_now.date(),
            is_active=True,
            created_by_id=admin.id,
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id

    with app.state.session_factory() as db:
        assert refresh_recurring_occurrences(db, timezone=timezone, now=now) == 35
        first_max = db.scalar(
            select(func.max(RecordingSchedule.occurrence_date)).where(
                RecordingSchedule.recurrence_id == rule_id
            )
        )

    later = now + timedelta(days=10)
    with app.state.session_factory() as db:
        assert refresh_recurring_occurrences(db, timezone=timezone, now=later) == 10
        second_max = db.scalar(
            select(func.max(RecordingSchedule.occurrence_date)).where(
                RecordingSchedule.recurrence_id == rule_id
            )
        )
    assert second_max == first_max + timedelta(days=10)


def test_expired_recurring_rule_is_closed(app: FastAPI, admin) -> None:
    now = utc_now().replace(microsecond=0)
    timezone = app.state.settings.general.timezone
    today = now.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone)).date()
    with app.state.session_factory() as db:
        stream = Stream(
            name="Expired Stream",
            stream_url="https://radio.example/expired",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        rule = RecurringSchedule(
            stream_id=stream.id,
            title="Abgelaufen",
            weekday_mask=127,
            start_minute=12 * 60,
            duration_minutes=60,
            valid_from=today - timedelta(days=10),
            valid_until=today - timedelta(days=1),
            is_active=True,
            created_by_id=admin.id,
        )
        db.add(rule)
        db.commit()
        rule_id = rule.id

    with app.state.session_factory() as db:
        assert refresh_recurring_occurrences(db, timezone=timezone, now=now) == 0
        assert db.get(RecurringSchedule, rule_id).is_active is False
        assert db.scalar(select(AuditLog).where(AuditLog.action == "recurrence.expired"))


def test_monthly_first_monday_and_fixed_day_are_generated(app: FastAPI, admin) -> None:
    timezone = app.state.settings.general.timezone
    now = datetime(2026, 10, 1, 0, 0)
    with app.state.session_factory() as db:
        stream = Stream(
            name="Monthly Stream",
            stream_url="https://radio.example/monthly",
            preferred_recorder="ffmpeg",
            preferred_file_type="mp3",
            created_by_id=admin.id,
        )
        db.add(stream)
        db.flush()
        weekday_rule = create_recurring_schedule(
            db,
            stream=stream,
            title="Erster Montag",
            recorder="ffmpeg",
            file_type="mp3",
            recurrence_type="monthly_weekday",
            weekday_mask=1 << 0,
            month_week=1,
            start_minute=12 * 60,
            duration_minutes=60,
            valid_from=date(2026, 10, 1),
            valid_until=date(2026, 12, 31),
            timezone=timezone,
            actor=admin,
            ip_address="127.0.0.1",
            now=now,
        )
        fixed_rule = create_recurring_schedule(
            db,
            stream=stream,
            title="Monatsende",
            recorder="ffmpeg",
            file_type="flac",
            recurrence_type="monthly_day",
            weekday_mask=127,
            month_day=31,
            start_minute=16 * 60,
            duration_minutes=30,
            valid_from=date(2026, 10, 1),
            valid_until=date(2026, 12, 31),
            timezone=timezone,
            actor=admin,
            ip_address="127.0.0.1",
            now=now,
        )
        weekday_dates = list(
            db.scalars(
                select(RecordingSchedule.occurrence_date)
                .where(RecordingSchedule.recurrence_id == weekday_rule.id)
                .order_by(RecordingSchedule.occurrence_date)
            )
        )
        fixed_dates = list(
            db.scalars(
                select(RecordingSchedule.occurrence_date)
                .where(RecordingSchedule.recurrence_id == fixed_rule.id)
                .order_by(RecordingSchedule.occurrence_date)
            )
        )

        assert weekday_rule.recurrence_label == "Monatlich: erster Montag"
        assert weekday_dates == [date(2026, 10, 5), date(2026, 11, 2)]
        assert fixed_rule.recurrence_label == "Monatlich am 31."
        assert fixed_dates == [date(2026, 10, 31)]


def test_hourly_daily_and_biweekly_intervals_are_generated(
    app: FastAPI,
    admin,
) -> None:
    now = datetime(2026, 10, 1, 0, 0)
    with app.state.session_factory() as db:
        streams = []
        for name in ("Hourly Stream", "Daily Stream", "Weekly Stream"):
            stream = Stream(
                name=name,
                stream_url=f"https://radio.example/{name.lower().replace(' ', '-')}",
                preferred_recorder="ffmpeg",
                preferred_file_type="mp3",
                created_by_id=admin.id,
            )
            db.add(stream)
            streams.append(stream)
        db.flush()

        hourly = create_recurring_schedule(
            db,
            stream=streams[0],
            title="Alle drei Stunden",
            recurrence_type="hourly",
            interval_count=3,
            weekday_mask=127,
            start_minute=8 * 60,
            duration_minutes=30,
            valid_from=date(2026, 10, 1),
            valid_until=date(2026, 10, 1),
            timezone="UTC",
            actor=admin,
            ip_address="127.0.0.1",
            now=now,
        )
        daily = create_recurring_schedule(
            db,
            stream=streams[1],
            title="Jeden zweiten Tag",
            recurrence_type="daily",
            interval_count=2,
            weekday_mask=127,
            start_minute=9 * 60,
            duration_minutes=30,
            valid_from=date(2026, 10, 1),
            valid_until=date(2026, 10, 10),
            timezone="UTC",
            actor=admin,
            ip_address="127.0.0.1",
            now=now,
        )
        biweekly = create_recurring_schedule(
            db,
            stream=streams[2],
            title="Alle zwei Wochen montags",
            recurrence_type="weekly",
            interval_count=2,
            weekday_mask=1,
            start_minute=10 * 60,
            duration_minutes=30,
            valid_from=date(2026, 10, 1),
            valid_until=date(2026, 11, 4),
            timezone="UTC",
            actor=admin,
            ip_address="127.0.0.1",
            now=now,
        )

        hourly_starts = list(
            db.scalars(
                select(RecordingSchedule.starts_at)
                .where(RecordingSchedule.recurrence_id == hourly.id)
                .order_by(RecordingSchedule.starts_at)
            )
        )
        daily_dates = list(
            db.scalars(
                select(RecordingSchedule.occurrence_date)
                .where(RecordingSchedule.recurrence_id == daily.id)
                .order_by(RecordingSchedule.occurrence_date)
            )
        )
        biweekly_dates = list(
            db.scalars(
                select(RecordingSchedule.occurrence_date)
                .where(RecordingSchedule.recurrence_id == biweekly.id)
                .order_by(RecordingSchedule.occurrence_date)
            )
        )

        assert [value.hour for value in hourly_starts] == [8, 11, 14, 17, 20, 23]
        assert daily_dates == [
            date(2026, 10, 1),
            date(2026, 10, 3),
            date(2026, 10, 5),
            date(2026, 10, 7),
            date(2026, 10, 9),
        ]
        assert biweekly_dates == [
            date(2026, 10, 5),
            date(2026, 10, 19),
            date(2026, 11, 2),
        ]
        assert hourly.recurrence_label == "Alle 3 Stunden"
        assert daily.recurrence_label == "Alle 2 Tage"
        assert "alle 2 Wochen" in biweekly.recurrence_label


def test_new_recurring_form_starts_empty_and_offers_monthly_patterns(
    client: TestClient,
    admin,
) -> None:
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    assert add_stream(client).status_code == 303

    page = client.get("/schedules/recurring/new")

    assert page.status_code == 200
    assert 'name="start_time" value=""' in page.text
    assert 'name="end_time" value=""' in page.text
    assert 'name="valid_from" value=""' in page.text
    assert 'name="interval_count" value=""' in page.text
    assert 'name="weekdays"' in page.text
    assert 'name="weekdays" value="0" checked' not in page.text
    assert "Monatlich nach Wochentag" in page.text
    assert "Stündlich" in page.text
    assert "Täglich" in page.text
    assert "Erster" in page.text
    assert "Wiederholung anlegen" not in page.text
    assert ">Speichern</button>" in page.text


def test_recurring_dst_policy_and_time_parsers() -> None:
    assert parse_weekday_mask(["0", "2", "6"]) == 69
    with pytest.raises(RecurringInputError, match="Mindestens"):
        parse_weekday_mask([])
    assert parse_clock("23:30", "Start") == 23 * 60 + 30
    assert calculate_duration(23 * 60, 60) == 120
    assert calculate_duration(0, 0) == 1440

    spring_rule = RecurringSchedule(
        stream_id=1,
        title="DST",
        weekday_mask=127,
        start_minute=2 * 60 + 30,
        duration_minutes=60,
        valid_from=date(2026, 1, 1),
    )
    spring_start, _ = occurrence_interval(
        spring_rule,
        date(2026, 3, 29),
        "Europe/Berlin",
    )
    autumn_start, _ = occurrence_interval(
        spring_rule,
        date(2026, 10, 25),
        "Europe/Berlin",
    )
    assert spring_start == datetime(2026, 3, 29, 1, 30)
    assert autumn_start == datetime(2026, 10, 25, 0, 30)
