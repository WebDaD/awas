from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from awas.auth.passwords import hash_password, verify_password
from awas.auth.tokens import (
    login_csrf_cookie_name,
    login_csrf_cookie_path,
    new_token,
    session_cookie_name,
    tokens_match,
)
from awas.config import Settings
from awas.models import User
from awas.models.auth import utc_now
from awas.services.auth import (
    UserInputError,
    add_audit_entry,
    authenticate_user,
    create_web_session,
    destroy_session,
    destroy_user_sessions,
    validate_new_password,
)
from awas.web.dependencies import (
    client_ip,
    database,
    require_user_for_password_change,
    template_context,
    validate_csrf,
)


def build_auth_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    def render_login(
        request: Request,
        *,
        status_code: int = 200,
        error: str | None = None,
        username: str = "",
        next_url: str = "/",
    ) -> HTMLResponse:
        https_request = request.url.scheme == "https"
        csrf_cookie = login_csrf_cookie_name(https=https_request)
        csrf_cookie_path = login_csrf_cookie_path(https=https_request)
        login_csrf = request.cookies.get(csrf_cookie) or new_token()
        response = templates.TemplateResponse(
            request=request,
            name="login.html",
            context=template_context(
                request,
                login_csrf=login_csrf,
                error=error,
                username=username,
                next_url=safe_next_url(next_url),
                password_changed=request.query_params.get("status") == "password-changed",
            ),
            status_code=status_code,
        )
        settings: Settings = request.app.state.settings
        secure_cookie = https_request or settings.security.session_cookie_secure
        response.set_cookie(
            csrf_cookie,
            login_csrf,
            max_age=600,
            secure=secure_cookie,
            httponly=True,
            samesite="strict",
            path=csrf_cookie_path,
        )
        return response

    @router.get("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login_page(request: Request, next: str = "/") -> Response:
        if request.state.user is not None:
            return RedirectResponse(url="/", status_code=303)
        return render_login(request, next_url=next)

    @router.post("/login", response_class=HTMLResponse, include_in_schema=False)
    async def login(
        request: Request,
        username: str = Form(..., max_length=64),
        password: str = Form(..., max_length=128),
        csrf_token: str = Form(..., max_length=128),
        next_url: str = Form("/", max_length=512),
        db: Session = Depends(database),
    ) -> Response:
        https_request = request.url.scheme == "https"
        csrf_cookie = login_csrf_cookie_name(https=https_request)
        csrf_cookie_path = login_csrf_cookie_path(https=https_request)
        login_cookie = request.cookies.get(csrf_cookie)
        if not tokens_match(login_cookie, csrf_token):
            return render_login(
                request,
                status_code=403,
                error="Die Anmeldung ist abgelaufen. Bitte versuche es erneut.",
                username=username,
                next_url=next_url,
            )

        settings: Settings = request.app.state.settings
        secure_cookie = https_request or settings.security.session_cookie_secure
        user, limited = authenticate_user(
            db,
            username=username,
            password=password,
            ip_address=client_ip(request),
            security=settings.security,
        )
        if user is None:
            message = (
                "Zu viele Anmeldeversuche. Bitte warte einige Minuten."
                if limited
                else "Benutzername oder Passwort ist falsch."
            )
            return render_login(
                request,
                status_code=429 if limited else 401,
                error=message,
                username=username,
                next_url=next_url,
            )

        raw_session_token = create_web_session(
            db,
            user,
            security=settings.security,
            ip_address=client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
        destination = "/account/password" if user.must_change_password else safe_next_url(next_url)
        response = RedirectResponse(url=destination, status_code=303)
        active_session_cookie = session_cookie_name(https=https_request)
        response.set_cookie(
            active_session_cookie,
            raw_session_token,
            max_age=settings.security.session_lifetime_hours * 3600,
            secure=secure_cookie,
            httponly=True,
            samesite="lax",
            path="/",
        )
        response.delete_cookie(
            csrf_cookie,
            path=csrf_cookie_path,
            secure=secure_cookie,
            httponly=True,
            samesite="strict",
        )
        return response

    @router.post("/logout", include_in_schema=False)
    async def logout(
        request: Request,
        csrf_token: str = Form(..., max_length=128),
        _: User = Depends(require_user_for_password_change),
        db: Session = Depends(database),
    ) -> RedirectResponse:
        validate_csrf(request, csrf_token)
        https_request = request.url.scheme == "https"
        settings: Settings = request.app.state.settings
        secure_cookie = https_request or settings.security.session_cookie_secure
        active_session_cookie = session_cookie_name(https=https_request)
        raw_session_token = request.cookies.get(active_session_cookie)
        destroy_session(db, raw_session_token)
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie(
            active_session_cookie,
            path="/",
            secure=secure_cookie,
            httponly=True,
            samesite="lax",
        )
        return response

    @router.get("/account/password", response_class=HTMLResponse, include_in_schema=False)
    async def password_page(
        request: Request,
        user: User = Depends(require_user_for_password_change),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="password.html",
            context=template_context(request, user=user, error=None),
        )

    @router.post("/account/password", response_class=HTMLResponse, include_in_schema=False)
    async def change_password(
        request: Request,
        current_password: str = Form(..., max_length=128),
        new_password: str = Form(..., max_length=128),
        new_password_confirmation: str = Form(..., max_length=128),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user_for_password_change),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        error: str | None = None
        if not verify_password(current_password, user.password_hash):
            error = "Das aktuelle Passwort ist falsch."
        else:
            try:
                validate_new_password(new_password, new_password_confirmation)
            except UserInputError as exc:
                error = str(exc)

        if error:
            return templates.TemplateResponse(
                request=request,
                name="password.html",
                context=template_context(request, user=user, error=error),
                status_code=400,
            )

        user.password_hash = hash_password(new_password)
        user.password_changed_at = utc_now()
        user.must_change_password = False
        destroy_user_sessions(db, user.id)
        add_audit_entry(
            db,
            "user.password_changed",
            actor=user,
            target=user,
            ip_address=client_ip(request),
        )
        db.commit()
        response = RedirectResponse(url="/login?status=password-changed", status_code=303)
        https_request = request.url.scheme == "https"
        settings: Settings = request.app.state.settings
        response.delete_cookie(
            session_cookie_name(https=https_request),
            path="/",
            secure=https_request or settings.security.session_cookie_secure,
            httponly=True,
            samesite="lax",
        )
        return response

    return router


def safe_next_url(value: str) -> str:
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    return value
