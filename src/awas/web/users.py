from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from awas.auth.passwords import hash_password
from awas.models import User
from awas.models.auth import utc_now
from awas.services.auth import (
    UserInputError,
    active_admin_count,
    add_audit_entry,
    anonymize_deleted_user,
    create_user,
    destroy_user_sessions,
    validate_new_password,
)
from awas.web.dependencies import (
    client_ip,
    database,
    require_admin,
    template_context,
    validate_csrf,
    validate_delete_confirmation,
)

STATUS_MESSAGES = {
    "created": "Das Benutzerkonto wurde angelegt.",
    "enabled": "Das Benutzerkonto wurde aktiviert.",
    "disabled": "Das Benutzerkonto wurde gesperrt.",
    "role": "Die Benutzerrolle wurde geändert.",
    "password": "Das vorläufige Passwort wurde gesetzt.",
    "deleted": "Das Benutzerkonto wurde gelöscht.",
}


def build_user_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/admin/users")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def user_list(
        request: Request,
        _: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        users = list(
            db.scalars(
                select(User).where(User.deleted_at.is_(None)).order_by(User.username)
            )
        )
        return templates.TemplateResponse(
            request=request,
            name="users/list.html",
            context=template_context(
                request,
                users=users,
                notice=STATUS_MESSAGES.get(request.query_params.get("status", "")),
            ),
        )

    @router.get("/new", response_class=HTMLResponse, include_in_schema=False)
    async def new_user_page(
        request: Request,
        _: User = Depends(require_admin),
    ) -> HTMLResponse:
        return render_new_user(templates, request)

    @router.post("", response_class=HTMLResponse, include_in_schema=False)
    async def add_user(
        request: Request,
        username: str = Form(..., max_length=64),
        display_name: str = Form(..., max_length=128),
        role: str = Form(..., max_length=16),
        password: str = Form(..., max_length=128),
        password_confirmation: str = Form(..., max_length=128),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        try:
            create_user(
                db,
                username=username,
                display_name=display_name,
                password=password,
                password_confirmation=password_confirmation,
                role=role,
                actor=admin,
                ip_address=client_ip(request),
                must_change_password=True,
            )
        except UserInputError as exc:
            return render_new_user(
                templates,
                request,
                error=str(exc),
                values={"username": username, "display_name": display_name, "role": role},
                status_code=400,
            )
        return RedirectResponse(url="/admin/users?status=created", status_code=303)

    @router.get("/{user_id}", response_class=HTMLResponse, include_in_schema=False)
    async def user_detail(
        user_id: int,
        request: Request,
        _: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        target = get_target_user(db, user_id)
        return templates.TemplateResponse(
            request=request,
            name="users/detail.html",
            context=template_context(request, target=target, error=None),
        )

    @router.post("/{user_id}/status", response_class=HTMLResponse, include_in_schema=False)
    async def change_status(
        user_id: int,
        request: Request,
        enabled: str = Form(..., max_length=5),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        target = get_target_user(db, user_id)
        enable_account = enabled == "true"
        if not enable_account and target.id == admin.id:
            return render_user_error(
                templates, request, target, "Das eigene Konto kann nicht gesperrt werden."
            )
        if (
            not enable_account
            and target.is_admin
            and target.is_active
            and active_admin_count(db) <= 1
        ):
            return render_user_error(
                templates,
                request,
                target,
                "Der letzte aktive Administrator kann nicht gesperrt werden.",
            )

        target.is_active = enable_account
        target.updated_at = utc_now()
        if not enable_account:
            destroy_user_sessions(db, target.id)
        add_audit_entry(
            db,
            "user.enabled" if enable_account else "user.disabled",
            actor=admin,
            target=target,
            ip_address=client_ip(request),
        )
        db.commit()
        status = "enabled" if enable_account else "disabled"
        return RedirectResponse(url=f"/admin/users?status={status}", status_code=303)

    @router.post("/{user_id}/role", response_class=HTMLResponse, include_in_schema=False)
    async def change_role(
        user_id: int,
        request: Request,
        role: str = Form(..., max_length=16),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        target = get_target_user(db, user_id)
        if role not in {"admin", "user"}:
            return render_user_error(templates, request, target, "Unbekannte Benutzerrolle.")
        if target.id == admin.id and role != target.role:
            return render_user_error(
                templates, request, target, "Die eigene Rolle kann nicht geändert werden."
            )
        if (
            target.role == "admin"
            and role == "user"
            and target.is_active
            and active_admin_count(db) <= 1
        ):
            return render_user_error(
                templates,
                request,
                target,
                "Der letzte aktive Administrator kann nicht herabgestuft werden.",
            )

        old_role = target.role
        target.role = role
        target.updated_at = utc_now()
        add_audit_entry(
            db,
            "user.role_changed",
            actor=admin,
            target=target,
            ip_address=client_ip(request),
            details={"old_role": old_role, "new_role": role},
        )
        db.commit()
        return RedirectResponse(url="/admin/users?status=role", status_code=303)

    @router.post("/{user_id}/password", response_class=HTMLResponse, include_in_schema=False)
    async def reset_password(
        user_id: int,
        request: Request,
        password: str = Form(..., max_length=128),
        password_confirmation: str = Form(..., max_length=128),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        target = get_target_user(db, user_id)
        if target.id == admin.id:
            return render_user_error(
                templates,
                request,
                target,
                "Das eigene Passwort wird unter „Passwort ändern“ geändert.",
            )
        try:
            validate_new_password(password, password_confirmation)
        except UserInputError as exc:
            return render_user_error(templates, request, target, str(exc))

        target.password_hash = hash_password(password)
        target.password_changed_at = utc_now()
        target.must_change_password = True
        target.updated_at = utc_now()
        destroy_user_sessions(db, target.id)
        add_audit_entry(
            db,
            "user.password_reset",
            actor=admin,
            target=target,
            ip_address=client_ip(request),
        )
        db.commit()
        return RedirectResponse(url="/admin/users?status=password", status_code=303)

    @router.post("/{user_id}/delete", response_class=HTMLResponse, include_in_schema=False)
    async def delete_user(
        user_id: int,
        request: Request,
        delete_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_delete_confirmation(delete_confirmed)
        target = get_target_user(db, user_id)
        if target.id == admin.id:
            return render_user_error(
                templates, request, target, "Das eigene Konto kann nicht gelöscht werden."
            )
        if target.is_admin and target.is_active and active_admin_count(db) <= 1:
            return render_user_error(
                templates,
                request,
                target,
                "Der letzte aktive Administrator kann nicht gelöscht werden.",
            )

        anonymize_deleted_user(
            db,
            target,
            actor=admin,
            ip_address=client_ip(request),
        )
        return RedirectResponse(url="/admin/users?status=deleted", status_code=303)

    return router


def get_target_user(db: Session, user_id: int) -> User:
    target = db.get(User, user_id)
    if target is None or target.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    return target


def render_new_user(
    templates: Jinja2Templates,
    request: Request,
    *,
    error: str | None = None,
    values: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="users/new.html",
        context=template_context(
            request,
            error=error,
            values=values or {"username": "", "display_name": "", "role": "user"},
        ),
        status_code=status_code,
    )


def render_user_error(
    templates: Jinja2Templates, request: Request, target: User, message: str
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="users/detail.html",
        context=template_context(request, target=target, error=message),
        status_code=400,
    )
