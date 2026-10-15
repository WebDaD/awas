from datetime import datetime, timedelta

import pytest

from awas.web import dependencies
from tests.conftest import form_token, login


@pytest.mark.parametrize(
    ("timezone", "expected_time"),
    [
        ("Europe/Berlin", "15.10.2026 08:35:30 Uhr (Europe/Berlin)"),
        ("Asia/Tokyo", "15.10.2026 15:35:30 Uhr (Asia/Tokyo)"),
        ("UTC", "15.10.2026 06:35:30 Uhr (UTC)"),
    ],
)
def test_status_uses_server_clocks_and_application_timezone(
    client, monkeypatch, timezone, expected_time
):
    clock = {"time": datetime(2026, 10, 15, 6, 35, 30), "monotonic": 183945.0}
    monkeypatch.setattr(dependencies, "utc_now", lambda: clock["time"])
    monkeypatch.setattr(dependencies, "monotonic", lambda: clock["monotonic"])
    client.app.state.started_monotonic = 100.0
    client.app.state.timezone = timezone

    first = client.get("/system/status", headers={"X-Timezone": "Pacific/Honolulu"})

    assert first.status_code == 200
    assert first.headers["cache-control"] == "no-store"
    assert "set-cookie" not in first.headers
    assert first.json() == {"system_time": expected_time, "uptime": "2 Tage, 03:04:05"}
    page = client.get("/login")
    assert f'<span data-system-time>{expected_time}</span>' in page.text
    assert '<span data-uptime>2 Tage, 03:04:05</span>' in page.text
    assert page.text.index("Systemzeit:") < page.text.index("AWAS-Uptime:")

    clock["time"] += timedelta(seconds=5)
    clock["monotonic"] += 5
    updated = client.get("/system/status")
    assert updated.json() == {
        "system_time": expected_time.replace(":30 Uhr", ":35 Uhr"),
        "uptime": "2 Tage, 03:04:10",
    }

    client.app.state.started_monotonic = clock["monotonic"]
    assert client.get("/system/status").json()["uptime"] == "0 Tage, 00:00:00"


def test_server_time_observes_berlin_daylight_saving_transition(client, monkeypatch):
    client.app.state.timezone = "Europe/Berlin"
    monkeypatch.setattr(dependencies, "utc_now", lambda: datetime(2026, 10, 25, 0, 59, 59))
    before = client.get("/system/status").json()["system_time"]
    monkeypatch.setattr(dependencies, "utc_now", lambda: datetime(2026, 10, 25, 1, 0, 0))
    after = client.get("/system/status").json()["system_time"]
    assert before == "25.10.2026 02:59:59 Uhr (Europe/Berlin)"
    assert after == "25.10.2026 02:00:00 Uhr (Europe/Berlin)"


def test_footer_refresh_keeps_the_login_form_valid(client, admin):
    page = client.get("/login")
    token = form_token(page.text)
    for _ in range(2):
        status = client.get("/system/status")
        assert status.status_code == 200
        assert "set-cookie" not in status.headers

    response = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "a-secure-admin-password",
            "csrf_token": token,
            "next_url": "/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/history",
        "/streams",
        "/recordings",
        "/schedules/new",
        "/schedules/recurring/new",
        "/admin/streams/new",
        "/admin/users",
        "/admin/users/new",
        "/admin/recorders",
        "/admin/storage",
        "/account/password",
    ],
)
def test_html_pages_share_the_server_status_footer(client, admin, path):
    assert login(client, "admin", "a-secure-admin-password").status_code == 303
    response = client.get(path)
    assert response.status_code == 200
    assert '<footer class="site-footer" data-live-region="site-footer">' in response.text
    assert "Systemzeit: <span data-system-time>" in response.text
    assert "AWAS-Uptime: <span data-uptime>" in response.text
    assert "data-uptime-seconds" not in response.text
