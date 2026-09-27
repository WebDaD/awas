#!/usr/bin/env bash
set -Eeuo pipefail

readonly APP_USER="awas-service"
readonly APP_GROUP="awas-service"
readonly APP_ROOT="/opt/awas"
readonly APP_SOURCE="${APP_ROOT}/app"
readonly CONFIG_DIR="/etc/awas"
readonly TLS_DIR="${CONFIG_DIR}/tls"
readonly TLS_CERTIFICATE="${TLS_DIR}/fullchain.pem"
readonly TLS_PRIVATE_KEY="${TLS_DIR}/privkey.pem"
readonly NGINX_HTTP_CONFIG="/etc/nginx/sites-available/awas.conf"
readonly NGINX_HTTPS_CONFIG="/etc/nginx/sites-available/awas-https.conf"
readonly DATA_DIR="/var/lib/awas"
readonly LOG_DIR="/var/log/awas"
readonly RECORDING_DIR="/srv/awas/recordings"

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this installer as root: sudo ./scripts/install.sh" >&2
    exit 1
fi

SOURCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ ! -f "${SOURCE_DIR}/pyproject.toml" ]]; then
    echo "Could not locate the AWAS source directory." >&2
    exit 1
fi

source /etc/os-release
case "${ID:-}" in
    debian|raspbian)
        if [[ "${VERSION_ID:-}" != "13" ]]; then
            echo "Warning: AWAS is tested on Debian/Raspberry Pi OS 13; found ${PRETTY_NAME:-unknown}." >&2
        fi
        ;;
    ubuntu)
        case "${VERSION_ID:-}" in
            24.04|26.04) ;;
            *) echo "Warning: AWAS is tested on Ubuntu 24.04/26.04; found ${PRETTY_NAME:-unknown}." >&2 ;;
        esac
        ;;
    *)
        echo "Unsupported distribution: ${PRETTY_NAME:-${ID:-unknown}}" >&2
        exit 1
        ;;
esac

case "$(dpkg --print-architecture)" in
    arm64|amd64) ;;
    *) echo "AWAS 3 currently supports arm64 and amd64 only." >&2; exit 1 ;;
esac

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates ffmpeg mplayer mpv nginx python3 python3-pip python3-venv \
    rsync sqlite3 streamlink streamripper vlc-bin vlc-plugin-base

if ! getent group "${APP_GROUP}" >/dev/null; then
    groupadd --system "${APP_GROUP}"
fi
if ! id "${APP_USER}" >/dev/null 2>&1; then
    useradd --system --gid "${APP_GROUP}" --home-dir "${DATA_DIR}" --shell /usr/sbin/nologin "${APP_USER}"
fi

install -d -o root -g root -m 0755 "${APP_ROOT}" "${APP_SOURCE}"
install -d -o root -g "${APP_GROUP}" -m 0750 "${CONFIG_DIR}"
install -d -o root -g root -m 0700 "${TLS_DIR}"
install -d -o "${APP_USER}" -g "${APP_GROUP}" -m 0750 "${DATA_DIR}" "${LOG_DIR}" "${RECORDING_DIR}"

rsync -a --delete \
    --chown=root:root --chmod=D755,F644 \
    --exclude '.git/' --exclude '.venv/' --exclude '__pycache__/' --exclude '*.pyc' \
    "${SOURCE_DIR}/" "${APP_SOURCE}/"
find "${APP_SOURCE}/scripts" -type f -name '*.sh' -exec chmod 0755 {} +

if [[ ! -x "${APP_ROOT}/.venv/bin/python" ]]; then
    python3 -m venv "${APP_ROOT}/.venv"
fi
"${APP_ROOT}/.venv/bin/python" -m pip install --upgrade pip
"${APP_ROOT}/.venv/bin/python" -m pip install --upgrade "${APP_SOURCE}"

if [[ ! -f "${CONFIG_DIR}/awas.toml" ]]; then
    install -o root -g "${APP_GROUP}" -m 0640 \
        "${APP_SOURCE}/deploy/awas.example.toml" "${CONFIG_DIR}/awas.toml"
fi

install -o root -g root -m 0644 "${APP_SOURCE}/deploy/systemd/awas.service" /etc/systemd/system/awas.service
if [[ ! -f "${NGINX_HTTP_CONFIG}" ]]; then
    install -o root -g root -m 0644 "${APP_SOURCE}/deploy/nginx/awas.conf" "${NGINX_HTTP_CONFIG}"
fi
if [[ ! -f "${NGINX_HTTPS_CONFIG}" ]]; then
    install -o root -g root -m 0644 "${APP_SOURCE}/deploy/nginx/awas-https.conf" "${NGINX_HTTPS_CONFIG}"
fi
ln -sfn "${NGINX_HTTP_CONFIG}" /etc/nginx/sites-enabled/awas.conf
rm -f /etc/nginx/sites-enabled/default

https_enabled=false
if [[ -s "${TLS_CERTIFICATE}" && -s "${TLS_PRIVATE_KEY}" ]]; then
    ln -sfn "${NGINX_HTTPS_CONFIG}" /etc/nginx/sites-enabled/awas-https.conf
    https_enabled=true
else
    rm -f /etc/nginx/sites-enabled/awas-https.conf
fi

nginx -t
systemctl daemon-reload
if systemctl is-active --quiet awas.service; then
    systemctl stop awas.service
fi

(
    cd "${APP_SOURCE}"
    runuser -u "${APP_USER}" -- env AWAS_CONFIG="${CONFIG_DIR}/awas.toml" \
        "${APP_ROOT}/.venv/bin/alembic" -c "${APP_SOURCE}/alembic.ini" upgrade head
)

systemctl enable awas.service nginx.service
systemctl restart awas.service nginx.service

echo
echo "AWAS 3 installation completed."
echo "Open http://$(hostname -I | awk '{print $1}')/"
if [[ "${https_enabled}" == true ]]; then
    echo "HTTPS is enabled on port 443. Use the hostname covered by the installed certificate."
else
    echo "HTTPS is prepared but not enabled because the certificate or private key is missing."
    echo "Install ${TLS_CERTIFICATE} and ${TLS_PRIVATE_KEY}, then run:"
    echo "sudo bash ${APP_SOURCE}/scripts/enable-https.sh"
fi
echo "Check the service with: systemctl status awas"
echo "Create an administrator with:"
echo "sudo -u ${APP_USER} env AWAS_CONFIG=${CONFIG_DIR}/awas.toml ${APP_ROOT}/.venv/bin/awas-admin create-admin"
