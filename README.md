# AWAS 3

AWAS 3 is a from-scratch rewrite of the AWAS stream recorder. The `v3` branch is
independent of the legacy Node.js application on `master`.

Milestone 0.1 provides the production-shaped foundation:

- Python 3.12 or newer, FastAPI and Jinja2
- SQLAlchemy 2 and Alembic
- SQLite in WAL mode
- responsive start page and JSON health endpoint
- native systemd service and nginx reverse proxy
- installer for 64-bit Raspberry Pi OS/Debian and Ubuntu

Recording, authentication and scheduling are intentionally not part of this
first milestone.

## Supported base systems

- Raspberry Pi OS 64-bit based on Debian 13 (Pi 4 and newer)
- Debian 13 on `arm64` or `amd64`
- Ubuntu Server 24.04 LTS and 26.04 LTS on `arm64` or `amd64`

The application contains no Raspberry-Pi-specific code.

## Development

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
cp deploy/awas.example.toml awas.toml
AWAS_CONFIG="$PWD/awas.toml" alembic upgrade head
AWAS_CONFIG="$PWD/awas.toml" awas
```

Open <http://127.0.0.1:8080>. The health endpoint is available at
<http://127.0.0.1:8080/health>.

Run the checks with:

```bash
ruff check .
pytest
```

## Raspberry Pi / server installation

Clone or download the `v3` branch on the target system and run:

```bash
sudo ./scripts/install.sh
```

The installer creates the non-login system user `awas-service` and uses these paths:

| Purpose | Path |
|---|---|
| application and virtual environment | `/opt/awas` |
| configuration | `/etc/awas/awas.toml` |
| SQLite database | `/var/lib/awas/awas.db` |
| logs | `/var/log/awas` / system journal |
| recordings | `/srv/awas/recordings` |

After installation, open `http://IP-ADDRESS-OF-THE-SERVER/`.

Useful checks:

```bash
sudo systemctl status awas
sudo journalctl -u awas -n 100 --no-pager
curl http://127.0.0.1:8080/health
```

Milestone 0.1 deliberately exposes nginx through HTTP. HTTPS with nginx and
Let's Encrypt will be added as a separate installer mode without changing the
FastAPI application.

## Configuration

AWAS reads `/etc/awas/awas.toml` by default. Set `AWAS_CONFIG` to use another
file. See [`deploy/awas.example.toml`](deploy/awas.example.toml) for all current
settings.

