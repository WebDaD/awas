from pathlib import Path

from fastapi.testclient import TestClient

from awas.config import DatabaseSettings, Settings
from awas.main import create_app


def test_dashboard_and_health(tmp_path: Path) -> None:
    settings = Settings(database=DatabaseSettings(url=f"sqlite:///{tmp_path / 'awas.db'}"))

    with TestClient(create_app(settings)) as client:
        dashboard = client.get("/")
        health = client.get("/health")

    assert dashboard.status_code == 200
    assert "Grundsystem betriebsbereit" in dashboard.text
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "version": "0.1.0", "database": "ok"}

    database_path = tmp_path / "awas.db"
    assert database_path.exists()
    assert (tmp_path / "awas.db-wal").exists() or database_path.stat().st_size > 0

