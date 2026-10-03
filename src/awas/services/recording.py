from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from glob import escape as glob_escape
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session, sessionmaker

from awas.models import (
    ACTIVE_RECORDING_STATUSES,
    Recording,
    RecordingFile,
    Stream,
    User,
)
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.filenames import recording_file_name
from awas.services.recorder_settings import recorder_arguments
from awas.services.recorders import (
    RecorderInputError,
    RecorderUnavailableError,
    build_recorder_command,
    file_type_extension,
    recorder_label,
    validate_file_type,
    validate_recorder,
    validate_recorder_url,
)

logger = logging.getLogger(__name__)
STAGED_DELETE_PATTERN = re.compile(
    r"^\.awas-delete-(\d+)(?:-(\d+))?-[0-9a-f]{8}\.pending$"
)
STREAMRIPPER_SEQUENCE_SUFFIX = re.compile(r" \(([1-9]\d*)\)$")
RECORDING_TIMESTAMP_PREFIX = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}_"
)


def _streamripper_name_parts(expected: Path) -> tuple[str, str | None]:
    output_stem = STREAMRIPPER_SEQUENCE_SUFFIX.sub("", expected.stem)
    stable_stem = RECORDING_TIMESTAMP_PREFIX.sub("", output_stem, count=1)
    if stable_stem == output_stem:
        return output_stem, None
    return output_stem, f"_{stable_stem}"


def _streamripper_name_matches(expected: Path, candidate_name: str) -> bool:
    output_stem, stable_marker = _streamripper_name_parts(expected)
    markers = ((output_stem, True), (stable_marker, False))
    for marker, must_start in markers:
        if marker is None:
            continue
        marker_index = candidate_name.find(marker)
        if marker_index < 0 or (must_start and marker_index != 0):
            continue
        remainder = candidate_name[marker_index + len(marker) :]
        if not remainder or remainder[0] in " ._-([":
            return True
    return False


class RecordingError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    total_bytes: int
    used_bytes: int
    free_bytes: int
    recording_bytes: int
    recording_count: int
    file_count: int

    @property
    def used_percent(self) -> int:
        if self.total_bytes <= 0:
            return 0
        return min(100, max(0, round(self.used_bytes * 100 / self.total_bytes)))


@dataclass(frozen=True, slots=True)
class RecordingDeletionResult:
    file_present: bool
    freed_bytes: int


@dataclass(frozen=True, slots=True)
class RecordingFileInfo:
    id: int
    recording_id: int
    file_name: str
    size_bytes: int | None
    available: bool
    deleted_at: datetime | None


@dataclass(frozen=True, slots=True)
class RecordingGroup:
    group_key: str
    attempts: tuple[Recording, ...]
    files: tuple[RecordingFileInfo, ...]

    @property
    def id(self) -> int:
        return self.attempts[0].id

    @property
    def active_recording(self) -> Recording | None:
        return next(
            (item for item in reversed(self.attempts) if item.is_running),
            None,
        )

    @property
    def current_recording(self) -> Recording:
        return self.active_recording or self.attempts[-1]

    @property
    def is_running(self) -> bool:
        return self.active_recording is not None

    @property
    def status(self) -> str:
        return self.current_recording.status

    @property
    def stream_name(self) -> str:
        return self.attempts[0].stream_name

    @property
    def recorder(self) -> str:
        return self.current_recording.recorder

    @property
    def file_type(self) -> str:
        return self.current_recording.file_type

    @property
    def started_at(self) -> datetime:
        return self.attempts[0].started_at

    @property
    def ended_at(self) -> datetime | None:
        return max(
            (item.ended_at for item in self.attempts if item.ended_at is not None),
            default=None,
        )

    @property
    def duration_seconds(self) -> int:
        end = utc_now() if self.is_running else self.ended_at
        if end is None:
            return 0
        return max(0, int((end - self.started_at).total_seconds()))

    @property
    def error_message(self) -> str | None:
        return self.current_recording.error_message

    @property
    def schedule(self):
        return next(
            (item.schedule for item in self.attempts if item.schedule is not None),
            None,
        )

    @property
    def schedule_id(self) -> int | None:
        return self.attempts[0].schedule_id

    @property
    def started_by(self):
        return next(
            (item.started_by for item in self.attempts if item.started_by is not None),
            None,
        )

    @property
    def started_by_id(self) -> int | None:
        return next(
            (item.started_by_id for item in self.attempts if item.started_by_id is not None),
            None,
        )

    @property
    def available_file_count(self) -> int:
        return sum(item.available for item in self.files)

    @property
    def file_size_bytes(self) -> int:
        return sum(item.size_bytes or 0 for item in self.files)

    @property
    def display_file_name(self) -> str:
        if not self.files:
            return "Keine Datei"
        if len(self.files) == 1:
            return self.files[0].file_name
        return f"{len(self.files)} Dateien"


@dataclass(slots=True)
class _RunningRecording:
    process: subprocess.Popen[bytes]
    thread: threading.Thread | None = None
    stop_reason: str | None = None


class RecordingManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        recording_directory: Path,
        timezone: str,
    ) -> None:
        self._session_factory = session_factory
        self._default_recording_directory = recording_directory.resolve()
        self._recording_directory = self._default_recording_directory
        self._timezone = timezone
        self._running: dict[int, _RunningRecording] = {}
        self._lock = threading.Lock()

    @property
    def recording_directory(self) -> Path:
        return self._recording_directory

    def set_recording_directory(self, recording_directory: Path) -> None:
        with self._lock:
            self._recording_directory = recording_directory.resolve()

    def set_timezone(self, timezone: str) -> None:
        ZoneInfo(timezone)
        with self._lock:
            self._timezone = timezone

    def recording_groups(
        self,
        db: Session,
        recordings: list[Recording] | tuple[Recording, ...],
    ) -> list[RecordingGroup]:
        if not recordings:
            return []
        group_keys = {recording.group_key for recording in recordings}
        attempts = list(
            db.scalars(
                select(Recording)
                .where(Recording.group_key.in_(group_keys))
                .order_by(Recording.started_at, Recording.id)
            )
        )
        if self._sync_recording_files(db, attempts):
            db.commit()
        files = list(
            db.scalars(
                select(RecordingFile)
                .where(RecordingFile.recording_id.in_([item.id for item in attempts]))
                .order_by(RecordingFile.discovered_at, RecordingFile.id)
            )
        )
        files_by_recording: dict[int, list[RecordingFileInfo]] = {}
        for recording_file in files:
            files_by_recording.setdefault(recording_file.recording_id, []).append(
                self._file_info(recording_file)
            )

        attempts_by_group: dict[str, list[Recording]] = {}
        for attempt in attempts:
            attempts_by_group.setdefault(attempt.group_key, []).append(attempt)
        groups = [
            RecordingGroup(
                group_key=group_key,
                attempts=tuple(group_attempts),
                files=tuple(
                    file_info
                    for attempt in group_attempts
                    for file_info in files_by_recording.get(attempt.id, ())
                ),
            )
            for group_key, group_attempts in attempts_by_group.items()
        ]
        groups.sort(key=lambda item: (item.started_at, item.id), reverse=True)
        return groups

    def recording_group(self, db: Session, recording: Recording) -> RecordingGroup:
        groups = self.recording_groups(db, [recording])
        if not groups:
            raise RecordingError("Die Aufnahme wurde nicht gefunden.")
        return groups[0]

    def available_group_files(
        self,
        db: Session,
        recording: Recording,
    ) -> list[tuple[RecordingFile, Path, int]]:
        group = self.recording_group(db, recording)
        file_ids = [item.id for item in group.files if item.available]
        if not file_ids:
            return []
        file_records = {
            item.id: item
            for item in db.scalars(
                select(RecordingFile).where(RecordingFile.id.in_(file_ids))
            )
        }
        result: list[tuple[RecordingFile, Path, int]] = []
        for info in group.files:
            recording_file = file_records.get(info.id)
            if recording_file is None or not info.available:
                continue
            path = self.recording_file_path(recording_file)
            try:
                size = path.stat().st_size
            except OSError:
                continue
            result.append((recording_file, path, size))
        return result

    def reconcile_interrupted(self) -> None:
        with self._session_factory() as db:
            recordings = list(
                db.scalars(
                    select(Recording).where(Recording.status.in_(ACTIVE_RECORDING_STATUSES))
                )
            )
            for recording in recordings:
                recording.status = "interrupted"
                recording.ended_at = utc_now()
                recording.error_message = "AWAS wurde während der Aufnahme neu gestartet."
                self._remove_streamripper_cue(recording)
                self._sync_recording_files(db, [recording])
                add_audit_entry(
                    db,
                    "recording.interrupted",
                    target_type="recording",
                    target_id=recording.id,
                    details={"stream_id": recording.stream_id},
                )
            if recordings:
                db.commit()

    def reconcile_staged_deletions(self) -> None:
        self.recording_directory.mkdir(parents=True, exist_ok=True)
        with self._session_factory() as db:
            directories = {
                self._default_recording_directory,
                self.recording_directory,
                *(
                    Path(value)
                    for value in db.scalars(
                        select(Recording.storage_directory).where(
                            Recording.storage_directory.is_not(None)
                        )
                    )
                    if value
                ),
                *(
                    Path(value)
                    for value in db.scalars(
                        select(RecordingFile.storage_directory).where(
                            RecordingFile.storage_directory.is_not(None)
                        )
                    )
                    if value
                ),
            }
            for directory in directories:
                if not directory.is_dir():
                    continue
                for staged_path in directory.glob(".awas-delete-*.pending"):
                    match = STAGED_DELETE_PATTERN.fullmatch(staged_path.name)
                    if match is None or not staged_path.is_file():
                        continue
                    try:
                        recording = db.get(Recording, int(match.group(1)))
                        recording_file = (
                            db.get(RecordingFile, int(match.group(2)))
                            if match.group(2)
                            else None
                        )
                        completed = (
                            (recording_file is None and match.group(2) is not None)
                            or (
                                recording_file is not None
                                and recording_file.file_deleted_at is not None
                            )
                            or (
                                match.group(2) is None
                                and (
                                    recording is None
                                    or recording.file_deleted_at is not None
                                )
                            )
                        )
                        if completed:
                            staged_path.unlink()
                            logger.info(
                                "Removed completed recording deletion stage %s",
                                staged_path.name,
                            )
                            continue
                        output_path = (
                            self.recording_file_path(recording_file)
                            if recording_file is not None
                            else self.output_path(recording)
                        )
                        if output_path.exists():
                            logger.warning(
                                "Recording deletion stage %s has an existing target",
                                staged_path.name,
                            )
                            continue
                        staged_path.replace(output_path)
                        logger.warning(
                            "Restored recording %s after an interrupted deletion",
                            recording.id if recording is not None else match.group(1),
                        )
                    except OSError:
                        logger.exception(
                            "Could not reconcile recording deletion stage %s", staged_path
                        )

    def storage_snapshot(self, db: Session) -> StorageSnapshot:
        self.recording_directory.mkdir(parents=True, exist_ok=True)
        sync_candidates = list(
            db.scalars(
                select(Recording).where(
                    Recording.status.in_(ACTIVE_RECORDING_STATUSES)
                    | ~Recording.files.any()
                )
            )
        )
        if self._sync_recording_files(db, sync_candidates):
            db.commit()
        usage = shutil.disk_usage(self.recording_directory)
        recording_count = (
            db.scalar(select(func.count(distinct(Recording.group_key)))) or 0
        )
        file_count, recording_bytes = db.execute(
            select(
                func.count(RecordingFile.id),
                func.coalesce(func.sum(RecordingFile.file_size_bytes), 0),
            ).where(RecordingFile.file_deleted_at.is_(None))
        ).one()
        return StorageSnapshot(
            total_bytes=usage.total,
            used_bytes=usage.used,
            free_bytes=usage.free,
            recording_bytes=int(recording_bytes),
            recording_count=int(recording_count),
            file_count=int(file_count),
        )

    def current_file_size(self, recording: Recording) -> int | None:
        if recording.file_deleted_at is not None:
            return None
        try:
            path = self.output_path(recording)
            return path.stat().st_size if path.is_file() else None
        except (OSError, RecordingError):
            return None

    def delete_recording_file(
        self,
        db: Session,
        *,
        recording: Recording,
        actor: User | None,
        ip_address: str | None,
        reason: str = "manual",
    ) -> RecordingDeletionResult:
        if reason not in {"manual", "retention.manual", "retention.automatic"}:
            raise ValueError("Unknown recording deletion reason")
        group = self.recording_group(db, recording)
        if group.is_running:
            raise RecordingError("Die Datei einer laufenden Aufnahme kann nicht gelöscht werden.")
        if group.attempts and all(
            item.file_deleted_at is not None for item in group.attempts
        ):
            raise RecordingError("Die Aufnahmedatei wurde bereits gelöscht.")
        staged = self._stage_group_files(db, group)
        file_records = list(
            db.scalars(
                select(RecordingFile).where(
                    RecordingFile.recording_id.in_([item.id for item in group.attempts])
                )
            )
        )
        deleted_at = utc_now()

        add_audit_entry(
            db,
            "recording.file_deleted",
            actor=actor,
            target_type="recording",
            target_id=group.id,
            ip_address=ip_address,
            details={
                "stream_id": group.attempts[0].stream_id,
                "stream_name": group.stream_name,
                "file_name": group.files[0].file_name if group.files else None,
                "file_names": [item.file_name for item in group.files],
                "file_size_bytes": group.file_size_bytes,
                "status": group.status,
                "file_removed": bool(staged),
                "reason": reason,
            },
        )
        for recording_file in file_records:
            if recording_file.file_deleted_at is None:
                recording_file.file_deleted_at = deleted_at
                recording_file.file_delete_reason = reason
        for attempt in group.attempts:
            attempt.file_deleted_at = deleted_at
            attempt.file_delete_reason = reason
        try:
            db.commit()
        except Exception:
            db.rollback()
            self._restore_staged_files(staged)
            raise
        return RecordingDeletionResult(
            file_present=bool(staged),
            freed_bytes=self._finalize_staged_files(staged),
        )

    def delete_recording(
        self,
        db: Session,
        *,
        recording: Recording,
        actor: User | None,
        ip_address: str | None,
    ) -> RecordingDeletionResult:
        group = self.recording_group(db, recording)
        if group.is_running:
            raise RecordingError("Eine laufende Aufnahme kann nicht gelöscht werden.")
        staged = self._stage_group_files(db, group)

        add_audit_entry(
            db,
            "recording.deleted",
            actor=actor,
            target_type="recording",
            target_id=group.id,
            ip_address=ip_address,
            details={
                "stream_id": group.attempts[0].stream_id,
                "stream_name": group.stream_name,
                "file_name": group.files[0].file_name if group.files else None,
                "file_names": [item.file_name for item in group.files],
                "file_size_bytes": group.file_size_bytes,
                "status": group.status,
                "schedule_id": group.schedule_id,
                "file_removed": bool(staged),
            },
        )
        for attempt in group.attempts:
            db.delete(attempt)
        try:
            db.commit()
        except Exception:
            db.rollback()
            self._restore_staged_files(staged)
            raise
        return RecordingDeletionResult(
            file_present=bool(staged),
            freed_bytes=self._finalize_staged_files(staged),
        )

    def _stage_group_files(
        self,
        db: Session,
        group: RecordingGroup,
    ) -> list[tuple[Path, Path, int]]:
        for attempt in group.attempts:
            self._expected_output_path(attempt)
        file_records = list(
            db.scalars(
                select(RecordingFile).where(
                    RecordingFile.recording_id.in_([item.id for item in group.attempts]),
                    RecordingFile.file_deleted_at.is_(None),
                )
            )
        )
        staged: list[tuple[Path, Path, int]] = []
        try:
            for recording_file in file_records:
                output_path = self.recording_file_path(recording_file)
                if not output_path.exists():
                    continue
                if not output_path.is_file() or output_path.is_symlink():
                    raise RecordingError("Der Aufnahmepfad ist keine reguläre Datei.")
                staged_path = output_path.parent / (
                    f".awas-delete-{group.id}-{recording_file.id}-"
                    f"{secrets.token_hex(4)}.pending"
                )
                size = output_path.stat().st_size
                output_path.replace(staged_path)
                staged.append((output_path, staged_path, size))
        except RecordingError:
            self._restore_staged_files(staged)
            raise
        except OSError as exc:
            self._restore_staged_files(staged)
            raise RecordingError("Die Aufnahmedateien konnten nicht gelöscht werden.") from exc
        return staged

    @staticmethod
    def _restore_staged_files(staged: list[tuple[Path, Path, int]]) -> None:
        for output_path, staged_path, _ in reversed(staged):
            if not staged_path.exists() or output_path.exists():
                continue
            try:
                staged_path.replace(output_path)
            except OSError:
                logger.exception("Could not restore recording file after database failure")

    @staticmethod
    def _finalize_staged_files(staged: list[tuple[Path, Path, int]]) -> int:
        freed_bytes = 0
        for _, staged_path, size in staged:
            try:
                staged_path.unlink()
                freed_bytes += size
            except OSError:
                logger.exception(
                    "Could not remove recording deletion stage %s; retrying at next startup",
                    staged_path,
                )
        return freed_bytes

    def start_recording(
        self,
        db: Session,
        *,
        stream: Stream,
        actor: User | None,
        ip_address: str | None,
        schedule_id: int | None = None,
        file_name_base: str | None = None,
        recorder: str | None = None,
        file_type: str | None = None,
    ) -> Recording:
        try:
            selected_recorder = validate_recorder(recorder or stream.preferred_recorder)
            selected_file_type = validate_file_type(file_type or stream.preferred_file_type)
            validate_recorder_url(selected_recorder, stream.stream_url)
        except RecorderInputError as exc:
            raise RecordingError(str(exc)) from exc

        with self._lock:
            recording_directory = self._recording_directory
            try:
                recording_directory.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                raise RecordingError(
                    "Das Aufnahmeverzeichnis ist nicht verfügbar oder nicht beschreibbar."
                ) from exc
            file_name = recording_file_name(
                file_name_base or stream.name,
                file_type_extension(selected_file_type),
                self._timezone,
            )
            output_path = recording_directory / file_name
            try:
                command = build_recorder_command(
                    selected_recorder,
                    stream_url=stream.stream_url,
                    output_path=output_path,
                    file_type=selected_file_type,
                    argument_template=recorder_arguments(db, selected_recorder),
                )
            except (RecorderInputError, RecorderUnavailableError) as exc:
                raise RecordingError(str(exc)) from exc
            group_key = secrets.token_hex(16)
            if schedule_id is not None:
                existing_group_key = db.scalar(
                    select(Recording.group_key)
                    .where(Recording.schedule_id == schedule_id)
                    .order_by(Recording.id)
                    .limit(1)
                )
                if existing_group_key:
                    group_key = existing_group_key
            recording = Recording(
                group_key=group_key,
                stream_id=stream.id,
                stream_name=stream.name,
                file_name=file_name,
                storage_directory=str(recording_directory),
                recorder=selected_recorder,
                file_type=selected_file_type,
                status="starting",
                started_at=utc_now(),
                started_by_id=actor.id if actor else None,
                schedule_id=schedule_id,
            )
            db.add(recording)
            db.flush()
            add_audit_entry(
                db,
                "recording.started",
                actor=actor,
                target_type="recording",
                target_id=recording.id,
                ip_address=ip_address,
                details={
                    "stream_id": stream.id,
                    "stream_name": stream.name,
                    "schedule_id": schedule_id,
                    "recorder": selected_recorder,
                    "file_type": selected_file_type,
                    "file_name_base": file_name_base or stream.name,
                    "storage_directory": str(recording_directory),
                    "group_key": group_key,
                },
            )
            db.commit()

            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as exc:
                recording.status = "failed"
                recording.ended_at = utc_now()
                label = recorder_label(selected_recorder)
                recording.error_message = f"{label} konnte nicht gestartet werden."
                add_audit_entry(
                    db,
                    "recording.failed",
                    target_type="recording",
                    target_id=recording.id,
                    details={"stream_id": stream.id, "reason": "spawn_failed"},
                )
                db.commit()
                raise RecordingError(f"{label} konnte nicht gestartet werden.") from exc

            running = _RunningRecording(process=process)
            self._running[recording.id] = running
            recording.status = "recording"
            db.commit()
            thread = threading.Thread(
                target=self._watch_process,
                args=(recording.id, process),
                name=f"awas-recording-{recording.id}",
                daemon=True,
            )
            running.thread = thread
            thread.start()
            return recording

    def stop_recording(
        self,
        db: Session,
        *,
        recording: Recording,
        actor: User | None,
        ip_address: str | None,
        reason: str = "user",
    ) -> None:
        if reason not in {"user", "schedule"}:
            raise ValueError("Unknown recording stop reason")
        with self._lock:
            running = self._running.get(recording.id)
            if running is None or running.process.poll() is not None:
                raise RecordingError("Diese Aufnahme läuft nicht mehr.")
            running.stop_reason = reason
            process = running.process
            recording.status = "stopping"
            add_audit_entry(
                db,
                "recording.stop_requested",
                actor=actor,
                target_type="recording",
                target_id=recording.id,
                ip_address=ip_address,
                details={"stream_id": recording.stream_id, "reason": reason},
            )
            db.commit()
        with suppress(ProcessLookupError):
            self._terminate_process_group(process)

    def output_path(self, recording: Recording) -> Path:
        expected = self._expected_output_path(recording)
        candidates = self._recording_candidate_paths(recording)
        if expected in candidates:
            return expected
        if candidates:
            return max(candidates, key=lambda item: item.stat().st_size)
        return expected

    def recording_file_path(self, recording_file: RecordingFile) -> Path:
        base = Path(
            recording_file.storage_directory or self._default_recording_directory
        ).resolve()
        candidate = base / recording_file.file_name
        path = candidate.resolve()
        if path.parent != base or candidate.is_symlink():
            raise RecordingError("Ungültiger Aufnahmepfad.")
        return path

    def _expected_output_path(self, recording: Recording) -> Path:
        base = Path(
            recording.storage_directory or self._default_recording_directory
        ).resolve()
        candidate = base / recording.file_name
        path = candidate.resolve()
        if path.parent != base or candidate.is_symlink():
            raise RecordingError("Ungültiger Aufnahmepfad.")
        return path

    def _recording_candidate_paths(self, recording: Recording) -> list[Path]:
        expected = self._expected_output_path(recording)
        if recording.recorder != "streamripper":
            return [expected] if expected.is_file() and not expected.is_symlink() else []

        base = expected.parent
        output_stem, stable_marker = _streamripper_name_parts(expected)
        patterns = [f"{glob_escape(output_stem)}*"]
        if stable_marker is not None:
            patterns.append(f"*{glob_escape(stable_marker)}*")
        candidates: list[Path] = []
        seen: set[Path] = set()
        for pattern in patterns:
            for item in base.glob(pattern):
                if (
                    item in seen
                    or not _streamripper_name_matches(expected, item.name)
                    or not item.is_file()
                    or item.is_symlink()
                    or item.name.lower().endswith((".cue", ".pending"))
                ):
                    continue
                resolved = item.resolve()
                if resolved.parent != base:
                    continue
                seen.add(item)
                candidates.append(resolved)

        def sort_key(path: Path) -> tuple[object, ...]:
            natural_parts = tuple(
                (0, int(part)) if part.isdigit() else (1, part.casefold())
                for part in re.split(r"(\d+)", path.name)
                if part
            )
            return (0 if path == expected else 1, natural_parts)

        candidates.sort(key=sort_key)
        return candidates

    def _sync_recording_files(
        self,
        db: Session,
        recordings: list[Recording] | tuple[Recording, ...],
    ) -> bool:
        if not recordings:
            return False
        recording_ids = [recording.id for recording in recordings]
        existing_files = list(
            db.scalars(
                select(RecordingFile).where(
                    RecordingFile.recording_id.in_(recording_ids)
                )
            )
        )
        by_key = {
            (item.recording_id, item.file_name): item for item in existing_files
        }
        changed = False
        now = utc_now()
        for recording in recordings:
            try:
                discovered = self._recording_candidate_paths(recording)
            except RecordingError:
                logger.warning(
                    "Skipped unsafe recording path for recording %s",
                    recording.id,
                )
                discovered = []
            for path in discovered:
                key = (recording.id, path.name)
                recording_file = by_key.get(key)
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if recording_file is None:
                    recording_file = RecordingFile(
                        recording_id=recording.id,
                        file_name=path.name,
                        storage_directory=str(path.parent),
                        file_size_bytes=size,
                        discovered_at=now,
                        updated_at=now,
                    )
                    db.add(recording_file)
                    existing_files.append(recording_file)
                    by_key[key] = recording_file
                    changed = True
                elif (
                    recording_file.file_deleted_at is None
                    and recording_file.file_size_bytes != size
                ):
                    recording_file.file_size_bytes = size
                    recording_file.updated_at = now
                    changed = True

            recording_files = [
                item for item in existing_files if item.recording_id == recording.id
            ]
            if not recording_files and not recording.is_running:
                recording_file = RecordingFile(
                    recording_id=recording.id,
                    file_name=recording.file_name,
                    storage_directory=recording.storage_directory,
                    file_size_bytes=recording.file_size_bytes,
                    discovered_at=recording.started_at,
                    updated_at=recording.ended_at or recording.started_at,
                    file_deleted_at=recording.file_deleted_at,
                    file_delete_reason=recording.file_delete_reason,
                )
                db.add(recording_file)
                existing_files.append(recording_file)
                by_key[(recording.id, recording.file_name)] = recording_file
                changed = True

            total_size = sum(
                item.file_size_bytes or 0
                for item in existing_files
                if item.recording_id == recording.id
            )
            if recording.file_size_bytes != total_size:
                recording.file_size_bytes = total_size
                changed = True
        if changed:
            db.flush()
        return changed

    def _file_info(self, recording_file: RecordingFile) -> RecordingFileInfo:
        available = False
        current_size = recording_file.file_size_bytes
        if recording_file.file_deleted_at is None:
            try:
                path = self.recording_file_path(recording_file)
                if path.is_file() and not path.is_symlink():
                    current_size = path.stat().st_size
                    available = True
            except (OSError, RecordingError):
                available = False
        return RecordingFileInfo(
            id=recording_file.id,
            recording_id=recording_file.recording_id,
            file_name=recording_file.file_name,
            size_bytes=current_size,
            available=available,
            deleted_at=recording_file.file_deleted_at,
        )

    def shutdown(self) -> None:
        with self._lock:
            running_items = list(self._running.values())
            for running in running_items:
                running.stop_reason = "shutdown"
                if running.process.poll() is None:
                    with suppress(ProcessLookupError):
                        self._terminate_process_group(running.process)
        for running in running_items:
            if running.thread is not None:
                running.thread.join(timeout=8)
            if running.process.poll() is None:
                with suppress(ProcessLookupError):
                    self._kill_process_group(running.process)
                if running.thread is not None:
                    running.thread.join(timeout=2)

    def _watch_process(self, recording_id: int, process: subprocess.Popen[bytes]) -> None:
        process.wait()
        with self._lock:
            running = self._running.get(recording_id)
            stop_reason = running.stop_reason if running else None

        try:
            with self._session_factory() as db:
                recording = db.get(Recording, recording_id)
                if recording is None:
                    return
                recording.ended_at = utc_now()
                self._remove_streamripper_cue(recording)
                self._sync_recording_files(db, [recording])
                ended_early = (
                    recording.schedule is not None
                    and recording.ended_at < recording.schedule.ends_at
                )
                if stop_reason in {"user", "schedule"}:
                    recording.status = "completed"
                    recording.error_message = None
                    action = "recording.completed"
                elif stop_reason == "shutdown":
                    recording.status = "interrupted"
                    recording.error_message = "AWAS wurde während der Aufnahme beendet."
                    action = "recording.interrupted"
                elif ended_early:
                    recording.status = "interrupted"
                    recording.error_message = (
                        f"{recorder_label(recording.recorder)} wurde vor dem geplanten Ende "
                        f"mit Status {process.returncode} beendet."
                    )
                    action = "recording.interrupted"
                elif process.returncode == 0:
                    recording.status = "completed"
                    recording.error_message = None
                    action = "recording.completed"
                else:
                    recording.status = "failed"
                    recording.error_message = (
                        f"{recorder_label(recording.recorder)} wurde mit Status "
                        f"{process.returncode} beendet."
                    )
                    action = "recording.failed"
                add_audit_entry(
                    db,
                    action,
                    target_type="recording",
                    target_id=recording.id,
                    details={
                        "stream_id": recording.stream_id,
                        "file_size_bytes": recording.file_size_bytes,
                        "return_code": process.returncode,
                    },
                )
                db.commit()
        finally:
            with self._lock:
                self._running.pop(recording_id, None)

    def _remove_streamripper_cue(self, recording: Recording) -> None:
        if recording.recorder != "streamripper":
            return
        expected_path = self._expected_output_path(recording)
        output_stem, stable_marker = _streamripper_name_parts(expected_path)
        patterns = [f"{glob_escape(output_stem)}*.cue"]
        if stable_marker is not None:
            patterns.append(f"*{glob_escape(stable_marker)}*.cue")
        seen: set[Path] = set()
        for pattern in patterns:
            for cue_path in expected_path.parent.glob(pattern):
                if cue_path in seen:
                    continue
                seen.add(cue_path)
                try:
                    if (
                        _streamripper_name_matches(expected_path, cue_path.name)
                        and cue_path.name.lower().endswith(".cue")
                        and cue_path.parent == expected_path.parent
                        and cue_path.is_file()
                        and not cue_path.is_symlink()
                    ):
                        cue_path.unlink()
                except OSError:
                    logger.warning(
                        "Could not remove streamripper cue file %s",
                        cue_path.name,
                        exc_info=True,
                    )

    @staticmethod
    def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
        os.killpg(process.pid, signal.SIGTERM)

    @staticmethod
    def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
        os.killpg(process.pid, signal.SIGKILL)
