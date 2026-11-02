from __future__ import annotations

import hashlib
import hmac
import secrets

SESSION_COOKIE = "awas_session"
LOGIN_CSRF_COOKIE = "awas_login_csrf"
HTTPS_SESSION_COOKIE = "__Host-awas_session"
HTTPS_LOGIN_CSRF_COOKIE = "__Host-awas_login_csrf"
USER_FILTER_COOKIE = "awas_user_filter"
HTTPS_USER_FILTER_COOKIE = "__Host-awas_user_filter"


def session_cookie_name(*, https: bool) -> str:
    return HTTPS_SESSION_COOKIE if https else SESSION_COOKIE


def login_csrf_cookie_name(*, https: bool) -> str:
    return HTTPS_LOGIN_CSRF_COOKIE if https else LOGIN_CSRF_COOKIE


def user_filter_cookie_name(*, https: bool) -> str:
    return HTTPS_USER_FILTER_COOKIE if https else USER_FILTER_COOKIE


def login_csrf_cookie_path(*, https: bool) -> str:
    # __Host- cookies must use Path=/ and may not specify a Domain attribute.
    return "/" if https else "/login"


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_from_session_token(session_token: str) -> str:
    return hmac.new(
        session_token.encode("utf-8"), b"awas-csrf-token-v1", hashlib.sha256
    ).hexdigest()


def tokens_match(left: str | None, right: str | None) -> bool:
    if not left or not right:
        return False
    return hmac.compare_digest(left, right)
