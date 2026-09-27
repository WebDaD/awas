from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from awas.db.base import Base
from awas.models.auth import utc_now


class RecorderSetting(Base):
    __tablename__ = "recorder_settings"

    recorder: Mapped[str] = mapped_column(String(32), primary_key=True)
    arguments: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
