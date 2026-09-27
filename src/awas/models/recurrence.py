from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from awas.db.base import Base
from awas.models.auth import utc_now

if TYPE_CHECKING:
    from awas.models.auth import User
    from awas.models.schedule import RecordingSchedule
    from awas.models.stream import Stream


WEEKDAY_LABELS = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")
WEEKDAY_NAMES = (
    "Montag",
    "Dienstag",
    "Mittwoch",
    "Donnerstag",
    "Freitag",
    "Samstag",
    "Sonntag",
)
MONTH_WEEK_LABELS = {
    -1: "letzter",
    1: "erster",
    2: "zweiter",
    3: "dritter",
    4: "vierter",
    5: "fünfter",
}


class RecurringSchedule(Base):
    __tablename__ = "recurring_schedules"
    __table_args__ = (
        CheckConstraint(
            "weekday_mask BETWEEN 1 AND 127",
            name="ck_recurring_schedules_weekday_mask",
        ),
        CheckConstraint(
            "start_minute BETWEEN 0 AND 1439",
            name="ck_recurring_schedules_start_minute",
        ),
        CheckConstraint(
            "duration_minutes BETWEEN 1 AND 1440",
            name="ck_recurring_schedules_duration",
        ),
        CheckConstraint(
            "recurrence_type IN "
            "('hourly', 'daily', 'weekly', 'monthly_day', 'monthly_weekday')",
            name="ck_recurring_schedules_type",
        ),
        CheckConstraint(
            "interval_count BETWEEN 1 AND 999",
            name="ck_recurring_schedules_interval",
        ),
        CheckConstraint(
            "month_day IS NULL OR month_day BETWEEN 1 AND 31",
            name="ck_recurring_schedules_month_day",
        ),
        CheckConstraint(
            "month_week IS NULL OR month_week = -1 OR month_week BETWEEN 1 AND 5",
            name="ck_recurring_schedules_month_week",
        ),
        CheckConstraint(
            "valid_until IS NULL OR valid_until >= valid_from",
            name="ck_recurring_schedules_valid_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stream_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "streams.id",
            ondelete="SET NULL",
            name="fk_recurring_schedules_stream_id_streams",
        ),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(128))
    file_name_base: Mapped[str] = mapped_column(String(128), default="")
    recorder: Mapped[str] = mapped_column(String(32), default="streamripper")
    file_type: Mapped[str] = mapped_column(String(16), default="ts")
    recurrence_type: Mapped[str] = mapped_column(String(24), default="weekly")
    interval_count: Mapped[int] = mapped_column(Integer, default=1)
    weekday_mask: Mapped[int] = mapped_column(Integer)
    month_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    month_week: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_minute: Mapped[int] = mapped_column(Integer)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    is_hidden: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)

    stream: Mapped[Stream | None] = relationship(back_populates="recurring_schedules")
    created_by: Mapped[User | None] = relationship()
    occurrences: Mapped[list[RecordingSchedule]] = relationship(
        back_populates="recurring_schedule"
    )

    @property
    def weekdays(self) -> tuple[int, ...]:
        return tuple(day for day in range(7) if self.weekday_mask & (1 << day))

    @property
    def weekday_label(self) -> str:
        if self.weekday_mask == 127:
            return "Täglich"
        if self.weekday_mask == 31:
            return "Montag bis Freitag"
        return ", ".join(WEEKDAY_LABELS[day] for day in self.weekdays)

    @property
    def recurrence_label(self) -> str:
        if self.recurrence_type == "hourly":
            return (
                "Stündlich"
                if self.interval_count == 1
                else f"Alle {self.interval_count} Stunden"
            )
        if self.recurrence_type == "daily":
            return (
                "Täglich"
                if self.interval_count == 1
                else f"Alle {self.interval_count} Tage"
            )
        if self.recurrence_type == "monthly_day":
            label = f"Monatlich am {self.month_day}."
            return self._with_interval(label, "Monate")
        if self.recurrence_type == "monthly_weekday":
            weekday = self.weekdays[0] if self.weekdays else 0
            ordinal = MONTH_WEEK_LABELS.get(self.month_week or 1, "erster")
            label = f"Monatlich: {ordinal} {WEEKDAY_NAMES[weekday]}"
            return self._with_interval(label, "Monate")
        return self._with_interval(self.weekday_label, "Wochen")

    def _with_interval(self, label: str, unit: str) -> str:
        if self.interval_count == 1:
            return label
        return f"{label} · alle {self.interval_count} {unit}"

    @property
    def start_time_label(self) -> str:
        return f"{self.start_minute // 60:02d}:{self.start_minute % 60:02d}"

    @property
    def end_minute(self) -> int:
        return (self.start_minute + self.duration_minutes) % 1440

    @property
    def end_time_label(self) -> str:
        suffix = " (+1 Tag)" if self.start_minute + self.duration_minutes >= 1440 else ""
        return f"{self.end_minute // 60:02d}:{self.end_minute % 60:02d}{suffix}"
