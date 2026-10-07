from __future__ import annotations

from calendar import monthrange
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from awas.models import (
    RecordingSchedule,
    RecurringSchedule,
    Stream,
    User,
)
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.filenames import FileNameInputError, normalize_file_name_base
from awas.services.recorders import (
    RecorderInputError,
    validate_file_type,
    validate_recorder,
    validate_recorder_url,
)

GENERATION_HORIZON_DAYS = 35
HOURLY_GENERATION_HORIZON_DAYS = 2
RECURRENCE_TYPES = frozenset(
    ("hourly", "daily", "weekly", "monthly_day", "monthly_weekday")
)


class RecurringInputError(ValueError):
    pass


def parse_weekday_mask(values: list[str]) -> int:
    try:
        weekdays = {int(value) for value in values}
    except ValueError as exc:
        raise RecurringInputError("Die ausgewählten Wochentage sind ungültig.") from exc
    if not weekdays or any(day < 0 or day > 6 for day in weekdays):
        raise RecurringInputError("Mindestens ein Wochentag muss ausgewählt werden.")
    return sum(1 << day for day in weekdays)


def parse_clock(value: str, field_name: str) -> int:
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as exc:
        raise RecurringInputError(f"{field_name} ist keine gültige Uhrzeit.") from exc
    if parsed.second or parsed.microsecond or parsed.tzinfo is not None:
        raise RecurringInputError(f"{field_name} muss minutengenau angegeben werden.")
    return parsed.hour * 60 + parsed.minute


def parse_date(value: str, field_name: str, *, optional: bool = False) -> date | None:
    normalized = value.strip()
    if optional and not normalized:
        return None
    try:
        return date.fromisoformat(normalized)
    except ValueError as exc:
        raise RecurringInputError(f"{field_name} ist kein gültiges Datum.") from exc


def calculate_duration(start_minute: int, end_minute: int) -> int:
    duration = (end_minute - start_minute) % 1440
    return duration or 1440


def create_recurring_schedule(
    db: Session,
    *,
    stream: Stream,
    title: str,
    file_name_base: str | None = None,
    recorder: str | None = None,
    file_type: str | None = None,
    recurrence_type: str = "weekly",
    interval_count: int = 1,
    weekday_mask: int,
    month_day: int | None = None,
    month_week: int | None = None,
    start_minute: int,
    duration_minutes: int,
    valid_from: date,
    valid_until: date | None,
    timezone: str,
    actor: User,
    ip_address: str,
    now: datetime | None = None,
) -> RecurringSchedule:
    current_time = now or utc_now()
    normalized_title = _validate_rule(
        title=title,
        recurrence_type=recurrence_type,
        interval_count=interval_count,
        weekday_mask=weekday_mask,
        month_day=month_day,
        month_week=month_week,
        start_minute=start_minute,
        duration_minutes=duration_minutes,
        valid_from=valid_from,
        valid_until=valid_until,
        timezone=timezone,
        now=current_time,
    )
    try:
        normalized_recorder = validate_recorder(recorder or stream.preferred_recorder)
        normalized_file_type = validate_file_type(file_type or stream.preferred_file_type)
        validate_recorder_url(normalized_recorder, stream.stream_url)
        normalized_file_name = normalize_file_name_base(file_name_base or normalized_title)
    except (FileNameInputError, RecorderInputError) as exc:
        raise RecurringInputError(str(exc)) from exc
    rule = RecurringSchedule(
        stream_id=stream.id,
        title=normalized_title,
        file_name_base=normalized_file_name,
        recorder=normalized_recorder,
        file_type=normalized_file_type,
        recurrence_type=recurrence_type,
        interval_count=interval_count,
        weekday_mask=weekday_mask,
        month_day=month_day,
        month_week=month_week,
        start_minute=start_minute,
        duration_minutes=duration_minutes,
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=True,
        created_by_id=actor.id,
    )
    db.add(rule)
    db.flush()
    generated = generate_rule_occurrences(db, rule, timezone=timezone, now=current_time)
    add_audit_entry(
        db,
        "recurrence.created",
        actor=actor,
        target_type="recurring_schedule",
        target_id=rule.id,
        ip_address=ip_address,
        details={
            "stream_id": stream.id,
            "generated": generated,
            "recorder": normalized_recorder,
            "file_type": normalized_file_type,
            "file_name_base": normalized_file_name,
            "recurrence_type": recurrence_type,
            "interval_count": interval_count,
        },
    )
    db.commit()
    return rule


def update_recurring_schedule(
    db: Session,
    rule: RecurringSchedule,
    *,
    stream: Stream,
    title: str,
    file_name_base: str | None = None,
    recorder: str | None = None,
    file_type: str | None = None,
    recurrence_type: str = "weekly",
    interval_count: int = 1,
    weekday_mask: int,
    month_day: int | None = None,
    month_week: int | None = None,
    start_minute: int,
    duration_minutes: int,
    valid_from: date,
    valid_until: date | None,
    timezone: str,
    actor: User,
    ip_address: str,
    now: datetime | None = None,
) -> RecurringSchedule:
    current_time = now or utc_now()
    normalized_title = _validate_rule(
        title=title,
        recurrence_type=recurrence_type,
        interval_count=interval_count,
        weekday_mask=weekday_mask,
        month_day=month_day,
        month_week=month_week,
        start_minute=start_minute,
        duration_minutes=duration_minutes,
        valid_from=valid_from,
        valid_until=valid_until,
        timezone=timezone,
        now=current_time,
    )
    try:
        normalized_recorder = validate_recorder(recorder or stream.preferred_recorder)
        normalized_file_type = validate_file_type(file_type or stream.preferred_file_type)
        validate_recorder_url(normalized_recorder, stream.stream_url)
        normalized_file_name = normalize_file_name_base(file_name_base or normalized_title)
    except (FileNameInputError, RecorderInputError) as exc:
        raise RecurringInputError(str(exc)) from exc
    _delete_pending_occurrences(db, rule.id, current_time)
    rule.stream_id = stream.id
    rule.title = normalized_title
    rule.file_name_base = normalized_file_name
    rule.recorder = normalized_recorder
    rule.file_type = normalized_file_type
    rule.recurrence_type = recurrence_type
    rule.interval_count = interval_count
    rule.weekday_mask = weekday_mask
    rule.month_day = month_day
    rule.month_week = month_week
    rule.start_minute = start_minute
    rule.duration_minutes = duration_minutes
    rule.valid_from = valid_from
    rule.valid_until = valid_until
    rule.updated_at = current_time
    db.flush()
    generated = (
        generate_rule_occurrences(db, rule, timezone=timezone, now=current_time)
        if rule.is_active
        else 0
    )
    add_audit_entry(
        db,
        "recurrence.updated",
        actor=actor,
        target_type="recurring_schedule",
        target_id=rule.id,
        ip_address=ip_address,
        details={
            "stream_id": stream.id,
            "generated": generated,
            "recorder": normalized_recorder,
            "file_type": normalized_file_type,
            "file_name_base": normalized_file_name,
            "recurrence_type": recurrence_type,
            "interval_count": interval_count,
        },
    )
    db.commit()
    return rule


def set_recurring_schedule_active(
    db: Session,
    rule: RecurringSchedule,
    *,
    enabled: bool,
    timezone: str,
    actor: User,
    ip_address: str,
    now: datetime | None = None,
) -> None:
    current_time = now or utc_now()
    if (
        enabled
        and rule.valid_until is not None
        and rule.valid_until < _local_date(current_time, timezone)
    ):
        raise RecurringInputError(
            "Der Gültigkeitszeitraum ist abgelaufen. Bitte zuerst das Enddatum ändern."
        )
    _delete_pending_occurrences(db, rule.id, current_time)
    rule.is_active = enabled
    rule.updated_at = current_time
    db.flush()
    generated = (
        generate_rule_occurrences(db, rule, timezone=timezone, now=current_time)
        if enabled
        else 0
    )
    add_audit_entry(
        db,
        "recurrence.enabled" if enabled else "recurrence.disabled",
        actor=actor,
        target_type="recurring_schedule",
        target_id=rule.id,
        ip_address=ip_address,
        details={"stream_id": rule.stream_id, "generated": generated},
    )
    db.commit()


def hide_recurring_schedule(
    db: Session,
    rule: RecurringSchedule,
    *,
    actor: User,
    ip_address: str,
    now: datetime | None = None,
) -> None:
    current_time = now or utc_now()
    running = db.scalar(
        select(RecordingSchedule.id)
        .where(
            RecordingSchedule.recurrence_id == rule.id,
            RecordingSchedule.status == "running",
        )
        .limit(1)
    )
    if running is not None:
        raise RecurringInputError(
            "Die Wiederholung kann während einer laufenden Aufnahme nicht gelöscht werden."
        )
    _delete_pending_occurrences(db, rule.id, current_time)
    rule.is_active = False
    rule.is_hidden = True
    rule.updated_at = current_time
    add_audit_entry(
        db,
        "recurrence.entry_deleted",
        actor=actor,
        target_type="recurring_schedule",
        target_id=rule.id,
        ip_address=ip_address,
        details={"stream_id": rule.stream_id},
    )
    db.commit()


def refresh_recurring_occurrences(
    db: Session,
    *,
    timezone: str,
    now: datetime | None = None,
) -> int:
    current_time = now or utc_now()
    local_today = _local_date(current_time, timezone)
    horizon_end = local_today + timedelta(days=GENERATION_HORIZON_DAYS - 1)
    expired_rules = list(
        db.scalars(
            select(RecurringSchedule).where(
                RecurringSchedule.is_active.is_(True),
                RecurringSchedule.is_hidden.is_(False),
                RecurringSchedule.valid_until.is_not(None),
                RecurringSchedule.valid_until < local_today,
            )
        )
    )
    for rule in expired_rules:
        rule.is_active = False
        rule.updated_at = current_time
        add_audit_entry(
            db,
            "recurrence.expired",
            target_type="recurring_schedule",
            target_id=rule.id,
            details={"stream_id": rule.stream_id},
        )
    if expired_rules:
        db.flush()
    rules = list(
        db.scalars(
            select(RecurringSchedule).where(
                RecurringSchedule.is_active.is_(True),
                RecurringSchedule.is_hidden.is_(False),
                RecurringSchedule.valid_from <= horizon_end,
                (RecurringSchedule.valid_until.is_(None))
                | (RecurringSchedule.valid_until >= local_today),
            )
        )
    )
    generated = sum(
        generate_rule_occurrences(db, rule, timezone=timezone, now=current_time)
        for rule in rules
    )
    if generated or expired_rules:
        db.commit()
    return generated


def rebuild_pending_recurring_occurrences(
    db: Session,
    *,
    timezone: str,
    now: datetime | None = None,
) -> int:
    """Rebuild future occurrences after the application timezone changes."""
    current_time = now or utc_now()
    rules = list(
        db.scalars(
            select(RecurringSchedule).where(
                RecurringSchedule.is_hidden.is_(False),
            )
        )
    )
    for rule in rules:
        _delete_pending_occurrences(db, rule.id, current_time)
    db.flush()
    generated = refresh_recurring_occurrences(
        db,
        timezone=timezone,
        now=current_time,
    )
    db.commit()
    return generated


def generate_rule_occurrences(
    db: Session,
    rule: RecurringSchedule,
    *,
    timezone: str,
    now: datetime,
) -> int:
    if not rule.is_active:
        return 0
    local_today = _local_date(now, timezone)
    first_date = max(local_today, rule.valid_from)
    horizon_days = (
        HOURLY_GENERATION_HORIZON_DAYS
        if rule.recurrence_type == "hourly"
        else GENERATION_HORIZON_DAYS
    )
    last_date = local_today + timedelta(days=horizon_days - 1)
    if rule.valid_until is not None:
        last_date = min(last_date, rule.valid_until)
    if last_date < first_date:
        return 0

    existing_starts = set(
        db.scalars(
            select(RecordingSchedule.starts_at).where(
                RecordingSchedule.recurrence_id == rule.id,
            )
        )
    )
    stream = db.get(Stream, rule.stream_id) if rule.stream_id is not None else None
    generated = 0
    zone = ZoneInfo(timezone)
    for local_start in _iter_local_starts(rule, first_date, last_date):
        starts_at = _lenient_local_to_utc(local_start, zone)
        ends_at = starts_at + timedelta(minutes=rule.duration_minutes)
        if starts_at not in existing_starts and ends_at > now:
            schedule = RecordingSchedule(
                stream_id=rule.stream_id,
                stream_name=stream.name if stream is not None else "Gelöschter Stream",
                stream_url=stream.stream_url if stream is not None else "",
                title=rule.title,
                file_name_base=rule.file_name_base,
                recorder=rule.recorder,
                file_type=rule.file_type,
                starts_at=starts_at,
                ends_at=ends_at,
                status="scheduled",
                created_by_id=rule.created_by_id,
                recurrence_id=rule.id,
                occurrence_date=local_start.date(),
            )
            db.add(schedule)
            db.flush()
            existing_starts.add(starts_at)
            generated += 1
    if generated:
        add_audit_entry(
            db,
            "recurrence.generated",
            target_type="recurring_schedule",
            target_id=rule.id,
            details={"stream_id": rule.stream_id, "count": generated},
        )
    return generated


def occurrence_interval(
    rule: RecurringSchedule,
    occurrence_date: date,
    timezone: str,
) -> tuple[datetime, datetime]:
    local_start = datetime.combine(
        occurrence_date,
        time(rule.start_minute // 60, rule.start_minute % 60),
    )
    starts_at = _lenient_local_to_utc(local_start, ZoneInfo(timezone))
    return starts_at, starts_at + timedelta(minutes=rule.duration_minutes)


def _date_matches_rule(rule: RecurringSchedule, candidate: date) -> bool:
    interval = rule.interval_count or 1
    days_since_anchor = (candidate - rule.valid_from).days
    if rule.recurrence_type == "daily":
        return days_since_anchor >= 0 and days_since_anchor % interval == 0
    if rule.recurrence_type == "weekly":
        first_weekday = min(
            (weekday - rule.valid_from.weekday()) % 7 for weekday in rule.weekdays
        )
        first_occurrence = rule.valid_from + timedelta(days=first_weekday)
        anchor_week = first_occurrence - timedelta(days=first_occurrence.weekday())
        candidate_week = candidate - timedelta(days=candidate.weekday())
        weeks_since_anchor = (candidate_week - anchor_week).days // 7
        return (
            weeks_since_anchor >= 0
            and weeks_since_anchor % interval == 0
            and bool(rule.weekday_mask & (1 << candidate.weekday()))
        )
    monthly_anchor = _first_monthly_occurrence(rule)
    month_offset = (candidate.year - monthly_anchor.year) * 12 + (
        candidate.month - monthly_anchor.month
    )
    if month_offset < 0 or month_offset % interval:
        return False
    return candidate == _monthly_occurrence(rule, candidate.year, candidate.month)


def _first_monthly_occurrence(rule: RecurringSchedule) -> date:
    year = rule.valid_from.year
    month = rule.valid_from.month
    for _ in range(24):
        occurrence = _monthly_occurrence(rule, year, month)
        if occurrence is not None and occurrence >= rule.valid_from:
            return occurrence
        month += 1
        if month == 13:
            year += 1
            month = 1
    raise RecurringInputError("Für die Monatsregel konnte kein Termin ermittelt werden.")


def _monthly_occurrence(
    rule: RecurringSchedule,
    year: int,
    month: int,
) -> date | None:
    days_in_month = monthrange(year, month)[1]
    if rule.recurrence_type == "monthly_day":
        if rule.month_day is None or rule.month_day > days_in_month:
            return None
        return date(year, month, rule.month_day)
    if rule.recurrence_type != "monthly_weekday" or not rule.weekdays:
        return None
    weekday = rule.weekdays[0]
    if rule.month_week == -1:
        last_day = date(year, month, days_in_month)
        day = days_in_month - (last_day.weekday() - weekday) % 7
        return date(year, month, day)
    first_day = date(year, month, 1)
    day = 1 + (weekday - first_day.weekday()) % 7 + 7 * ((rule.month_week or 1) - 1)
    if day > days_in_month:
        return None
    return date(year, month, day)


def _iter_local_starts(
    rule: RecurringSchedule,
    first_date: date,
    last_date: date,
):
    start_clock = time(rule.start_minute // 60, rule.start_minute % 60)
    if rule.recurrence_type == "hourly":
        interval_seconds = (rule.interval_count or 1) * 3600
        anchor = datetime.combine(rule.valid_from, start_clock)
        lower_bound = datetime.combine(first_date, time.min)
        upper_bound = datetime.combine(last_date, time.max)
        steps = 0
        if anchor < lower_bound:
            delta_seconds = int((lower_bound - anchor).total_seconds())
            steps = (delta_seconds + interval_seconds - 1) // interval_seconds
        candidate = anchor + timedelta(seconds=steps * interval_seconds)
        while candidate <= upper_bound:
            yield candidate
            candidate += timedelta(seconds=interval_seconds)
        return

    candidate_date = first_date
    while candidate_date <= last_date:
        if _date_matches_rule(rule, candidate_date):
            yield datetime.combine(candidate_date, start_clock)
        candidate_date += timedelta(days=1)


def _validate_rule(
    *,
    title: str,
    recurrence_type: str,
    interval_count: int,
    weekday_mask: int,
    month_day: int | None,
    month_week: int | None,
    start_minute: int,
    duration_minutes: int,
    valid_from: date,
    valid_until: date | None,
    timezone: str,
    now: datetime,
) -> str:
    normalized_title = " ".join(title.strip().split())
    if not 1 <= len(normalized_title) <= 128:
        raise RecurringInputError("Die Bezeichnung muss 1 bis 128 Zeichen lang sein.")
    if recurrence_type not in RECURRENCE_TYPES:
        raise RecurringInputError("Die ausgewählte Wiederholung ist ungültig.")
    if not 1 <= interval_count <= 999:
        raise RecurringInputError("Das Wiederholungsintervall muss zwischen 1 und 999 liegen.")
    if not 1 <= weekday_mask <= 127:
        message = (
            "Ein Wochentag muss ausgewählt werden."
            if recurrence_type == "monthly_weekday"
            else "Mindestens ein Wochentag muss ausgewählt werden."
        )
        raise RecurringInputError(message)
    if recurrence_type == "monthly_day" and month_day not in range(1, 32):
        raise RecurringInputError("Der Monatstag muss zwischen 1 und 31 liegen.")
    if recurrence_type == "monthly_weekday":
        if weekday_mask & (weekday_mask - 1):
            raise RecurringInputError("Für die Monatsregel muss ein Wochentag gewählt werden.")
        if month_week not in {-1, 1, 2, 3, 4, 5}:
            raise RecurringInputError("Die Position des Wochentags im Monat ist ungültig.")
    if not 0 <= start_minute <= 1439 or not 1 <= duration_minutes <= 1440:
        raise RecurringInputError("Start, Ende oder Dauer sind ungültig.")
    if valid_until is not None and valid_until < valid_from:
        raise RecurringInputError("Das Enddatum darf nicht vor dem Startdatum liegen.")
    if valid_until is not None and valid_until < _local_date(now, timezone):
        raise RecurringInputError("Das Enddatum darf nicht in der Vergangenheit liegen.")
    return normalized_title


def _delete_pending_occurrences(db: Session, rule_id: int, now: datetime) -> None:
    db.execute(
        delete(RecordingSchedule).where(
            RecordingSchedule.recurrence_id == rule_id,
            RecordingSchedule.ends_at > now,
            RecordingSchedule.status.in_(("scheduled", "cancelled", "missed", "failed")),
        )
    )


def _local_date(value: datetime, timezone: str) -> date:
    return value.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone)).date()


def _lenient_local_to_utc(value: datetime, timezone: ZoneInfo) -> datetime:
    first = value.replace(tzinfo=timezone, fold=0)
    second = value.replace(tzinfo=timezone, fold=1)
    first_roundtrip = first.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
    second_roundtrip = second.astimezone(UTC).astimezone(timezone).replace(tzinfo=None)
    if first_roundtrip == value:
        selected = first
    elif second_roundtrip == value:
        selected = second
    else:
        # During the spring DST gap, keep the minute and shift forward by the gap.
        selected = first
    return selected.astimezone(UTC).replace(tzinfo=None)
