from __future__ import annotations

import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from awas.models import StorageConfiguration, User
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry


class StorageInputError(ValueError):
    pass


def ensure_storage_configuration(
    db: Session,
    default_directory: Path,
) -> StorageConfiguration:
    configuration = db.get(StorageConfiguration, 1)
    if configuration is None:
        configuration = StorageConfiguration(
            id=1,
            recording_directory=str(default_directory.resolve()),
        )
        db.add(configuration)
        db.commit()
    return configuration


def validate_recording_directory(value: str) -> Path:
    normalized = value.strip()
    if not normalized:
        raise StorageInputError("Der Aufnahmepfad darf nicht leer sein.")
    if len(normalized) > 4096 or any(ord(character) < 32 for character in normalized):
        raise StorageInputError("Der Aufnahmepfad ist ungültig.")
    candidate = Path(normalized)
    if not candidate.is_absolute():
        raise StorageInputError("Der Aufnahmepfad muss absolut sein und mit / beginnen.")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise StorageInputError("Das angegebene Aufnahmeverzeichnis existiert nicht.") from exc
    if not resolved.is_dir():
        raise StorageInputError("Der Aufnahmepfad ist kein Verzeichnis.")
    if resolved == Path(resolved.anchor):
        raise StorageInputError(
            "Das Wurzelverzeichnis kann nicht als Aufnahmepfad verwendet werden."
        )
    try:
        with tempfile.NamedTemporaryFile(
            dir=resolved,
            prefix=".awas-write-test-",
        ):
            pass
    except OSError as exc:
        raise StorageInputError(
            "Der Systembenutzer awas-service kann in dieses Verzeichnis nicht schreiben."
        ) from exc
    return resolved


def update_recording_directory(
    db: Session,
    configuration: StorageConfiguration,
    *,
    recording_directory: str,
    actor: User,
    ip_address: str,
) -> Path:
    normalized_directory = validate_recording_directory(recording_directory)
    previous = configuration.recording_directory
    configuration.recording_directory = str(normalized_directory)
    configuration.updated_at = utc_now()
    configuration.updated_by_id = actor.id
    add_audit_entry(
        db,
        "storage.directory.updated",
        actor=actor,
        target_type="storage_configuration",
        target_id=configuration.id,
        ip_address=ip_address,
        details={
            "previous": previous,
            "current": configuration.recording_directory,
        },
    )
    db.commit()
    return normalized_directory
