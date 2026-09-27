from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from awas.db.base import Base
from awas.models.auth import utc_now

if TYPE_CHECKING:
    from awas.models.recording import Recording
    from awas.models.recurrence import RecurringSchedule
    from awas.models.schedule import RecordingSchedule


class Stream(Base):
    __tablename__ = "streams"
    __table_args__ = (UniqueConstraint("name", name="uq_stations_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        String(128, collation="NOCASE"), unique=True, index=True
    )
    stream_url: Mapped[str] = mapped_column(String(2048))
    preferred_recorder: Mapped[str] = mapped_column(String(32), default="streamripper")
    preferred_file_type: Mapped[str] = mapped_column(String(16), default="ts")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_check_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_check_message: Mapped[str | None] = mapped_column(String(256), nullable=True)

    recordings: Mapped[list[Recording]] = relationship(
        back_populates="stream", passive_deletes=True
    )
    schedules: Mapped[list[RecordingSchedule]] = relationship(
        back_populates="stream", passive_deletes=True
    )
    recurring_schedules: Mapped[list[RecurringSchedule]] = relationship(
        back_populates="stream", passive_deletes=True
    )
