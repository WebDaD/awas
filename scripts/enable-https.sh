#!/usr/bin/env bash
set -Eeuo pipefail

readonly TLS_CERTIFICATE="/etc/awas/tls/fullchain.pem"
readonly TLS_PRIVATE_KEY="/etc/awas/tls/privkey.pem"
readonly NGINX_AVAILABLE="/etc/nginx/sites-available/awas-https.conf"
readonly NGINX_ENABLED="/etc/nginx/sites-enabled/awas-https.conf"

if [[ ${EUID} -ne 0 ]]; then
    echo "Run this command as root: sudo bash /opt/awas/app/scripts/enable-https.sh" >&2
    exit 1
fi

if [[ ! -s "${TLS_CERTIFICATE}" ]]; then
    echo "Missing TLS certificate: ${TLS_CERTIFICATE}" >&2
    exit 1
fi
if [[ ! -s "${TLS_PRIVATE_KEY}" ]]; then
    echo "Missing TLS private key: ${TLS_PRIVATE_KEY}" >&2
    exit 1
fi
if [[ ! -f "${NGINX_AVAILABLE}" ]]; then
    echo "Missing AWAS HTTPS nginx configuration: ${NGINX_AVAILABLE}" >&2
    exit 1
fi

ln -sfn "${NGINX_AVAILABLE}" "${NGINX_ENABLED}"

if ! nginx -t; then
    rm -f "${NGINX_ENABLED}"
    nginx -t || true
    echo "HTTPS was not enabled because the nginx configuration is invalid." >&2
    exit 1
fi

systemctl reload nginx.service
echo "AWAS HTTPS is enabled on port 443. HTTP remains enabled on port 80."
