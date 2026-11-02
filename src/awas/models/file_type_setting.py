from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from awas.db.base import Base
from awas.models.auth import utc_now


class FileTypeSetting(Base):
    __tablename__ = "file_type_settings"
    __table_args__ = (CheckConstraint("id = 1", name="ck_file_type_settings_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    file_types: Mapped[str] = mapped_column(String(2048))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
