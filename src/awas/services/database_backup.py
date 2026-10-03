from __future__ import annotations

import os
import secrets
import sqlite3
import stat
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.engine import make_url

CURRENT_DATABASE_REVISION = "0021"
MAX_DATABASE_IMPORT_BYTES = 256 * 1024 * 1024
SQLITE_HEADER = b"SQLite format 3\x00"
REQUIRED_TABLES = frozenset(
    {
        "alembic_version",
        "audit_log",
        "login_attempts",
        "recorder_settings",
        "recording_schedules",
        "recording_files",
        "recordings",
        "recurring_schedules",
        "retention_policy",
        "sessions",
        "storage_configuration",
        "streams",
        "users",
    }
)


class DatabaseBackupError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DatabaseRollback:
    path: Path
    mode: int


def sqlite_database_path(database_url: str) -> Path:
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        raise DatabaseBackupError(
            "Datenbankexport und -import benötigen eine dateibasierte SQLite-Datenbank."
        )
    return Path(url.database).expanduser().resolve()


class DatabaseBackupManager:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()

    def create_export(self) -> Path:
        file_descriptor, raw_path = tempfile.mkstemp(
            prefix="awas-database-export-",
            suffix=".db",
        )
        os.close(file_descriptor)
        export_path = Path(raw_path)
        try:
            _backup_database(self.database_path, export_path)
            self.validate_database(export_path)
            export_path.chmod(0o600)
            return export_path
        except Exception:
            export_path.unlink(missing_ok=True)
            raise

    def new_import_path(self) -> Path:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        file_descriptor, raw_path = tempfile.mkstemp(
            prefix=".awas-database-import-",
            suffix=".db",
            dir=self.database_path.parent,
        )
        os.close(file_descriptor)
        import_path = Path(raw_path)
        import_path.chmod(0o600)
        return import_path

    def validate_database(
        self,
        candidate: Path,
        *,
        required_admin_username: str | None = None,
    ) -> None:
        try:
            if not candidate.is_file() or candidate.stat().st_size < len(SQLITE_HEADER):
                raise DatabaseBackupError("Die ausgewählte Datei ist keine SQLite-Datenbank.")
            with candidate.open("rb") as source:
                if source.read(len(SQLITE_HEADER)) != SQLITE_HEADER:
                    raise DatabaseBackupError("Die ausgewählte Datei ist keine SQLite-Datenbank.")

            with closing(_open_readonly(candidate)) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
                if missing := sorted(REQUIRED_TABLES - tables):
                    raise DatabaseBackupError(
                        "Die Datei ist keine vollständige AWAS-Datenbank. "
                        f"Fehlende Tabellen: {', '.join(missing)}."
                    )

                revision_row = connection.execute(
                    "SELECT version_num FROM alembic_version LIMIT 1"
                ).fetchone()
                revision = revision_row[0] if revision_row else None
                if revision != CURRENT_DATABASE_REVISION:
                    raise DatabaseBackupError(
                        "Die Datenbankversion ist nicht kompatibel. "
                        f"Erwartet wird {CURRENT_DATABASE_REVISION}, gefunden wurde "
                        f"{revision or 'keine Versionsangabe'}."
                    )

                integrity_rows = connection.execute("PRAGMA integrity_check").fetchall()
                if integrity_rows != [("ok",)]:
                    raise DatabaseBackupError("Die SQLite-Integritätsprüfung ist fehlgeschlagen.")
                if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise DatabaseBackupError(
                        "Die Datenbank enthält ungültige Verknüpfungen und wurde abgelehnt."
                    )

                if required_admin_username is not None:
                    admin = connection.execute(
                        "SELECT 1 FROM users "
                        "WHERE username = ? AND role = 'admin' AND is_active = 1 LIMIT 1",
                        (required_admin_username,),
                    ).fetchone()
                    if admin is None:
                        raise DatabaseBackupError(
                            "Die Sicherung enthält für das aktuell angemeldete Konto kein "
                            "aktives Administratorkonto."
                        )
        except DatabaseBackupError:
            raise
        except (OSError, sqlite3.DatabaseError) as exc:
            raise DatabaseBackupError(
                "Die Datenbankdatei konnte nicht vollständig geprüft werden."
            ) from exc

    def install_import(self, candidate: Path) -> DatabaseRollback:
        self.validate_database(candidate)
        try:
            current_stat = self.database_path.stat()
        except OSError as exc:
            raise DatabaseBackupError("Die aktuelle AWAS-Datenbank ist nicht verfügbar.") from exc
        mode = stat.S_IMODE(current_stat.st_mode)
        rollback = self.database_path.parent / (
            f".awas-database-before-import-{secrets.token_hex(8)}.db"
        )
        replaced = False
        try:
            _backup_database(self.database_path, rollback)
            rollback.chmod(mode)
            _checkpoint_database(self.database_path)
            _remove_sidecars(self.database_path)
            candidate.chmod(mode)
            os.replace(candidate, self.database_path)
            replaced = True
            _remove_sidecars(self.database_path)
            _sync_directory(self.database_path.parent)
            self.validate_database(self.database_path)
            return DatabaseRollback(path=rollback, mode=mode)
        except Exception as exc:
            if replaced and rollback.exists():
                try:
                    _remove_sidecars(self.database_path)
                    os.replace(rollback, self.database_path)
                    self.database_path.chmod(mode)
                    _sync_directory(self.database_path.parent)
                except OSError as restore_exc:
                    raise DatabaseBackupError(
                        "Der Datenbankimport und die automatische Wiederherstellung sind "
                        "fehlgeschlagen."
                    ) from restore_exc
            rollback.unlink(missing_ok=True)
            if isinstance(exc, DatabaseBackupError):
                raise
            raise DatabaseBackupError("Die Datenbank konnte nicht importiert werden.") from exc

    def restore_import(self, rollback: DatabaseRollback) -> None:
        try:
            _remove_sidecars(self.database_path)
            os.replace(rollback.path, self.database_path)
            self.database_path.chmod(rollback.mode)
            _sync_directory(self.database_path.parent)
            self.validate_database(self.database_path)
        except (OSError, DatabaseBackupError) as exc:
            raise DatabaseBackupError(
                "Die vorherige Datenbank konnte nicht wiederhergestellt werden."
            ) from exc

    @staticmethod
    def finish_import(rollback: DatabaseRollback) -> None:
        rollback.path.unlink(missing_ok=True)


def _open_readonly(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(
        f"{path.resolve().as_uri()}?mode=ro",
        uri=True,
        timeout=30,
    )


def _backup_database(source_path: Path, destination_path: Path) -> None:
    destination_path.unlink(missing_ok=True)
    try:
        with (
            closing(_open_readonly(source_path)) as source,
            closing(sqlite3.connect(destination_path, timeout=30)) as destination,
        ):
            source.execute("PRAGMA busy_timeout=30000")
            source.backup(destination)
            destination.commit()
    except (OSError, sqlite3.DatabaseError) as exc:
        destination_path.unlink(missing_ok=True)
        raise DatabaseBackupError("Die Datenbanksicherung konnte nicht erstellt werden.") from exc


def _checkpoint_database(path: Path) -> None:
    try:
        with closing(sqlite3.connect(path, timeout=30)) as connection:
            connection.execute("PRAGMA busy_timeout=30000")
            result = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if result is not None and result[0] != 0:
                raise DatabaseBackupError(
                    "Die aktuelle Datenbank ist noch in Benutzung und konnte nicht "
                    "importiert werden."
                )
    except DatabaseBackupError:
        raise
    except sqlite3.DatabaseError as exc:
        raise DatabaseBackupError(
            "Die aktuelle Datenbank konnte nicht für den Import vorbereitet werden."
        ) from exc


def _remove_sidecars(path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


def _sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
