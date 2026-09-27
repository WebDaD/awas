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
class SecuritySettings:
    session_cookie_secure: bool = False
    session_lifetime_hours: int = 12
    login_window_minutes: int = 15
    login_max_attempts_per_account: int = 5
    login_max_attempts_per_ip: int = 20


@dataclass(frozen=True, slots=True)
class Settings:
    server: ServerSettings = ServerSettings()
    database: DatabaseSettings = DatabaseSettings()
    recording: RecordingSettings = RecordingSettings()
    general: GeneralSettings = GeneralSettings()
    security: SecuritySettings = SecuritySettings()


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
    security = _section(data, "security")

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
        raise ConfigError("AWAS currently supports SQLite database URLs only")

    session_lifetime_hours = int(security.get("session_lifetime_hours", 12))
    login_window_minutes = int(security.get("login_window_minutes", 15))
    account_attempts = int(security.get("login_max_attempts_per_account", 5))
    ip_attempts = int(security.get("login_max_attempts_per_ip", 20))
    if not 1 <= session_lifetime_hours <= 168:
        raise ConfigError("security.session_lifetime_hours must be between 1 and 168")
    if not 1 <= login_window_minutes <= 60:
        raise ConfigError("security.login_window_minutes must be between 1 and 60")
    if not 1 <= account_attempts <= 100:
        raise ConfigError("security.login_max_attempts_per_account must be between 1 and 100")
    if not account_attempts <= ip_attempts <= 1000:
        raise ConfigError(
            "security.login_max_attempts_per_ip must be at least the account limit and at most 1000"
        )

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
        security=SecuritySettings(
            session_cookie_secure=bool(security.get("session_cookie_secure", False)),
            session_lifetime_hours=session_lifetime_hours,
            login_window_minutes=login_window_minutes,
            login_max_attempts_per_account=account_attempts,
            login_max_attempts_per_ip=ip_attempts,
        ),
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return load_settings()
