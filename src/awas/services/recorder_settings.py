from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from awas.models import RecorderSetting, User
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.recorders import (
    RECORDER_BY_KEY,
    RECORDER_PROFILES,
    RecorderInputError,
    validate_argument_template,
    validate_recorder,
)


@dataclass(frozen=True, slots=True)
class RecorderConfiguration:
    key: str
    label: str
    executable: str
    arguments: str
    output_placeholder: str


def ensure_recorder_settings(db: Session) -> None:
    changed = False
    for profile in RECORDER_PROFILES:
        if db.get(RecorderSetting, profile.key) is None:
            db.add(
                RecorderSetting(
                    recorder=profile.key,
                    arguments=profile.default_arguments,
                )
            )
            changed = True
    if changed:
        db.commit()


def recorder_arguments(db: Session, recorder: str) -> str:
    normalized = validate_recorder(recorder)
    setting = db.get(RecorderSetting, normalized)
    if setting is not None:
        return setting.arguments
    return RECORDER_BY_KEY[normalized].default_arguments


def recorder_configurations(db: Session) -> tuple[RecorderConfiguration, ...]:
    return tuple(
        RecorderConfiguration(
            key=profile.key,
            label=profile.label,
            executable=profile.executable,
            arguments=recorder_arguments(db, profile.key),
            output_placeholder=profile.output_placeholder,
        )
        for profile in RECORDER_PROFILES
    )


def update_recorder_arguments(
    db: Session,
    *,
    recorder: str,
    arguments: str,
    actor: User,
    ip_address: str,
) -> RecorderSetting:
    normalized = validate_recorder(recorder)
    normalized_arguments = validate_argument_template(normalized, arguments)
    setting = db.get(RecorderSetting, normalized)
    if setting is None:
        setting = RecorderSetting(recorder=normalized, arguments=normalized_arguments)
        db.add(setting)
    else:
        setting.arguments = normalized_arguments
    setting.updated_at = utc_now()
    setting.updated_by_id = actor.id
    add_audit_entry(
        db,
        "recorder.updated",
        actor=actor,
        target_type="recorder",
        ip_address=ip_address,
        details={"recorder": normalized},
    )
    db.commit()
    return setting


__all__ = [
    "RecorderInputError",
    "ensure_recorder_settings",
    "recorder_arguments",
    "recorder_configurations",
    "update_recorder_arguments",
]
