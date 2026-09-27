from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from awas.models import (
    Recording,
    RecordingSchedule,
    RecurringSchedule,
    Stream,
    User,
)
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.recorders import (
    DEFAULT_FILE_TYPE,
    FILE_TYPE_CHOICES,
    RECORDER_CHOICES,
    recorder_label,
)
from awas.services.streams import (
    StreamInputError,
    check_stream_url,
    create_stream,
    update_stream,
)
from awas.web.dependencies import (
    client_ip,
    database,
    require_admin,
    require_user,
    template_context,
    validate_csrf,
    validate_delete_confirmation,
)

STATUS_MESSAGES = {
    "created": "Der Stream wurde angelegt.",
    "updated": "Die Streamdaten wurden gespeichert.",
    "test-ok": "Die Stream-Verbindung wurde erfolgreich geprüft.",
    "test-failed": "Die Stream-Verbindung konnte nicht bestätigt werden.",
    "deleted": "Der Stream wurde gelöscht.",
    "started": "Die Aufnahme wurde gestartet.",
    "stopping": "Die Aufnahme wird beendet und die Datei abgeschlossen.",
}


def build_stream_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/streams", response_class=HTMLResponse, include_in_schema=False)
    async def stream_list(
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        return render_stream_list(
            templates,
            request,
            db,
            user=user,
            notice=STATUS_MESSAGES.get(request.query_params.get("status", "")),
        )

    @router.get("/admin/streams", include_in_schema=False)
    async def legacy_stream_list(
        _: User = Depends(require_user),
    ) -> RedirectResponse:
        return RedirectResponse(url="/streams", status_code=303)

    @router.get("/admin/streams/new", response_class=HTMLResponse, include_in_schema=False)
    async def new_stream_page(
        request: Request,
        _: User = Depends(require_user),
    ) -> HTMLResponse:
        return render_new_stream(templates, request)

    @router.post("/admin/streams", response_class=HTMLResponse, include_in_schema=False)
    async def add_stream(
        request: Request,
        name: str = Form(..., max_length=128),
        stream_url: str = Form(..., max_length=2048),
        preferred_recorder: str | None = Form(None, max_length=32),
        preferred_file_type: str | None = Form(None, max_length=16),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        try:
            create_stream(
                db,
                name=name,
                stream_url=stream_url,
                preferred_recorder=preferred_recorder or "",
                preferred_file_type=preferred_file_type or DEFAULT_FILE_TYPE,
                actor=user,
                ip_address=client_ip(request),
            )
        except StreamInputError as exc:
            return render_new_stream(
                templates,
                request,
                error=str(exc),
                values={
                    "name": name,
                    "stream_url": stream_url,
                    "preferred_recorder": preferred_recorder or "",
                    "preferred_file_type": preferred_file_type or "",
                },
                status_code=400,
            )
        return RedirectResponse(url="/streams?status=created", status_code=303)

    @router.get(
        "/admin/streams/{stream_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def stream_detail(
        stream_id: int,
        request: Request,
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        stream = get_stream(db, stream_id)
        return render_stream_detail(
            templates,
            request,
            stream,
            notice=STATUS_MESSAGES.get(request.query_params.get("status", "")),
        )

    @router.post(
        "/admin/streams/{stream_id}",
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    async def edit_stream(
        stream_id: int,
        request: Request,
        name: str = Form(..., max_length=128),
        stream_url: str = Form(..., max_length=2048),
        preferred_recorder: str | None = Form(None, max_length=32),
        preferred_file_type: str | None = Form(None, max_length=16),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        stream = get_stream(db, stream_id)
        selected_recorder = preferred_recorder or stream.preferred_recorder
        selected_file_type = preferred_file_type or stream.preferred_file_type
        try:
            update_stream(
                db,
                stream,
                name=name,
                stream_url=stream_url,
                preferred_recorder=selected_recorder,
                preferred_file_type=selected_file_type,
                actor=user,
                ip_address=client_ip(request),
            )
        except StreamInputError as exc:
            stream.name = name
            stream.stream_url = stream_url
            stream.preferred_recorder = selected_recorder
            stream.preferred_file_type = selected_file_type
            return render_stream_detail(
                templates,
                request,
                stream,
                error=str(exc),
                status_code=400,
            )
        return RedirectResponse(url="/streams?status=updated", status_code=303)

    @router.post("/admin/streams/{stream_id}/test", include_in_schema=False)
    async def test_stream_connection(
        stream_id: int,
        request: Request,
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> RedirectResponse:
        validate_csrf(request, csrf_token)
        stream = get_stream(db, stream_id)
        result = await asyncio.to_thread(check_stream_url, stream.stream_url)
        stream.last_checked_at = utc_now()
        stream.last_check_ok = result.ok
        stream.last_check_message = result.message[:256]
        stream.updated_at = utc_now()
        add_audit_entry(
            db,
            "stream.tested",
            actor=user,
            target_type="stream",
            target_id=stream.id,
            ip_address=client_ip(request),
            details={"name": stream.name, "succeeded": result.ok},
        )
        db.commit()
        status = "test-ok" if result.ok else "test-failed"
        return RedirectResponse(
            url=f"/admin/streams/{stream.id}?status={status}", status_code=303
        )

    @router.post("/admin/streams/{stream_id}/delete", include_in_schema=False)
    async def remove_stream(
        stream_id: int,
        request: Request,
        delete_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_delete_confirmation(delete_confirmed)
        stream = get_stream(db, stream_id)
        schedule_id = db.scalar(
            select(RecordingSchedule.id)
            .where(
                RecordingSchedule.stream_id == stream.id,
                RecordingSchedule.is_hidden.is_(False),
            )
            .limit(1)
        )
        if schedule_id is not None:
            return render_stream_detail(
                templates,
                request,
                stream,
                error="Dieser Stream besitzt Zeitpläne und kann deshalb nicht gelöscht werden.",
                status_code=400,
            )
        recurrence_id = db.scalar(
            select(RecurringSchedule.id)
            .where(
                RecurringSchedule.stream_id == stream.id,
                RecurringSchedule.is_hidden.is_(False),
            )
            .limit(1)
        )
        if recurrence_id is not None:
            return render_stream_detail(
                templates,
                request,
                stream,
                error=(
                    "Dieser Stream besitzt Wiederholungen und kann deshalb nicht gelöscht werden."
                ),
                status_code=400,
            )
        add_audit_entry(
            db,
            "stream.deleted",
            actor=admin,
            target_type="stream",
            target_id=stream.id,
            ip_address=client_ip(request),
            details={"name": stream.name},
        )
        db.delete(stream)
        db.commit()
        return RedirectResponse(url="/streams?status=deleted", status_code=303)

    return router


def get_stream(db: Session, stream_id: int) -> Stream:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise HTTPException(status_code=404, detail="Stream nicht gefunden")
    return stream


def render_new_stream(
    templates: Jinja2Templates,
    request: Request,
    *,
    error: str | None = None,
    values: dict[str, object] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="streams/new.html",
        context=template_context(
            request,
            error=error,
            values=values
            or {
                "name": "",
                "stream_url": "",
                "preferred_recorder": "",
                "preferred_file_type": "",
            },
            recorder_choices=RECORDER_CHOICES,
            file_type_choices=FILE_TYPE_CHOICES,
            recorder_label=recorder_label,
        ),
        status_code=status_code,
    )


def render_stream_detail(
    templates: Jinja2Templates,
    request: Request,
    stream: Stream,
    *,
    notice: str | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request=request,
        name="streams/detail.html",
        context=template_context(
            request,
            stream=stream,
            recorder_choices=RECORDER_CHOICES,
            file_type_choices=FILE_TYPE_CHOICES,
            notice=notice,
            error=error,
        ),
        status_code=status_code,
    )


def render_stream_list(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
    *,
    user: User,
    notice: str | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    streams = list(db.scalars(select(Stream).order_by(Stream.name)))
    latest_recording_ids = select(func.max(Recording.id)).group_by(Recording.stream_id)
    last_recordings = {
        recording.stream_id: recording
        for recording in db.scalars(
            select(Recording).where(Recording.id.in_(latest_recording_ids))
        )
    }
    return templates.TemplateResponse(
        request=request,
        name="streams/list.html",
        context=template_context(
            request,
            streams=streams,
            last_recordings=last_recordings,
            recorder_choices=RECORDER_CHOICES,
            file_type_choices=FILE_TYPE_CHOICES,
            recorder_label=recorder_label,
            notice=notice,
            error=error,
        ),
        status_code=status_code,
    )
