from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from awas import __version__
from awas.models import Stream, User
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.recorders import (
    DEFAULT_FILE_TYPE,
    RecorderInputError,
    validate_file_type,
    validate_recorder,
    validate_recorder_url,
)


class StreamInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StreamCheckResult:
    ok: bool
    message: str


def validate_stream_name(name: str) -> str:
    normalized = " ".join(name.strip().split())
    if not 1 <= len(normalized) <= 128:
        raise StreamInputError("Der Streamname muss 1 bis 128 Zeichen lang sein.")
    return normalized


def validate_stream_url(stream_url: str) -> str:
    normalized = stream_url.strip()
    if not 1 <= len(normalized) <= 2048:
        raise StreamInputError("Die Stream-URL muss 1 bis 2048 Zeichen lang sein.")
    if any(ord(character) < 32 for character in normalized):
        raise StreamInputError("Die Stream-URL enthält ungültige Steuerzeichen.")
    try:
        parsed = urlsplit(normalized)
        hostname = parsed.hostname
        _ = parsed.port
    except ValueError as exc:
        raise StreamInputError("Die Stream-URL ist ungültig.") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not hostname:
        raise StreamInputError("Die Stream-URL muss mit http:// oder https:// beginnen.")
    return normalized


def _ensure_unique_name(db: Session, name: str, *, stream_id: int | None = None) -> None:
    statement = select(Stream.id).where(Stream.name == name)
    if stream_id is not None:
        statement = statement.where(Stream.id != stream_id)
    if db.scalar(statement) is not None:
        raise StreamInputError("Ein Stream mit diesem Namen ist bereits vorhanden.")


def create_stream(
    db: Session,
    *,
    name: str,
    stream_url: str,
    preferred_recorder: str,
    preferred_file_type: str | None = None,
    actor: User,
    ip_address: str,
) -> Stream:
    normalized_name = validate_stream_name(name)
    normalized_url = validate_stream_url(stream_url)
    try:
        normalized_recorder = validate_recorder(preferred_recorder)
        normalized_file_type = validate_file_type(preferred_file_type or DEFAULT_FILE_TYPE)
        validate_recorder_url(normalized_recorder, normalized_url)
    except RecorderInputError as exc:
        raise StreamInputError(str(exc)) from exc
    _ensure_unique_name(db, normalized_name)
    stream = Stream(
        name=normalized_name,
        stream_url=normalized_url,
        preferred_recorder=normalized_recorder,
        preferred_file_type=normalized_file_type,
        created_by_id=actor.id,
    )
    db.add(stream)
    db.flush()
    add_audit_entry(
        db,
        "stream.created",
        actor=actor,
        target_type="stream",
        target_id=stream.id,
        ip_address=ip_address,
        details={
            "name": stream.name,
            "preferred_recorder": stream.preferred_recorder,
            "preferred_file_type": stream.preferred_file_type,
        },
    )
    db.commit()
    return stream


def update_stream(
    db: Session,
    stream: Stream,
    *,
    name: str,
    stream_url: str,
    preferred_recorder: str,
    preferred_file_type: str | None = None,
    actor: User,
    ip_address: str,
) -> Stream:
    normalized_name = validate_stream_name(name)
    normalized_url = validate_stream_url(stream_url)
    try:
        normalized_recorder = validate_recorder(preferred_recorder)
        normalized_file_type = validate_file_type(
            preferred_file_type or stream.preferred_file_type
        )
        validate_recorder_url(normalized_recorder, normalized_url)
    except RecorderInputError as exc:
        raise StreamInputError(str(exc)) from exc
    _ensure_unique_name(db, normalized_name, stream_id=stream.id)
    url_changed = stream.stream_url != normalized_url
    stream.name = normalized_name
    stream.stream_url = normalized_url
    stream.preferred_recorder = normalized_recorder
    stream.preferred_file_type = normalized_file_type
    stream.updated_at = utc_now()
    if url_changed:
        stream.last_checked_at = None
        stream.last_check_ok = None
        stream.last_check_message = None
    add_audit_entry(
        db,
        "stream.updated",
        actor=actor,
        target_type="stream",
        target_id=stream.id,
        ip_address=ip_address,
        details={
            "name": stream.name,
            "url_changed": url_changed,
            "preferred_recorder": stream.preferred_recorder,
            "preferred_file_type": stream.preferred_file_type,
        },
    )
    db.commit()
    return stream


def check_stream_url(stream_url: str, *, timeout_seconds: float = 10.0) -> StreamCheckResult:
    headers = {
        "Accept": "audio/*, application/ogg, application/octet-stream, */*;q=0.1",
        "Icy-MetaData": "1",
        "User-Agent": f"AWAS Stream Recorder/{__version__}",
    }
    timeout = httpx.Timeout(timeout_seconds, connect=min(timeout_seconds, 5.0))
    try:
        with (
            httpx.Client(follow_redirects=True, timeout=timeout) as client,
            client.stream("GET", stream_url, headers=headers) as response,
        ):
            response.raise_for_status()
            content_type = response.headers.get("content-type", "unbekannter Inhaltstyp")
            media_type = content_type.split(";", 1)[0].strip().lower()
            if media_type == "text/html":
                return StreamCheckResult(
                    False,
                    "Die URL liefert eine Webseite statt eines Audio-Streams.",
                )
            first_chunk = next(response.iter_raw(chunk_size=1), b"")
            if not first_chunk:
                return StreamCheckResult(False, "Der Stream liefert keine Daten.")
            return StreamCheckResult(
                True,
                f"Erreichbar (HTTP {response.status_code}, {content_type[:96]}).",
            )
    except httpx.TimeoutException:
        return StreamCheckResult(False, "Zeitüberschreitung beim Verbindungsaufbau.")
    except httpx.HTTPStatusError as exc:
        return StreamCheckResult(
            False,
            f"Der Streamserver antwortet mit HTTP {exc.response.status_code}.",
        )
    except httpx.HTTPError:
        return StreamCheckResult(False, "Die Verbindung zum Streamserver ist fehlgeschlagen.")
