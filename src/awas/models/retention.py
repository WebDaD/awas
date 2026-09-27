from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from awas.db.base import Base
from awas.models.auth import utc_now

if TYPE_CHECKING:
    from awas.models.auth import User


class RetentionPolicy(Base):
    __tablename__ = "retention_policy"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_retention_policy_singleton"),
        CheckConstraint(
            "retention_days BETWEEN 1 AND 3650",
            name="ck_retention_policy_days",
        ),
        CheckConstraint(
            "last_run_mode IS NULL OR last_run_mode IN ('automatic', 'manual')",
            name="ck_retention_policy_run_mode",
        ),
        CheckConstraint(
            "last_deleted_count >= 0",
            name="ck_retention_policy_deleted_count",
        ),
        CheckConstraint(
            "last_freed_bytes >= 0",
            name="ck_retention_policy_freed_bytes",
        ),
        CheckConstraint(
            "last_failed_count >= 0",
            name="ck_retention_policy_failed_count",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    retention_days: Mapped[int] = mapped_column(Integer, default=90)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_mode: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_deleted_count: Mapped[int] = mapped_column(Integer, default=0)
    last_freed_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    last_failed_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(512), nullable=True)

    updated_by: Mapped[User | None] = relationship()
