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
from glob import escape as glob_escape
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from awas.models import ACTIVE_RECORDING_STATUSES, Recording, Stream, User
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
STAGED_DELETE_PATTERN = re.compile(r"^\.awas-delete-(\d+)-[0-9a-f]{8}\.pending$")


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
                self._set_file_size(recording)
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
            }
            for directory in directories:
                if not directory.is_dir():
                    continue
                for staged_path in directory.glob(".awas-delete-*.pending"):
                    match = STAGED_DELETE_PATTERN.fullmatch(staged_path.name)
                    if match is None or not staged_path.is_file():
                        continue
                    recording = db.get(Recording, int(match.group(1)))
                    try:
                        if recording is None or recording.file_deleted_at is not None:
                            staged_path.unlink()
                            logger.info(
                                "Removed completed recording deletion stage %s",
                                staged_path.name,
                            )
                            continue
                        output_path = self.output_path(recording)
                        if output_path.exists():
                            logger.warning(
                                "Recording deletion stage %s has an existing target",
                                staged_path.name,
                            )
                            continue
                        staged_path.replace(output_path)
                        logger.warning(
                            "Restored recording %s after an interrupted deletion",
                            recording.id,
                        )
                    except OSError:
                        logger.exception(
                            "Could not reconcile recording deletion stage %s", staged_path
                        )

    def storage_snapshot(self, db: Session) -> StorageSnapshot:
        self.recording_directory.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(self.recording_directory)
        recording_count = db.scalar(select(func.count(Recording.id))) or 0
        file_count, recording_bytes = db.execute(
            select(
                func.count(Recording.id),
                func.coalesce(func.sum(Recording.file_size_bytes), 0),
            ).where(Recording.file_deleted_at.is_(None))
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
        if recording.is_running:
            raise RecordingError("Die Datei einer laufenden Aufnahme kann nicht gelöscht werden.")
        if recording.file_deleted_at is not None:
            raise RecordingError("Die Aufnahmedatei wurde bereits gelöscht.")

        output_path = self.output_path(recording)
        staged_path: Path | None = None
        file_removed = False
        file_size_on_disk = 0
        if output_path.exists():
            if not output_path.is_file():
                raise RecordingError("Der Aufnahmepfad ist keine reguläre Datei.")
            staged_path = output_path.parent / (
                f".awas-delete-{recording.id}-{secrets.token_hex(4)}.pending"
            )
            try:
                file_size_on_disk = output_path.stat().st_size
                output_path.replace(staged_path)
            except OSError as exc:
                raise RecordingError("Die Aufnahmedatei konnte nicht gelöscht werden.") from exc
            file_removed = True

        add_audit_entry(
            db,
            "recording.file_deleted",
            actor=actor,
            target_type="recording",
            target_id=recording.id,
            ip_address=ip_address,
            details={
                "stream_id": recording.stream_id,
                "stream_name": recording.stream_name,
                "file_name": recording.file_name,
                "file_size_bytes": recording.file_size_bytes,
                "status": recording.status,
                "file_removed": file_removed,
                "reason": reason,
            },
        )
        recording.file_deleted_at = utc_now()
        recording.file_delete_reason = reason
        try:
            db.commit()
        except Exception:
            db.rollback()
            if staged_path is not None and staged_path.exists() and not output_path.exists():
                try:
                    staged_path.replace(output_path)
                except OSError:
                    logger.exception("Could not restore recording file after database failure")
            raise

        freed_bytes = 0
        if staged_path is not None:
            try:
                staged_path.unlink()
                freed_bytes = file_size_on_disk
            except OSError:
                logger.exception(
                    "Could not remove recording deletion stage %s; retrying at next startup",
                    staged_path,
                )
        return RecordingDeletionResult(file_present=file_removed, freed_bytes=freed_bytes)

    def delete_recording(
        self,
        db: Session,
        *,
        recording: Recording,
        actor: User | None,
        ip_address: str | None,
    ) -> RecordingDeletionResult:
        if recording.is_running:
            raise RecordingError("Eine laufende Aufnahme kann nicht gelöscht werden.")

        output_path = self.output_path(recording)
        staged_path: Path | None = None
        file_removed = False
        file_size_on_disk = 0
        if output_path.exists():
            if not output_path.is_file():
                raise RecordingError("Der Aufnahmepfad ist keine reguläre Datei.")
            staged_path = output_path.parent / (
                f".awas-delete-{recording.id}-{secrets.token_hex(4)}.pending"
            )
            try:
                file_size_on_disk = output_path.stat().st_size
                output_path.replace(staged_path)
            except OSError as exc:
                raise RecordingError("Die Aufnahme konnte nicht gelöscht werden.") from exc
            file_removed = True

        add_audit_entry(
            db,
            "recording.deleted",
            actor=actor,
            target_type="recording",
            target_id=recording.id,
            ip_address=ip_address,
            details={
                "stream_id": recording.stream_id,
                "stream_name": recording.stream_name,
                "file_name": recording.file_name,
                "file_size_bytes": recording.file_size_bytes,
                "status": recording.status,
                "schedule_id": recording.schedule_id,
                "file_removed": file_removed,
                "file_deleted_at": (
                    recording.file_deleted_at.isoformat()
                    if recording.file_deleted_at is not None
                    else None
                ),
            },
        )
        db.delete(recording)
        try:
            db.commit()
        except Exception:
            db.rollback()
            if staged_path is not None and staged_path.exists() and not output_path.exists():
                try:
                    staged_path.replace(output_path)
                except OSError:
                    logger.exception("Could not restore recording file after database failure")
            raise

        freed_bytes = 0
        if staged_path is not None:
            try:
                staged_path.unlink()
                freed_bytes = file_size_on_disk
            except OSError:
                logger.exception(
                    "Could not remove recording deletion stage %s; retrying at next startup",
                    staged_path,
                )
        return RecordingDeletionResult(file_present=file_removed, freed_bytes=freed_bytes)

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
            recording = Recording(
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
        base = Path(
            recording.storage_directory or self._default_recording_directory
        ).resolve()
        candidate = base / recording.file_name
        path = candidate.resolve()
        if path.parent != base or candidate.is_symlink():
            raise RecordingError("Ungültiger Aufnahmepfad.")
        if not path.exists() and recording.recorder == "streamripper":
            output_base = path.with_suffix("")
            if output_base.is_file() and not output_base.is_symlink():
                return output_base
            candidates = [
                item.resolve()
                for item in base.glob(f"{glob_escape(output_base.name)}.*")
                if item.is_file()
                and not item.is_symlink()
                and item.suffix.lower() not in {".cue", ".pending"}
            ]
            candidates = [item for item in candidates if item.parent == base]
            if candidates:
                return max(candidates, key=lambda item: item.stat().st_size)
        return path

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
                self._set_file_size(recording)
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

    def _set_file_size(self, recording: Recording) -> None:
        try:
            path = self.output_path(recording)
            recording.file_size_bytes = path.stat().st_size
            if path.name != recording.file_name:
                recording.file_name = path.name
                suffix = path.suffix.lower().lstrip(".")
                if suffix:
                    recording.file_type = suffix[:16]
        except (OSError, RecordingError):
            recording.file_size_bytes = None

    def _remove_streamripper_cue(self, recording: Recording) -> None:
        if recording.recorder != "streamripper":
            return
        base = Path(
            recording.storage_directory or self._default_recording_directory
        ).resolve()
        expected_path = base / recording.file_name
        output_base = expected_path.with_suffix("")
        candidates = {
            output_base.parent / f"{output_base.name}.cue",
            expected_path.parent / f"{expected_path.name}.cue",
        }
        for cue_path in candidates:
            try:
                if cue_path.parent == base and cue_path.is_file() and not cue_path.is_symlink():
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
