from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_systemd_allows_orderly_recorder_shutdown() -> None:
    service = (ROOT / "deploy/systemd/awas.service").read_text(encoding="utf-8")

    assert "KillMode=mixed" in service
    assert "TimeoutStopSec=30s" in service


def test_installer_stops_awas_before_database_migration() -> None:
    installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")

    daemon_reload = installer.index("systemctl daemon-reload")
    stop_service = installer.index("systemctl stop awas.service")
    migrate = installer.index('"${APP_ROOT}/.venv/bin/alembic"')
    nginx_test = installer.index("nginx -t")
    restart = installer.index("systemctl restart awas.service nginx.service")
    assert nginx_test < stop_service
    assert daemon_reload < stop_service < migrate < restart


def test_nginx_keeps_http_and_adds_optional_https() -> None:
    http_config = (ROOT / "deploy/nginx/awas.conf").read_text(encoding="utf-8")
    https_config = (ROOT / "deploy/nginx/awas-https.conf").read_text(encoding="utf-8")

    assert "listen 80 default_server;" in http_config
    assert "listen [::]:80 default_server;" in http_config
    assert "return 301" not in http_config
    assert "listen 443 ssl default_server;" in https_config
    assert "listen [::]:443 ssl default_server;" in https_config
    assert "ssl_certificate /etc/awas/tls/fullchain.pem;" in https_config
    assert "ssl_certificate_key /etc/awas/tls/privkey.pem;" in https_config
    assert "ssl_protocols TLSv1.2 TLSv1.3;" in https_config
    assert "Strict-Transport-Security" not in https_config
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in http_config
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in https_config


def test_installer_only_enables_https_when_manual_certificates_exist() -> None:
    installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")
    enable_script = (ROOT / "scripts/enable-https.sh").read_text(encoding="utf-8")

    assert 'TLS_CERTIFICATE="${TLS_DIR}/fullchain.pem"' in installer
    assert 'TLS_PRIVATE_KEY="${TLS_DIR}/privkey.pem"' in installer
    assert 'if [[ -s "${TLS_CERTIFICATE}" && -s "${TLS_PRIVATE_KEY}" ]]' in installer
    assert "awas-https.conf" in installer
    assert "systemctl reload nginx.service" in enable_script
    assert "HTTP remains enabled on port 80" in enable_script


def test_installer_preserves_existing_nginx_configuration() -> None:
    installer = (ROOT / "scripts/install.sh").read_text(encoding="utf-8")

    assert 'if [[ ! -f "${NGINX_HTTP_CONFIG}" ]]' in installer
    assert 'if [[ ! -f "${NGINX_HTTPS_CONFIG}" ]]' in installer
    assert '"${APP_SOURCE}/deploy/nginx/awas.conf" "${NGINX_HTTP_CONFIG}"' in installer
    assert (
        '"${APP_SOURCE}/deploy/nginx/awas-https.conf" "${NGINX_HTTPS_CONFIG}"'
        in installer
    )
