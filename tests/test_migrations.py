from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from awas.config import get_settings
from awas.services.recorders import RECORDER_BY_KEY


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
    command.check(alembic_config)

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }
        retention_policy = connection.execute(
            text(
                "SELECT enabled, retention_days, last_deleted_count, "
                "last_freed_bytes, last_failed_count FROM retention_policy WHERE id = 1"
            )
        ).one()
        recording_indexes = {
            row[1] for row in connection.execute(text("PRAGMA index_list('recordings')"))
        }
        stream_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info('streams')"))
        }
        user_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info('users')"))
        }
        user_indexes = {
            row[1] for row in connection.execute(text("PRAGMA index_list('users')"))
        }
        recording_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info('recordings')"))
        }
        recorder_count = connection.execute(
            text("SELECT COUNT(*) FROM recorder_settings")
        ).scalar_one()

    assert revision == "0017"
    assert journal_mode == "wal"
    assert {
        "users",
        "sessions",
        "login_attempts",
        "audit_log",
        "streams",
        "recordings",
        "recording_schedules",
        "recurring_schedules",
        "retention_policy",
        "recorder_settings",
        "storage_configuration",
    } <= tables
    assert "recorder_tool_settings" not in tables
    assert recorder_count == 8
    assert tuple(retention_policy) == (0, 90, 0, 0, 0)
    assert "ix_recordings_status_ended_at" in recording_indexes
    assert "is_active" not in stream_columns
    assert "storage_directory" in recording_columns
    assert "deleted_at" in user_columns
    assert "ix_users_deleted_at" in user_indexes
    get_settings.cache_clear()


def test_stream_migration_preserves_existing_entries(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "upgrade.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0003")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO stations (name, stream_url, is_active) "
                "VALUES ('Existing Stream', 'https://radio.example/live', 1)"
            )
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT name, stream_url, preferred_recorder, "
                "preferred_file_type FROM streams"
            )
        ).one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert tuple(row) == (
        "Existing Stream",
        "https://radio.example/live",
        "streamripper",
        "ts",
    )
    assert revision == "0017"
    engine.dispose()
    get_settings.cache_clear()


def test_recorder_rename_preserves_parameters(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "recorder-rename.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0012")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE recorder_tool_settings SET arguments = :arguments "
                "WHERE recorder = 'ffmpeg'"
            ),
            {"arguments": "-i {url} -c copy {output}"},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        arguments = connection.execute(
            text("SELECT arguments FROM recorder_settings WHERE recorder = 'ffmpeg'")
        ).scalar_one()
        tables = {
            row[0]
            for row in connection.execute(
                text("SELECT name FROM sqlite_master WHERE type = 'table'")
            )
        }

    assert arguments == "-i {url} -c copy {output}"
    assert "recorder_settings" in tables
    assert "recorder_tool_settings" not in tables
    engine.dispose()
    get_settings.cache_clear()


def test_recorder_cleanup_updates_defaults_and_active_yt_dlp_configuration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "recorder-cleanup.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0015")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO streams "
                "(name, stream_url, preferred_recorder, preferred_file_type) VALUES "
                "('Entfernter Rekorder', 'https://radio.example/removed', "
                "'yt-dlp', 'ts')"
            )
        )
        stream_id = connection.execute(
            text("SELECT id FROM streams WHERE name = 'Entfernter Rekorder'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recording_schedules "
                "(stream_id, title, file_name_base, recorder, file_type, starts_at, "
                "ends_at, status, is_hidden) VALUES "
                "(:stream_id, 'Noch geplant', 'noch-geplant', 'yt-dlp-ffmpeg', 'ts', "
                "'2026-10-01 08:00:00', '2026-10-01 09:00:00', 'scheduled', 0), "
                "(:stream_id, 'Historisch', 'historisch', 'yt-dlp', 'ts', "
                "'2026-09-01 08:00:00', '2026-09-01 09:00:00', 'completed', 0)"
            ),
            {"stream_id": stream_id},
        )
        connection.execute(
            text(
                "INSERT INTO recurring_schedules "
                "(stream_id, title, file_name_base, recorder, file_type, "
                "recurrence_type, interval_count, weekday_mask, start_minute, "
                "duration_minutes, valid_from, is_active, is_hidden) VALUES "
                "(:stream_id, 'Wiederholung', 'wiederholung', 'yt-dlp', 'ts', "
                "'weekly', 1, 1, 480, 60, '2026-10-01', 1, 0)"
            ),
            {"stream_id": stream_id},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
        recorder_names = set(
            connection.execute(text("SELECT recorder FROM recorder_settings")).scalars()
        )
        ffmpeg_arguments = connection.execute(
            text("SELECT arguments FROM recorder_settings WHERE recorder = 'ffmpeg'")
        ).scalar_one()
        preferred_recorder = connection.execute(
            text("SELECT preferred_recorder FROM streams")
        ).scalar_one()
        schedules = dict(
            connection.execute(
                text("SELECT title, recorder FROM recording_schedules ORDER BY id")
            ).all()
        )
        recurring_recorder = connection.execute(
            text("SELECT recorder FROM recurring_schedules")
        ).scalar_one()

    assert revision == "0017"
    assert "yt-dlp" not in recorder_names
    assert "yt-dlp-ffmpeg" not in recorder_names
    assert "-map" not in ffmpeg_arguments
    assert "-sn -dn -c copy" in ffmpeg_arguments
    assert preferred_recorder == "ffmpeg"
    assert schedules == {"Noch geplant": "ffmpeg", "Historisch": "yt-dlp"}
    assert recurring_recorder == "ffmpeg"
    engine.dispose()
    get_settings.cache_clear()


def test_hls_reconnect_migration_updates_unmodified_defaults(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "hls-reconnect.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0016")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        old_arguments = dict(
            connection.execute(
                text(
                    "SELECT recorder, arguments FROM recorder_settings "
                    "WHERE recorder IN ('ffmpeg', 'ffmpeg-all')"
                )
            ).all()
        )
    engine.dispose()

    assert set(old_arguments) == {"ffmpeg", "ffmpeg-all"}
    assert all("-reconnect_at_eof 1" in value for value in old_arguments.values())

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        new_arguments = dict(
            connection.execute(
                text(
                    "SELECT recorder, arguments FROM recorder_settings "
                    "WHERE recorder IN ('ffmpeg', 'ffmpeg-all')"
                )
            ).all()
        )
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert revision == "0017"
    assert new_arguments == {
        recorder: RECORDER_BY_KEY[recorder].default_arguments
        for recorder in ("ffmpeg", "ffmpeg-all")
    }
    assert all("-reconnect_at_eof" not in value for value in new_arguments.values())
    engine.dispose()
    get_settings.cache_clear()


def test_hls_reconnect_migration_preserves_custom_arguments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "custom-hls-reconnect.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0016")

    custom_arguments = "-i {url} -c copy {output}"
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE recorder_settings SET arguments = :arguments "
                "WHERE recorder = 'ffmpeg'"
            ),
            {"arguments": custom_arguments},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        arguments = dict(
            connection.execute(
                text(
                    "SELECT recorder, arguments FROM recorder_settings "
                    "WHERE recorder IN ('ffmpeg', 'ffmpeg-all')"
                )
            ).all()
        )

    assert arguments["ffmpeg"] == custom_arguments
    assert arguments["ffmpeg-all"] == RECORDER_BY_KEY["ffmpeg-all"].default_arguments
    engine.dispose()
    get_settings.cache_clear()


def test_deleted_user_migration_preserves_existing_users(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "deleted-users-upgrade.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0013")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (username, display_name, password_hash, role, is_active) "
                "VALUES ('existing', 'Existing User', 'hash', 'user', 1)"
            )
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        user = connection.execute(
            text("SELECT username, display_name, is_active, deleted_at FROM users")
        ).one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        indexes = {
            row[1] for row in connection.execute(text("PRAGMA index_list('users')"))
        }

    assert tuple(user) == ("existing", "Existing User", 1, None)
    assert revision == "0017"
    assert "ix_users_deleted_at" in indexes
    engine.dispose()
    get_settings.cache_clear()


def test_discarded_schedule_migration_hides_existing_entries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "discarded-schedules-upgrade.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0014")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO streams "
                "(name, stream_url, preferred_recorder, preferred_file_type) VALUES "
                "('Historienstream', 'https://radio.example/history', 'ffmpeg', 'mp3')"
            )
        )
        stream_id = connection.execute(
            text("SELECT id FROM streams WHERE name = 'Historienstream'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recording_schedules "
                "(stream_id, title, file_name_base, recorder, file_type, starts_at, "
                "ends_at, status, is_hidden) VALUES "
                "(:stream_id, 'Verworfen', 'verworfen', 'ffmpeg', 'mp3', "
                "'2026-09-27 08:00:00', '2026-09-27 09:00:00', 'cancelled', 0), "
                "(:stream_id, 'Abgeschlossen', 'abgeschlossen', 'ffmpeg', 'mp3', "
                "'2026-09-27 09:00:00', '2026-09-27 10:00:00', 'completed', 0)"
            ),
            {"stream_id": stream_id},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        visibility = dict(
            connection.execute(
                text("SELECT title, is_hidden FROM recording_schedules ORDER BY id")
            ).all()
        )
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert visibility == {"Verworfen": 1, "Abgeschlossen": 0}
    assert revision == "0017"
    engine.dispose()
    get_settings.cache_clear()


def test_schedule_migration_preserves_existing_recordings(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "recording-upgrade.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0004")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO streams (name, stream_url, is_active) "
                "VALUES ('Existing Stream', 'https://radio.example/live', 1)"
            )
        )
        stream_id = connection.execute(
            text("SELECT id FROM streams WHERE name = 'Existing Stream'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recordings "
                "(stream_id, stream_name, file_name, status, started_at, ended_at, "
                "file_size_bytes) VALUES "
                "(:stream_id, 'Existing Stream', 'existing.mka', 'completed', "
                "'2026-09-23 08:00:00', '2026-09-23 09:00:00', 12345)"
            ),
            {"stream_id": stream_id},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT stream_name, file_name, status, file_size_bytes, schedule_id, "
                "recorder, file_type, file_deleted_at, storage_directory FROM recordings"
            )
        ).one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert tuple(row) == (
        "Existing Stream",
        "existing.mka",
        "completed",
        12345,
        None,
        "ffmpeg",
        "mka",
        None,
        None,
    )
    assert revision == "0017"
    engine.dispose()
    get_settings.cache_clear()


def test_recurring_migration_preserves_one_time_schedules(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / "recurring-upgrade.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0005")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO streams (name, stream_url, is_active) "
                "VALUES ('Existing Stream', 'https://radio.example/live', 1)"
            )
        )
        stream_id = connection.execute(
            text("SELECT id FROM streams WHERE name = 'Existing Stream'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recording_schedules "
                "(stream_id, title, starts_at, ends_at, status) VALUES "
                "(:stream_id, 'One-time Show', '2026-10-01 08:00:00', "
                "'2026-10-01 09:00:00', 'scheduled')"
            ),
            {"stream_id": stream_id},
        )
        schedule_id = connection.execute(
            text("SELECT id FROM recording_schedules WHERE title = 'One-time Show'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recordings "
                "(stream_id, stream_name, file_name, status, started_at, ended_at, "
                "file_size_bytes, schedule_id) VALUES "
                "(:stream_id, 'Existing Stream', 'scheduled-existing.mka', 'completed', "
                "'2026-10-01 08:00:00', '2026-10-01 09:00:00', 12345, :schedule_id)"
            ),
            {"stream_id": stream_id, "schedule_id": schedule_id},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT title, status, recurrence_id, occurrence_date, recorder, file_type, "
                "is_hidden "
                "FROM recording_schedules"
            )
        ).one()
        recording_schedule_id = connection.execute(
            text("SELECT schedule_id FROM recordings WHERE file_name = 'scheduled-existing.mka'")
        ).scalar_one()
        revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

    assert tuple(row) == ("One-time Show", "scheduled", None, None, "ffmpeg", "ts", 0)
    assert recording_schedule_id == schedule_id
    assert revision == "0017"
    engine.dispose()
    get_settings.cache_clear()


def test_recorder_migration_preserves_existing_recurrence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "recorder-upgrade.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0007")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO streams (name, stream_url, is_active) "
                "VALUES ('Series Stream', 'https://radio.example/series', 1)"
            )
        )
        stream_id = connection.execute(
            text("SELECT id FROM streams WHERE name = 'Series Stream'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recurring_schedules "
                "(stream_id, title, weekday_mask, start_minute, duration_minutes, "
                "valid_from, valid_until, is_active) VALUES "
                "(:stream_id, 'Existing Series', 31, 480, 60, "
                "'2026-09-01', '2026-12-31', 1)"
            ),
            {"stream_id": stream_id},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT id, title, weekday_mask, is_active, recorder, file_type, "
                "recurrence_type, interval_count, month_day, month_week, is_hidden "
                "FROM recurring_schedules"
            )
        ).one()

    assert tuple(row) == (
        1,
        "Existing Series",
        31,
        1,
        "ffmpeg",
        "ts",
        "weekly",
        1,
        None,
        None,
        0,
    )
    recurrence_id = row.id
    engine.dispose()

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        for hour in (8, 9):
            connection.execute(
                text(
                    "INSERT INTO recording_schedules "
                    "(stream_id, title, starts_at, ends_at, status, recurrence_id, "
                    "occurrence_date) VALUES "
                    "(:stream_id, 'Hourly Series', :starts_at, :ends_at, 'scheduled', "
                    ":recurrence_id, '2026-10-01')"
                ),
                {
                    "stream_id": stream_id,
                    "recurrence_id": recurrence_id,
                    "starts_at": f"2026-10-01 {hour:02d}:00:00",
                    "ends_at": f"2026-10-01 {hour:02d}:30:00",
                },
            )
    engine.dispose()
    get_settings.cache_clear()


def test_stream_history_migration_preserves_links_and_detaches_deleted_stream(
    tmp_path: Path,
    monkeypatch,
) -> None:
    database_path = tmp_path / "stream-history-upgrade.db"
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        f'[database]\nurl = "sqlite:///{database_path}"\n[general]\ntimezone = "UTC"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("AWAS_CONFIG", str(config_path))
    get_settings.cache_clear()
    alembic_config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(alembic_config, "0009")

    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO streams (name, stream_url, is_active) "
                "VALUES ('Antenne Münster', 'https://radio.example/live', 1)"
            )
        )
        stream_id = connection.execute(
            text("SELECT id FROM streams WHERE name = 'Antenne Münster'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recurring_schedules "
                "(stream_id, title, weekday_mask, start_minute, duration_minutes, "
                "valid_from, is_active, is_hidden) VALUES "
                "(:stream_id, 'Morgensendung', 1, 480, 60, '2026-09-01', 0, 1)"
            ),
            {"stream_id": stream_id},
        )
        recurrence_id = connection.execute(
            text("SELECT id FROM recurring_schedules WHERE title = 'Morgensendung'")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recording_schedules "
                "(stream_id, title, starts_at, ends_at, status, recurrence_id, "
                "occurrence_date, is_hidden) VALUES "
                "(:stream_id, 'Morgensendung am Montag', '2026-09-21 08:00:00', "
                "'2026-09-21 09:00:00', 'completed', :recurrence_id, '2026-09-21', 1)"
            ),
            {"stream_id": stream_id, "recurrence_id": recurrence_id},
        )
        schedule_id = connection.execute(
            text(
                "SELECT id FROM recording_schedules "
                "WHERE title = 'Morgensendung am Montag'"
            )
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO recordings "
                "(stream_id, stream_name, file_name, status, started_at, ended_at, "
                "schedule_id) VALUES "
                "(:stream_id, 'Antenne Münster', 'antenne-history.mp3', 'completed', "
                "'2026-09-21 08:00:00', '2026-09-21 09:00:00', :schedule_id)"
            ),
            {"stream_id": stream_id, "schedule_id": schedule_id},
        )
    engine.dispose()

    command.upgrade(alembic_config, "head")
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        nullable_columns = {
            table: next(
                row[3]
                for row in connection.execute(text(f"PRAGMA table_info('{table}')"))
                if row[1] == "stream_id"
            )
            for table in ("recordings", "recording_schedules", "recurring_schedules")
        }
        delete_actions = {
            table: next(
                row[6]
                for row in connection.execute(text(f"PRAGMA foreign_key_list('{table}')"))
                if row[3] == "stream_id"
            )
            for table in ("recordings", "recording_schedules", "recurring_schedules")
        }
        connection.execute(text("DELETE FROM streams WHERE id = :id"), {"id": stream_id})
        recording_row = connection.execute(
            text("SELECT stream_id, schedule_id FROM recordings")
        ).one()
        schedule_row = connection.execute(
            text("SELECT stream_id, recurrence_id FROM recording_schedules")
        ).one()
        recurrence_row = connection.execute(
            text("SELECT stream_id FROM recurring_schedules")
        ).one()
        foreign_key_errors = connection.execute(text("PRAGMA foreign_key_check")).all()
        revision = connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()

    assert nullable_columns == {
        "recordings": 0,
        "recording_schedules": 0,
        "recurring_schedules": 0,
    }
    assert delete_actions == {
        "recordings": "SET NULL",
        "recording_schedules": "SET NULL",
        "recurring_schedules": "SET NULL",
    }
    assert tuple(recording_row) == (None, schedule_id)
    assert tuple(schedule_row) == (None, recurrence_id)
    assert tuple(recurrence_row) == (None,)
    assert foreign_key_errors == []
    assert revision == "0017"
    engine.dispose()
    get_settings.cache_clear()
