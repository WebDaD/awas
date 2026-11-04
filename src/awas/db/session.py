from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker


def _local_datetime(value: str | None, timezone: str) -> str:
    if value is None:
        return ""
    instant = datetime.fromisoformat(value)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    return instant.astimezone(ZoneInfo(timezone)).strftime("%d.%m.%Y %H:%M")


def _search_text(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def create_database_engine(database_url: str) -> Engine:
    connect_args = (
        {"check_same_thread": False, "timeout": 30} if database_url.startswith("sqlite:") else {}
    )
    engine = create_engine(database_url, connect_args=connect_args, pool_pre_ping=True)

    if database_url.startswith("sqlite:"):

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi_connection: object, _: object) -> None:
            dbapi_connection.create_function(  # type: ignore[attr-defined]
                "awas_local_datetime", 2, _local_datetime, deterministic=True
            )
            dbapi_connection.create_function(  # type: ignore[attr-defined]
                "awas_search_text", 1, _search_text, deterministic=True
            )
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

    return engine


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
