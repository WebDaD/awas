from __future__ import annotations

from datetime import UTC
from time import monotonic
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from awas import __release_date__, __version__
from awas.auth.tokens import (
    csrf_from_session_token,
    session_cookie_name,
    tokens_match,
    user_filter_cookie_name,
)
from awas.models import User, WebSession
from awas.models.auth import utc_now


class AuthenticationRequired(Exception):
    def __init__(self, next_url: str = "/") -> None:
        self.next_url = next_url


class PasswordChangeRequired(Exception):
    pass


class AuthorizationDenied(Exception):
    pass


class CsrfValidationFailed(Exception):
    pass


def database(request: Request) -> Session:
    return request.state.db


def current_user(request: Request) -> User | None:
    return request.state.user


def require_user_for_password_change(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise AuthenticationRequired(request.url.path)
    return user


def require_user(request: Request) -> User:
    user = require_user_for_password_change(request)
    if user.must_change_password:
        raise PasswordChangeRequired
    return user


def require_admin(request: Request) -> User:
    user = require_user(request)
    if not user.is_admin:
        raise AuthorizationDenied
    return user


def current_web_session(request: Request) -> WebSession | None:
    return request.state.web_session


def client_ip(request: Request) -> str:
    return request.client.host[:45] if request.client else "unknown"


def csrf_token(request: Request) -> str:
    raw_session_token = request.cookies.get(
        session_cookie_name(https=request.url.scheme == "https")
    )
    if not raw_session_token:
        return ""
    return csrf_from_session_token(raw_session_token)


def validate_csrf(request: Request, submitted_token: str | None) -> None:
    if not tokens_match(csrf_token(request), submitted_token):
        raise CsrfValidationFailed


def validate_delete_confirmation(confirmed: str | None) -> None:
    if confirmed != "true":
        raise HTTPException(status_code=400, detail="Die Löschung muss bestätigt werden.")


def validate_stop_confirmation(confirmed: str | None) -> None:
    if confirmed != "true":
        raise HTTPException(status_code=400, detail="Das Stoppen muss bestätigt werden.")


def user_filter_choices(db: Session) -> list[User]:
    """Return the users shown by list filters in a stable display-name order."""
    users = list(db.scalars(select(User).where(User.deleted_at.is_(None))))
    return sorted(users, key=lambda user: (user.display_name.casefold(), user.id))


def selected_user_filter(
    request: Request, db: Session, *, value: str | None = None
) -> int | None:
    """Read a display preference scoped to this login, never an authorization rule."""
    if value is None:
        value = request.query_params.get("user_id")
    if value is None:
        cookie = request.cookies.get(
            user_filter_cookie_name(https=request.url.scheme == "https"), ""
        )
        scope, separator, value = cookie.partition(".")
        if not separator or not scope.isascii() or not tokens_match(scope, csrf_token(request)):
            return None
    try:
        user_id = int(value)
    except ValueError:
        return None
    if not 0 < user_id <= 2**63 - 1:
        return None
    with db.no_autoflush:
        user = db.get(User, user_id)
    return user_id if user is not None and user.deleted_at is None else None


def clear_user_filter_cookie(request: Request, response: Response) -> None:
    https = request.url.scheme == "https"
    response.delete_cookie(
        user_filter_cookie_name(https=https),
        path="/",
        secure=https or request.app.state.settings.security.session_cookie_secure,
        samesite="lax",
    )


def format_uptime(total_seconds: float) -> str:
    seconds = max(0, int(total_seconds))
    days, remainder = divmod(seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    return f"{days} Tage, {hours:02d}:{minutes:02d}:{seconds:02d}"


def server_status(request: Request) -> dict[str, str]:
    current_monotonic = monotonic()
    started_monotonic = getattr(request.app.state, "started_monotonic", current_monotonic)
    timezone = request.app.state.timezone
    local_now = utc_now().replace(tzinfo=UTC).astimezone(ZoneInfo(timezone))
    return {
        "system_time": f"{local_now:%d.%m.%Y %H:%M:%S} Uhr ({timezone})",
        "uptime": format_uptime(current_monotonic - started_monotonic),
    }


def template_context(request: Request, **extra: object) -> dict[str, object]:
    web_session = current_web_session(request)
    context: dict[str, object] = {
        "request": request,
        "version": __version__,
        "release_date": __release_date__,
        "asset_revision": request.app.state.asset_revision,
        **server_status(request),
        "current_user": current_user(request),
        "csrf_token": csrf_token(request),
        "user_filter_cookie": user_filter_cookie_name(https=request.url.scheme == "https"),
        "user_filter_max_age": (
            max(0, int((web_session.expires_at - utc_now()).total_seconds()))
            if web_session is not None else 0
        ),
    }
    context.update(extra)
    return context
