from pathlib import Path

import pytest

from awas.config import ConfigError, load_settings


def test_load_settings_from_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        """
[server]
port = 9090

[database]
url = "sqlite:///test.db"

[recording]
directory = "/tmp/recordings"

[general]
timezone = "UTC"

[security]
session_cookie_secure = true
session_lifetime_hours = 24
""",
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.server.port == 9090
    assert settings.database.url == "sqlite:///test.db"
    assert settings.recording.directory == Path("/tmp/recordings")
    assert settings.general.timezone == "UTC"
    assert settings.security.session_cookie_secure is True
    assert settings.security.session_lifetime_hours == 24


def test_invalid_port_is_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "awas.toml"
    config_path.write_text("[server]\nport = 70000\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="server.port"):
        load_settings(config_path)


def test_invalid_security_limits_are_rejected(tmp_path: Path) -> None:
    config_path = tmp_path / "awas.toml"
    config_path.write_text(
        "[security]\nlogin_max_attempts_per_account = 50\nlogin_max_attempts_per_ip = 10\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="login_max_attempts_per_ip"):
        load_settings(config_path)
