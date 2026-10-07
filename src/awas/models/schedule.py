from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from awas.db.base import Base
from awas.models.auth import utc_now

if TYPE_CHECKING:
    from awas.models.auth import User
    from awas.models.recording import Recording
    from awas.models.recurrence import RecurringSchedule
    from awas.models.stream import Stream


ACTIVE_SCHEDULE_STATUSES = ("scheduled", "running")


class RecordingSchedule(Base):
    __tablename__ = "recording_schedules"
    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled', 'running', 'completed', 'cancelled', 'missed', "
            "'failed')",
            name="ck_recording_schedules_status",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_recording_schedules_time_range"),
        UniqueConstraint(
            "recurrence_id",
            "starts_at",
            name="uq_recording_schedules_recurrence_start",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "streams.id",
            ondelete="SET NULL",
            name="fk_recording_schedules_stream_id_streams",
        ),
        nullable=True,
        index=True,
    )
    stream_name: Mapped[str] = mapped_column(String(128), default="")
    stream_url: Mapped[str] = mapped_column(String(2048), default="")
    title: Mapped[str] = mapped_column(String(128))
    file_name_base: Mapped[str] = mapped_column(String(128), default="")
    recorder: Mapped[str] = mapped_column(String(32), default="streamripper")
    file_type: Mapped[str] = mapped_column(String(16), default="ts")
    starts_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    ends_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="scheduled", index=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    recurrence_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "recurring_schedules.id",
            ondelete="SET NULL",
            name="fk_recording_schedules_recurrence_id",
        ),
        nullable=True,
        index=True,
    )
    occurrence_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    stream: Mapped[Stream | None] = relationship(back_populates="schedules")
    created_by: Mapped[User | None] = relationship()
    recordings: Mapped[list[Recording]] = relationship(back_populates="schedule")
    recurring_schedule: Mapped[RecurringSchedule | None] = relationship(
        back_populates="occurrences"
    )

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_SCHEDULE_STATUSES

    @property
    def is_editable(self) -> bool:
        return self.status == "scheduled"

    @property
    def duration_seconds(self) -> int:
        return max(0, int((self.ends_at - self.starts_at).total_seconds()))
