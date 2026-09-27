from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from awas.db.base import Base
from awas.models.auth import utc_now

if TYPE_CHECKING:
    from awas.models.auth import User


class StorageConfiguration(Base):
    __tablename__ = "storage_configuration"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    recording_directory: Mapped[str] = mapped_column(String(4096))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now, onupdate=utc_now)
    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    updated_by: Mapped[User | None] = relationship()
