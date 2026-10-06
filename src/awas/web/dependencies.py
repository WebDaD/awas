from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from awas import __release_date__, __version__
from awas.auth.tokens import csrf_from_session_token, session_cookie_name, tokens_match
from awas.models import User, WebSession


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


def template_context(request: Request, **extra: object) -> dict[str, object]:
    context: dict[str, object] = {
        "request": request,
        "version": __version__,
        "release_date": __release_date__,
        "current_user": current_user(request),
        "csrf_token": csrf_token(request),
    }
    context.update(extra)
    return context
