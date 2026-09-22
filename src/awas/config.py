from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_CONFIG_PATH = Path("/etc/awas/awas.toml")


class ConfigError(ValueError):
    """Raised when the AWAS configuration is invalid."""


@dataclass(frozen=True, slots=True)
class ServerSettings:
    host: str = "127.0.0.1"
    port: int = 8080
    proxy_headers: bool = True
    forwarded_allow_ips: str = "127.0.0.1"


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    url: str = "sqlite:////var/lib/awas/awas.db"


@dataclass(frozen=True, slots=True)
class RecordingSettings:
    directory: Path = Path("/srv/awas/recordings")


@dataclass(frozen=True, slots=True)
class GeneralSettings:
    timezone: str = "Europe/Berlin"


@dataclass(frozen=True, slots=True)
class Settings:
    server: ServerSettings = ServerSettings()
    database: DatabaseSettings = DatabaseSettings()
    recording: RecordingSettings = RecordingSettings()
    general: GeneralSettings = GeneralSettings()


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ConfigError(f"Configuration section [{name}] must be a table")
    return value


def load_settings(path: Path | None = None) -> Settings:
    config_path = path or Path(os.environ.get("AWAS_CONFIG", DEFAULT_CONFIG_PATH))
    data: dict[str, Any] = {}
    if config_path.exists():
        try:
            with config_path.open("rb") as file_handle:
                data = tomllib.load(file_handle)
        except tomllib.TOMLDecodeError as exc:
            raise ConfigError(f"Invalid TOML in {config_path}: {exc}") from exc

    server = _section(data, "server")
    database = _section(data, "database")
    recording = _section(data, "recording")
    general = _section(data, "general")

    port = int(server.get("port", 8080))
    if not 1 <= port <= 65535:
        raise ConfigError("server.port must be between 1 and 65535")

    timezone = str(general.get("timezone", "Europe/Berlin"))
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ConfigError(f"Unknown timezone: {timezone}") from exc

    database_url = str(database.get("url", "sqlite:////var/lib/awas/awas.db"))
    if not database_url.startswith("sqlite:"):
        raise ConfigError("Milestone 0.1 supports SQLite database URLs only")

    return Settings(
        server=ServerSettings(
            host=str(server.get("host", "127.0.0.1")),
            port=port,
            proxy_headers=bool(server.get("proxy_headers", True)),
            forwarded_allow_ips=str(server.get("forwarded_allow_ips", "127.0.0.1")),
        ),
        database=DatabaseSettings(url=database_url),
        recording=RecordingSettings(
            directory=Path(recording.get("directory", "/srv/awas/recordings"))
        ),
        general=GeneralSettings(timezone=timezone),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()

