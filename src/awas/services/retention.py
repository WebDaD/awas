from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from awas.models import Recording, RetentionPolicy, User
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.recording import RecordingError, RecordingManager

logger = logging.getLogger(__name__)
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 1
MAX_RETENTION_DAYS = 3650
MAX_DELETIONS_PER_RUN = 100
TERMINAL_RECORDING_STATUSES = ("completed", "failed", "interrupted")


class RetentionInputError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RetentionPreview:
    cutoff: datetime
    total_count: int
    total_bytes: int
    recordings: tuple[Recording, ...]

    @property
    def is_truncated(self) -> bool:
        return self.total_count > len(self.recordings)


@dataclass(frozen=True, slots=True)
class CleanupResult:
    eligible_count: int
    deleted_count: int
    freed_bytes: int
    failed_count: int
    skipped: bool = False


def ensure_retention_policy(db: Session) -> RetentionPolicy:
    policy = db.get(RetentionPolicy, 1)
    if policy is None:
        policy = RetentionPolicy(
            id=1,
            enabled=False,
            retention_days=DEFAULT_RETENTION_DAYS,
        )
        db.add(policy)
        db.commit()
    return policy


def parse_retention_days(value: str) -> int:
    try:
        days = int(value.strip())
    except ValueError as exc:
        raise RetentionInputError("Die Aufbewahrungsdauer muss eine ganze Zahl sein.") from exc
    if not MIN_RETENTION_DAYS <= days <= MAX_RETENTION_DAYS:
        raise RetentionInputError(
            f"Die Aufbewahrungsdauer muss zwischen {MIN_RETENTION_DAYS} und "
            f"{MAX_RETENTION_DAYS} Tagen liegen."
        )
    return days


def update_retention_policy(
    db: Session,
    policy: RetentionPolicy,
    *,
    enabled: bool,
    retention_days: int,
    actor: User,
    ip_address: str,
) -> None:
    if not MIN_RETENTION_DAYS <= retention_days <= MAX_RETENTION_DAYS:
        raise RetentionInputError(
            f"Die Aufbewahrungsdauer muss zwischen {MIN_RETENTION_DAYS} und "
            f"{MAX_RETENTION_DAYS} Tagen liegen."
        )
    previous = {
        "enabled": policy.enabled,
        "retention_days": policy.retention_days,
    }
    policy.enabled = enabled
    policy.retention_days = retention_days
    policy.updated_at = utc_now()
    policy.updated_by_id = actor.id
    add_audit_entry(
        db,
        "retention.policy.updated",
        actor=actor,
        target_type="retention_policy",
        target_id=policy.id,
        ip_address=ip_address,
        details={
            "previous": previous,
            "enabled": enabled,
            "retention_days": retention_days,
        },
    )
    db.commit()


class RetentionManager:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        recording_manager: RecordingManager,
        *,
        poll_interval: float = 3600,
        initial_delay: float = 60,
    ) -> None:
        self._session_factory = session_factory
        self._recording_manager = recording_manager
        self._poll_interval = poll_interval
        self._initial_delay = initial_delay
        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._run_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._wake_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="awas-retention-manager",
            daemon=True,
        )
        self._thread.start()

    def wake(self) -> None:
        self._wake_event.set()

    def shutdown(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def preview(
        self,
        db: Session,
        policy: RetentionPolicy,
        *,
        now: datetime | None = None,
        limit: int = 50,
    ) -> RetentionPreview:
        cutoff = (now or utc_now()) - timedelta(days=policy.retention_days)
        filters = self._eligible_filters(cutoff)
        total_count, total_bytes = db.execute(
            select(
                func.count(Recording.id),
                func.coalesce(func.sum(Recording.file_size_bytes), 0),
            ).where(*filters)
        ).one()
        recordings = tuple(
            db.scalars(
                select(Recording)
                .where(*filters)
                .order_by(Recording.ended_at, Recording.id)
                .limit(max(0, limit))
            )
        )
        return RetentionPreview(
            cutoff=cutoff,
            total_count=int(total_count),
            total_bytes=int(total_bytes),
            recordings=recordings,
        )

    def run_cleanup(
        self,
        *,
        mode: str,
        actor: User | None = None,
        ip_address: str | None = None,
        now: datetime | None = None,
    ) -> CleanupResult:
        if mode not in {"automatic", "manual"}:
            raise ValueError("Unknown retention cleanup mode")
        current_time = now or utc_now()
        with self._run_lock, self._session_factory() as db:
            policy = ensure_retention_policy(db)
            if mode == "automatic" and not policy.enabled:
                return CleanupResult(0, 0, 0, 0, skipped=True)

            preview = self.preview(db, policy, now=current_time, limit=0)
            candidate_ids = list(
                db.scalars(
                    select(Recording.id)
                    .where(*self._eligible_filters(preview.cutoff))
                    .order_by(Recording.ended_at, Recording.id)
                    .limit(MAX_DELETIONS_PER_RUN)
                )
            )
            deleted_count = 0
            freed_bytes = 0
            failed_count = 0
            for recording_id in candidate_ids:
                recording = db.get(Recording, recording_id)
                if recording is None:
                    continue
                try:
                    deletion = self._recording_manager.delete_recording_file(
                        db,
                        recording=recording,
                        actor=actor,
                        ip_address=ip_address,
                        reason=f"retention.{mode}",
                    )
                except RecordingError:
                    db.rollback()
                    failed_count += 1
                    logger.exception("Retention could not delete recording %s", recording_id)
                    continue
                except Exception:
                    db.rollback()
                    failed_count += 1
                    logger.exception("Retention deletion failed for recording %s", recording_id)
                    continue
                deleted_count += 1
                freed_bytes += deletion.freed_bytes

            policy = ensure_retention_policy(db)
            policy.last_run_at = current_time
            policy.last_run_mode = mode
            policy.last_deleted_count = deleted_count
            policy.last_freed_bytes = freed_bytes
            policy.last_failed_count = failed_count
            policy.last_error = (
                f"{failed_count} Aufnahme(n) konnten nicht gelöscht werden."
                if failed_count
                else None
            )
            add_audit_entry(
                db,
                "retention.cleanup.completed",
                actor=actor,
                target_type="retention_policy",
                target_id=policy.id,
                ip_address=ip_address,
                details={
                    "mode": mode,
                    "cutoff": preview.cutoff.isoformat(),
                    "eligible_count": preview.total_count,
                    "deleted_count": deleted_count,
                    "freed_bytes": freed_bytes,
                    "failed_count": failed_count,
                    "batch_limit": MAX_DELETIONS_PER_RUN,
                },
            )
            db.commit()
            return CleanupResult(
                eligible_count=preview.total_count,
                deleted_count=deleted_count,
                freed_bytes=freed_bytes,
                failed_count=failed_count,
            )

    def run_automatic(self, *, now: datetime | None = None) -> CleanupResult:
        return self.run_cleanup(mode="automatic", now=now)

    def _run_loop(self) -> None:
        delay = self._initial_delay
        while not self._stop_event.is_set():
            self._wake_event.wait(delay)
            self._wake_event.clear()
            if self._stop_event.is_set():
                return
            try:
                result = self.run_automatic()
                if not result.skipped and (result.deleted_count or result.failed_count):
                    logger.info(
                        "Retention cleanup deleted %s recording(s), %s failed",
                        result.deleted_count,
                        result.failed_count,
                    )
            except Exception:
                logger.exception("Retention cleanup iteration failed")
            delay = self._poll_interval

    @staticmethod
    def _eligible_filters(cutoff: datetime) -> tuple[object, ...]:
        return (
            Recording.status.in_(TERMINAL_RECORDING_STATUSES),
            Recording.file_deleted_at.is_(None),
            Recording.ended_at.is_not(None),
            Recording.ended_at <= cutoff,
        )
