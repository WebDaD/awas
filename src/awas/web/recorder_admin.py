from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from awas.models import User
from awas.services.recorder_settings import (
    recorder_configurations,
    update_recorder_arguments,
)
from awas.services.recorders import RecorderInputError
from awas.web.dependencies import (
    client_ip,
    database,
    require_admin,
    template_context,
    validate_csrf,
)


def build_recorder_admin_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/admin/recorders")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def recorder_list(
        request: Request,
        _: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        notice = (
            "Die Rekorderparameter wurden gespeichert."
            if request.query_params.get("status") == "updated"
            else None
        )
        return render_recorders(templates, request, db, notice=notice)

    @router.post("/{recorder}", response_class=HTMLResponse, include_in_schema=False)
    async def edit_recorder(
        recorder: str,
        request: Request,
        arguments: str = Form(..., max_length=4096),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        try:
            update_recorder_arguments(
                db,
                recorder=recorder,
                arguments=arguments,
                actor=admin,
                ip_address=client_ip(request),
            )
        except RecorderInputError as exc:
            if recorder not in {item.key for item in recorder_configurations(db)}:
                raise HTTPException(status_code=404, detail="Rekorder nicht gefunden") from exc
            return render_recorders(
                templates,
                request,
                db,
                error=str(exc),
                submitted_recorder=recorder,
                submitted_arguments=arguments,
                status_code=400,
            )
        return RedirectResponse(url="/admin/recorders?status=updated", status_code=303)

    return router


def render_recorders(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
    *,
    notice: str | None = None,
    error: str | None = None,
    submitted_recorder: str | None = None,
    submitted_arguments: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    values = {item.key: item.arguments for item in recorder_configurations(db)}
    if submitted_recorder is not None and submitted_arguments is not None:
        values[submitted_recorder] = submitted_arguments
    return templates.TemplateResponse(
        request=request,
        name="recorders/list.html",
        context=template_context(
            request,
            recorders=recorder_configurations(db),
            values=values,
            notice=notice,
            error=error,
        ),
        status_code=status_code,
    )
