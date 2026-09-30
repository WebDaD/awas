from __future__ import annotations

import secrets
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from awas.db.base import Base
from awas.models.auth import utc_now

if TYPE_CHECKING:
    from awas.models.auth import User
    from awas.models.schedule import RecordingSchedule
    from awas.models.stream import Stream

ACTIVE_RECORDING_STATUSES = ("starting", "recording", "stopping")


class Recording(Base):
    __tablename__ = "recordings"
    __table_args__ = (
        CheckConstraint(
            "status IN ('starting', 'recording', 'stopping', 'completed', 'failed', "
            "'interrupted')",
            name="ck_recordings_status",
        ),
        Index("ix_recordings_status_ended_at", "status", "ended_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_key: Mapped[str] = mapped_column(
        String(64),
        default=lambda: secrets.token_hex(16),
        index=True,
    )
    stream_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "streams.id",
            ondelete="SET NULL",
            name="fk_recordings_stream_id_streams",
        ),
        nullable=True,
        index=True,
    )
    stream_name: Mapped[str] = mapped_column(String(128))
    file_name: Mapped[str] = mapped_column(String(255), unique=True)
    storage_directory: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    recorder: Mapped[str] = mapped_column(String(32), default="streamripper")
    file_type: Mapped[str] = mapped_column(String(16), default="ts")
    status: Mapped[str] = mapped_column(String(16), default="starting", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    file_delete_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(512), nullable=True)
    started_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    schedule_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "recording_schedules.id",
            ondelete="SET NULL",
            name="fk_recordings_schedule_id",
        ),
        nullable=True,
        index=True,
    )

    stream: Mapped[Stream | None] = relationship(back_populates="recordings")
    started_by: Mapped[User | None] = relationship()
    schedule: Mapped[RecordingSchedule | None] = relationship(back_populates="recordings")
    files: Mapped[list[RecordingFile]] = relationship(
        back_populates="recording",
        cascade="all, delete-orphan",
    )

    @property
    def is_running(self) -> bool:
        return self.status in ACTIVE_RECORDING_STATUSES

    @property
    def duration_seconds(self) -> int:
        end = utc_now() if self.is_running else self.ended_at
        if end is None:
            return 0
        return max(0, int((end - self.started_at).total_seconds()))


class RecordingFile(Base):
    __tablename__ = "recording_files"
    __table_args__ = (
        UniqueConstraint(
            "storage_directory",
            "file_name",
            name="uq_recording_files_storage_name",
        ),
        Index("ix_recording_files_recording_id", "recording_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recording_id: Mapped[int] = mapped_column(
        ForeignKey("recordings.id", ondelete="CASCADE"),
        nullable=False,
    )
    file_name: Mapped[str] = mapped_column(String(255))
    storage_directory: Mapped[str | None] = mapped_column(String(4096), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    file_deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    file_delete_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)

    recording: Mapped[Recording] = relationship(back_populates="files")
