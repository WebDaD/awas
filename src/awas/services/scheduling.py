from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from awas.models import (
    ACTIVE_RECORDING_STATUSES,
    ACTIVE_SCHEDULE_STATUSES,
    Recording,
    RecordingSchedule,
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
from awas.services.recording import RecordingError, RecordingManager
from awas.services.recurrence import (
    rebuild_pending_recurring_occurrences,
    refresh_recurring_occurrences,
)

logger = logging.getLogger(__name__)
MAX_SCHEDULE_DURATION = timedelta(days=7)
RETRY_BACKOFF_SECONDS = (15, 30, 60, 120, 300)
RETRY_RESET_AFTER = timedelta(minutes=1)
RETRYABLE_RECORDING_STATUSES = frozenset(("failed", "interrupted"))


class ScheduleInputError(ValueError):
    pass


def parse_local_datetime(value: str, timezone: str, field_name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError as exc:
        raise ScheduleInputError(f"{field_name} ist keine gültige Zeitangabe.") from exc
    if parsed.tzinfo is not None:
        raise ScheduleInputError(f"{field_name} muss als lokale Zeit angegeben werden.")

    zone = ZoneInfo(timezone)
    first = parsed.replace(tzinfo=zone, fold=0)
    second = parsed.replace(tzinfo=zone, fold=1)

    def roundtrips(candidate: datetime) -> bool:
        return candidate.astimezone(UTC).astimezone(zone).replace(tzinfo=None) == parsed

    first_valid = roundtrips(first)
    second_valid = roundtrips(second)
    if not first_valid and not second_valid:
        raise ScheduleInputError(
            f"{field_name} existiert wegen der Zeitumstellung nicht."
        )
    if first_valid and second_valid and first.utcoffset() != second.utcoffset():
        raise ScheduleInputError(
            f"{field_name} ist wegen der Zeitumstellung nicht eindeutig."
        )
    local_value = first if first_valid else second
    return local_value.astimezone(UTC).replace(tzinfo=None)


def datetime_local_value(value: datetime, timezone: str) -> str:
    return value.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%dT%H:%M")


def create_schedule(
    db: Session,
    *,
    stream: Stream,
    title: str,
    file_name_base: str | None = None,
    recorder: str | None = None,
    file_type: str | None = None,
    starts_at: datetime,
    ends_at: datetime,
    actor: User,
    ip_address: str,
    now: datetime | None = None,
) -> RecordingSchedule:
    normalized_title = _validate_schedule(
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        now=now or utc_now(),
        require_future_start=True,
    )
    try:
        normalized_recorder = validate_recorder(recorder or stream.preferred_recorder)
        normalized_file_type = validate_file_type(file_type or stream.preferred_file_type)
        validate_recorder_url(normalized_recorder, stream.stream_url)
        normalized_file_name = normalize_file_name_base(file_name_base or normalized_title)
    except (FileNameInputError, RecorderInputError) as exc:
        raise ScheduleInputError(str(exc)) from exc
    schedule = RecordingSchedule(
        stream_id=stream.id,
        title=normalized_title,
        file_name_base=normalized_file_name,
        recorder=normalized_recorder,
        file_type=normalized_file_type,
        starts_at=starts_at,
        ends_at=ends_at,
        status="scheduled",
        created_by_id=actor.id,
    )
    db.add(schedule)
    db.flush()
    add_audit_entry(
        db,
        "schedule.created",
        actor=actor,
        target_type="recording_schedule",
        target_id=schedule.id,
        ip_address=ip_address,
        details={
            "stream_id": stream.id,
            "starts_at": starts_at.isoformat(),
            "recorder": normalized_recorder,
            "file_type": normalized_file_type,
            "file_name_base": normalized_file_name,
        },
    )
    db.commit()
    return schedule


def update_schedule(
    db: Session,
    schedule: RecordingSchedule,
    *,
    stream: Stream,
    title: str,
    file_name_base: str | None = None,
    recorder: str | None = None,
    file_type: str | None = None,
    starts_at: datetime,
    ends_at: datetime,
    actor: User,
    ip_address: str,
    now: datetime | None = None,
) -> RecordingSchedule:
    if not schedule.is_editable:
        raise ScheduleInputError("Dieser Zeitplan kann nicht mehr bearbeitet werden.")
    normalized_title = _validate_schedule(
        title=title,
        starts_at=starts_at,
        ends_at=ends_at,
        now=now or utc_now(),
        require_future_start=schedule.status == "scheduled",
    )
    try:
        normalized_recorder = validate_recorder(recorder or stream.preferred_recorder)
        normalized_file_type = validate_file_type(file_type or stream.preferred_file_type)
        validate_recorder_url(normalized_recorder, stream.stream_url)
        normalized_file_name = normalize_file_name_base(file_name_base or normalized_title)
    except (FileNameInputError, RecorderInputError) as exc:
        raise ScheduleInputError(str(exc)) from exc
    schedule.stream_id = stream.id
    schedule.title = normalized_title
    schedule.file_name_base = normalized_file_name
    schedule.recorder = normalized_recorder
    schedule.file_type = normalized_file_type
    schedule.starts_at = starts_at
    schedule.ends_at = ends_at
    if schedule.status == "scheduled":
        schedule.error_message = None
    schedule.updated_at = utc_now()
    add_audit_entry(
        db,
        "schedule.updated",
        actor=actor,
        target_type="recording_schedule",
        target_id=schedule.id,
        ip_address=ip_address,
        details={
            "stream_id": stream.id,
            "starts_at": starts_at.isoformat(),
            "recorder": normalized_recorder,
            "file_type": normalized_file_type,
            "file_name_base": normalized_file_name,
            "status": schedule.status,
        },
    )
    db.commit()
    return schedule


def cancel_schedule(
    db: Session,
    schedule: RecordingSchedule,
    *,
    actor: User,
    ip_address: str,
) -> None:
    if schedule.status != "scheduled":
        raise ScheduleInputError("Nur ein noch nicht gestarteter Zeitplan kann verworfen werden.")
    schedule.status = "cancelled"
    schedule.is_hidden = True
    schedule.error_message = None
    schedule.updated_at = utc_now()
    add_audit_entry(
        db,
        "schedule.cancelled",
        actor=actor,
        target_type="recording_schedule",
        target_id=schedule.id,
        ip_address=ip_address,
        details={"stream_id": schedule.stream_id},
    )
    db.commit()


def hide_schedule(
    db: Session,
    schedule: RecordingSchedule,
    *,
    actor: User,
    ip_address: str,
) -> None:
    if schedule.status in ACTIVE_SCHEDULE_STATUSES:
        raise ScheduleInputError(
            "Laufende oder anstehende Zeitpläne müssen zuerst beendet oder verworfen werden."
        )
    schedule.is_hidden = True
    schedule.updated_at = utc_now()
    add_audit_entry(
        db,
        "schedule.entry_deleted",
        actor=actor,
        target_type="recording_schedule",
        target_id=schedule.id,
        ip_address=ip_address,
        details={"stream_id": schedule.stream_id, "status": schedule.status},
    )
    db.commit()


def _validate_schedule(
    *,
    title: str,
    starts_at: datetime,
    ends_at: datetime,
    now: datetime,
    require_future_start: bool,
) -> str:
    normalized_title = " ".join(title.strip().split())
    if not 1 <= len(normalized_title) <= 128:
        raise ScheduleInputError("Die Bezeichnung muss 1 bis 128 Zeichen lang sein.")
    if require_future_start and starts_at <= now:
        raise ScheduleInputError("Die Startzeit muss in der Zukunft liegen.")
    if ends_at <= starts_at:
        raise ScheduleInputError("Die Endzeit muss nach der Startzeit liegen.")
    if ends_at - starts_at > MAX_SCHEDULE_DURATION:
        raise ScheduleInputError("Eine einzelne Aufnahme darf höchstens sieben Tage dauern.")

    return normalized_title


class RecordingScheduler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        recording_manager: RecordingManager,
        timezone: str,
        *,
        poll_interval: float = 1.0,
    ) -> None:
        self._session_factory = session_factory
        self._recording_manager = recording_manager
        self._timezone = timezone
        self._poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._recurrence_refresh_requested = threading.Event()
        self._recurrence_refresh_requested.set()
        self._last_recurrence_refresh: datetime | None = None
        self._run_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="awas-recording-scheduler",
            daemon=True,
        )
        self._thread.start()

    def wake(self, *, refresh_recurring: bool = False) -> None:
        if refresh_recurring:
            self._recurrence_refresh_requested.set()
        self._wake_event.set()

    def set_timezone(self, timezone: str, *, rebuild_pending: bool = False) -> None:
        ZoneInfo(timezone)
        current_time = utc_now()
        with self._run_lock:
            self._timezone = timezone
            if rebuild_pending:
                with self._session_factory() as db:
                    rebuild_pending_recurring_occurrences(
                        db,
                        timezone=timezone,
                        now=current_time,
                    )
                self._last_recurrence_refresh = current_time
                self._recurrence_refresh_requested.clear()
            else:
                self._recurrence_refresh_requested.set()
        self._wake_event.set()

    def stop_schedule(
        self,
        schedule_id: int,
        *,
        actor: User,
        ip_address: str,
    ) -> None:
        with self._run_lock, self._session_factory() as db:
            schedule = db.get(RecordingSchedule, schedule_id)
            if schedule is None:
                raise ScheduleInputError("Der Zeitplan wurde nicht gefunden.")
            if schedule.status != "running":
                raise ScheduleInputError("Diese Aufnahme wird nicht mehr ausgeführt.")

            active = self._active_recording(db, schedule)
            if active is not None and active.status != "stopping":
                try:
                    self._recording_manager.stop_recording(
                        db,
                        recording=active,
                        actor=actor,
                        ip_address=ip_address,
                        reason="user",
                    )
                except RecordingError:
                    logger.info(
                        "Recording %s ended while schedule %s was being stopped",
                        active.id,
                        schedule.id,
                    )

            schedule.status = "completed"
            schedule.error_message = None
            schedule.updated_at = utc_now()
            add_audit_entry(
                db,
                "schedule.stopped",
                actor=actor,
                target_type="recording_schedule",
                target_id=schedule.id,
                ip_address=ip_address,
                details={
                    "stream_id": schedule.stream_id,
                    "recording_id": active.id if active is not None else None,
                },
            )
            db.commit()
        self.wake()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def run_due(self, now: datetime | None = None) -> None:
        current_time = now or utc_now()
        with self._run_lock, self._session_factory() as db:
            refresh_due = (
                self._last_recurrence_refresh is None
                or current_time - self._last_recurrence_refresh >= timedelta(minutes=1)
                or self._recurrence_refresh_requested.is_set()
            )
            if refresh_due:
                refresh_recurring_occurrences(
                    db,
                    timezone=self._timezone,
                    now=current_time,
                )
                self._last_recurrence_refresh = current_time
                self._recurrence_refresh_requested.clear()
            schedules = list(
                db.scalars(
                    select(RecordingSchedule)
                    .where(
                        RecordingSchedule.status.in_(ACTIVE_SCHEDULE_STATUSES),
                        RecordingSchedule.is_hidden.is_(False),
                    )
                    .order_by(RecordingSchedule.starts_at, RecordingSchedule.id)
                )
            )
            for schedule in schedules:
                try:
                    if schedule.status == "scheduled":
                        self._process_scheduled(db, schedule, current_time)
                    else:
                        self._process_running(db, schedule, current_time)
                except Exception:
                    db.rollback()
                    logger.exception("Failed to process recording schedule %s", schedule.id)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_due()
            except Exception:
                logger.exception("Recording scheduler iteration failed")
            self._wake_event.wait(self._poll_interval)
            self._wake_event.clear()

    def _process_scheduled(
        self,
        db: Session,
        schedule: RecordingSchedule,
        now: datetime,
    ) -> None:
        if now >= schedule.ends_at:
            self._set_terminal_status(
                db,
                schedule,
                "missed",
                "Das Aufnahmefenster ist abgelaufen, während AWAS nicht aufnehmen konnte.",
            )
            return
        if now < schedule.starts_at:
            return

        active = self._active_recording(db, schedule)
        if active is not None:
            schedule.status = "running"
            schedule.error_message = None
            schedule.updated_at = now
            db.commit()
            return
        self._start_schedule(db, schedule, now, resumed=False)

    def _process_running(
        self,
        db: Session,
        schedule: RecordingSchedule,
        now: datetime,
    ) -> None:
        active = self._active_recording(db, schedule)
        if active is not None:
            if now >= schedule.ends_at and active.status != "stopping":
                try:
                    self._recording_manager.stop_recording(
                        db,
                        recording=active,
                        actor=None,
                        ip_address=None,
                        reason="schedule",
                    )
                except RecordingError:
                    logger.info("Scheduled recording %s already stopped", active.id)
            return

        attempts = list(
            db.scalars(
                select(Recording)
                .where(Recording.schedule_id == schedule.id)
                .order_by(Recording.started_at.desc(), Recording.id.desc())
                .limit(len(RETRY_BACKOFF_SECONDS))
            )
        )
        latest = attempts[0] if attempts else None
        if latest is not None and latest.status == "completed":
            self._set_terminal_status(db, schedule, "completed", None)
            return
        if now >= schedule.ends_at:
            last_error = latest.error_message if latest is not None else schedule.error_message
            message = "Die Aufnahme konnte bis zum geplanten Ende nicht fortgesetzt werden."
            if last_error:
                message = f"{message} Letzter Fehler: {last_error}"
            self._set_terminal_status(db, schedule, "failed", message)
            return

        if latest is not None and latest.status in RETRYABLE_RECORDING_STATUSES:
            retry_delay = self._retry_delay(attempts)
            retry_at = (latest.ended_at or now) + retry_delay
            if now < retry_at:
                self._set_retry_waiting(
                    db,
                    schedule,
                    message=latest.error_message
                    or "Die Aufnahme wurde vor dem geplanten Ende unterbrochen.",
                    recording_id=latest.id,
                    retry_at=retry_at,
                )
                return
            self._start_schedule(db, schedule, now, resumed=True)
            return

        if latest is None and schedule.error_message:
            retry_at = schedule.updated_at + timedelta(seconds=RETRY_BACKOFF_SECONDS[0])
            if now < retry_at:
                return
        self._start_schedule(db, schedule, now, resumed=latest is not None)

    def _start_schedule(
        self,
        db: Session,
        schedule: RecordingSchedule,
        now: datetime,
        *,
        resumed: bool,
    ) -> None:
        stream = db.get(Stream, schedule.stream_id)
        if stream is None:
            self._set_terminal_status(
                db,
                schedule,
                "failed",
                "Der ausgewählte Stream wurde gelöscht.",
            )
            return
        actor = db.get(User, schedule.created_by_id) if schedule.created_by_id else None
        try:
            recording = self._recording_manager.start_recording(
                db,
                stream=stream,
                actor=actor,
                ip_address=None,
                schedule_id=schedule.id,
                file_name_base=schedule.file_name_base or schedule.title,
                recorder=schedule.recorder,
                file_type=schedule.file_type,
            )
        except RecordingError as exc:
            schedule.status = "running"
            schedule.error_message = (
                f"{exc} AWAS versucht die Aufnahme automatisch erneut."
            )[:512]
            schedule.updated_at = now
            add_audit_entry(
                db,
                "schedule.retry_waiting",
                target_type="recording_schedule",
                target_id=schedule.id,
                details={"stream_id": schedule.stream_id, "reason": str(exc)[:256]},
            )
            db.commit()
            return

        schedule.status = "running"
        schedule.error_message = None
        schedule.updated_at = now
        add_audit_entry(
            db,
            "schedule.resumed" if resumed else "schedule.started",
            target_type="recording_schedule",
            target_id=schedule.id,
            details={"stream_id": schedule.stream_id, "recording_id": recording.id},
        )
        db.commit()

    @staticmethod
    def _retry_delay(attempts: list[Recording]) -> timedelta:
        quick_failures = 0
        for attempt in attempts:
            if attempt.status not in RETRYABLE_RECORDING_STATUSES:
                break
            if attempt.ended_at is None:
                break
            if attempt.ended_at - attempt.started_at >= RETRY_RESET_AFTER:
                break
            quick_failures += 1

        delay_index = min(max(quick_failures, 1) - 1, len(RETRY_BACKOFF_SECONDS) - 1)
        return timedelta(seconds=RETRY_BACKOFF_SECONDS[delay_index])

    @staticmethod
    def _set_retry_waiting(
        db: Session,
        schedule: RecordingSchedule,
        *,
        message: str,
        recording_id: int,
        retry_at: datetime,
    ) -> None:
        retry_message = f"{message} AWAS versucht die Aufnahme automatisch erneut."
        retry_message = retry_message[:512]
        if schedule.error_message == retry_message:
            return
        schedule.error_message = retry_message
        schedule.updated_at = utc_now()
        add_audit_entry(
            db,
            "schedule.retry_waiting",
            target_type="recording_schedule",
            target_id=schedule.id,
            details={
                "stream_id": schedule.stream_id,
                "recording_id": recording_id,
                "retry_at": retry_at.isoformat(),
            },
        )
        db.commit()

    @staticmethod
    def _active_recording(db: Session, schedule: RecordingSchedule) -> Recording | None:
        return db.scalar(
            select(Recording)
            .where(
                Recording.schedule_id == schedule.id,
                Recording.status.in_(ACTIVE_RECORDING_STATUSES),
            )
            .order_by(Recording.started_at.desc(), Recording.id.desc())
            .limit(1)
        )

    @staticmethod
    def _set_terminal_status(
        db: Session,
        schedule: RecordingSchedule,
        status: str,
        error_message: str | None,
    ) -> None:
        schedule.status = status
        schedule.error_message = error_message[:512] if error_message else None
        schedule.updated_at = utc_now()
        add_audit_entry(
            db,
            f"schedule.{status}",
            target_type="recording_schedule",
            target_id=schedule.id,
            details={"stream_id": schedule.stream_id},
        )
        db.commit()
