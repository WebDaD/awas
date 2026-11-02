from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from awas.models import (
    ACTIVE_RECORDING_STATUSES,
    ACTIVE_SCHEDULE_STATUSES,
    FileTypeSetting,
    Recording,
    RecordingSchedule,
    RecurringSchedule,
    Stream,
    User,
)
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.recorders import FILE_TYPE_CHOICES, RecorderInputError, validate_file_type

DEFAULT_FILE_TYPES = tuple(value for value, _ in FILE_TYPE_CHOICES)


def parse_file_types(value: str) -> tuple[str, ...]:
    if len(value) > 2048:
        raise RecorderInputError("Die Dateitypliste darf höchstens 2048 Zeichen lang sein.")
    result: list[str] = []
    for item in value.split(","):
        if not item.strip():
            continue
        try:
            normalized = validate_file_type(item, file_types=None)
        except RecorderInputError as exc:
            raise RecorderInputError(
                "Dateitypen müssen aus 1 bis 16 Buchstaben oder Ziffern bestehen "
                "und durch Kommas getrennt werden."
            ) from exc
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise RecorderInputError("Bitte geben Sie mindestens einen Dateityp ein.")
    if len(", ".join(result)) > 2048:
        raise RecorderInputError("Die Dateitypliste darf höchstens 2048 Zeichen lang sein.")
    return tuple(result)


def configured_file_types(db: Session) -> tuple[str, ...]:
    # Rendering a rejected form must not flush its invalid, submitted stream data.
    with db.no_autoflush:
        setting = db.get(FileTypeSetting, 1)
    return parse_file_types(setting.file_types) if setting is not None else DEFAULT_FILE_TYPES


def file_type_choices(db: Session) -> tuple[tuple[str, str], ...]:
    return tuple((value, value) for value in configured_file_types(db))


def ensure_file_type_settings(db: Session) -> None:
    if db.get(FileTypeSetting, 1) is None:
        db.add(FileTypeSetting(id=1, file_types=", ".join(DEFAULT_FILE_TYPES)))
        db.commit()


def update_file_types(
    db: Session,
    *,
    file_types: str,
    actor: User,
    ip_address: str,
) -> FileTypeSetting:
    normalized = parse_file_types(file_types)
    used = set(db.scalars(select(Stream.preferred_file_type)))
    used.update(
        db.scalars(
            select(RecordingSchedule.file_type).where(
                RecordingSchedule.status.in_(ACTIVE_SCHEDULE_STATUSES),
                RecordingSchedule.is_hidden.is_(False),
            )
        )
    )
    used.update(
        db.scalars(
            select(RecurringSchedule.file_type).where(RecurringSchedule.is_hidden.is_(False))
        )
    )
    used.update(
        db.scalars(
            select(Recording.file_type).where(Recording.status.in_(ACTIVE_RECORDING_STATUSES))
        )
    )
    removed_in_use = sorted(used - set(normalized))
    if removed_in_use:
        raise RecorderInputError(
            "Diese Dateitypen werden noch von Streams, aktiven Aufnahmen oder "
            "Planungen verwendet und müssen in der Liste bleiben: "
            + ", ".join(removed_in_use)
            + "."
        )
    setting = db.get(FileTypeSetting, 1)
    if setting is None:
        setting = FileTypeSetting(id=1, file_types=", ".join(normalized))
        db.add(setting)
    else:
        setting.file_types = ", ".join(normalized)
    setting.updated_at = utc_now()
    setting.updated_by_id = actor.id
    add_audit_entry(
        db,
        "recorder.file_types_updated",
        actor=actor,
        target_type="file_type_settings",
        target_id=1,
        ip_address=ip_address,
        details={"file_types": list(normalized)},
    )
    db.commit()
    return setting
