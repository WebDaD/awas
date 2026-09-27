from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from awas.config import DatabaseSettings, RecordingSettings, SecuritySettings, Settings
from awas.db.base import Base
from awas.main import create_app
from awas.services.auth import create_user


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    settings = Settings(
        database=DatabaseSettings(url=f"sqlite:///{tmp_path / 'awas.db'}"),
        recording=RecordingSettings(directory=tmp_path / "recordings"),
        security=SecuritySettings(
            login_max_attempts_per_account=3,
            login_max_attempts_per_ip=10,
        ),
    )
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app: FastAPI):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def admin(app: FastAPI):
    with app.state.session_factory() as db:
        return create_user(
            db,
            username="admin",
            display_name="AWAS Admin",
            password="a-secure-admin-password",
            password_confirmation="a-secure-admin-password",
            role="admin",
            must_change_password=False,
        )


def form_token(html: str, field_name: str = "csrf_token") -> str:
    match = re.search(rf'name="{field_name}" value="([^"]+)"', html)
    assert match is not None, f"No {field_name} token found"
    return match.group(1)


def login(client: TestClient, username: str, password: str):
    login_page = client.get("/login")
    return client.post(
        "/login",
        data={
            "username": username,
            "password": password,
            "csrf_token": form_token(login_page.text),
            "next_url": "/",
        },
        follow_redirects=False,
    )
