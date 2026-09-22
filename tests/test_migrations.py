from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from awas.config import get_settings


def test_migrations_reach_head(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "migrated.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()

    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "head")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()

    assert revision == "0001"
    assert journal_mode == "wal"
    get_settings.cache_clear()

