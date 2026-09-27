from pathlib import Path

from sqlalchemy import select

from awas.auth.passwords import verify_password
from awas.cli import create_admin_command
from awas.config import get_settings
from awas.db.base import Base
from awas.db.session import create_database_engine, create_session_factory
from awas.models import AuditLog, User


def test_create_admin_command(tmp_path: Path, monkeypatch, capsys) -> None:
    database_path = tmp_path / "awas.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    engine = create_database_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    passwords = iter(["admin", "admin"])
    monkeypatch.setattr("awas.cli.getpass.getpass", lambda _: next(passwords))

    try:
        result = create_admin_command("admin", "AWAS Admin")
        settings = get_settings()
        query_engine = create_database_engine(settings.database.url)
        with create_session_factory(query_engine)() as db:
            user = db.scalar(select(User).where(User.username == "admin"))
            assert user is not None
            assert user.role == "admin"
            assert user.must_change_password is False
            assert verify_password("admin", user.password_hash)
            assert db.scalar(select(AuditLog).where(AuditLog.action == "user.created")) is not None
        query_engine.dispose()
    finally:
        get_settings.cache_clear()

    assert result == 0
    assert "Administrator 'admin' wurde angelegt." in capsys.readouterr().out
