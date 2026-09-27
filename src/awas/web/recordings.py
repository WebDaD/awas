from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from awas.models import Recording, Stream, User
from awas.services.recorders import recorder_label
from awas.services.recording import RecordingError, RecordingManager
from awas.web.dependencies import (
    AuthorizationDenied,
    client_ip,
    database,
    require_user,
    template_context,
    validate_csrf,
    validate_delete_confirmation,
    validate_stop_confirmation,
)
from awas.web.streams import render_stream_list

STATUS_MESSAGES = {
    "started": "Die Aufnahme wurde gestartet.",
    "stopping": "Die Aufnahme wird beendet und die Datei abgeschlossen.",
    "deleted": "Die Aufnahme wurde gelöscht.",
    "stopped": "Die Aufnahme wurde beendet. Weitere Versuche finden nicht statt.",
}

STATUS_LABELS = {
    "starting": "Wird gestartet",
    "recording": "Läuft",
    "stopping": "Wird beendet",
    "completed": "Abgeschlossen",
    "failed": "Fehlgeschlagen",
    "interrupted": "Unterbrochen",
}


def build_recording_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/recordings", response_class=HTMLResponse, include_in_schema=False)
    async def recording_list(
        request: Request,
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        return render_recordings(
            templates,
            request,
            db,
            notice=STATUS_MESSAGES.get(request.query_params.get("status", "")),
        )

    @router.post("/streams/{stream_id}/recordings/start", include_in_schema=False)
    async def start_recording(
        stream_id: int,
        request: Request,
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        stream = db.get(Stream, stream_id)
        if stream is None:
            raise HTTPException(status_code=404, detail="Stream nicht gefunden")
        manager: RecordingManager = request.app.state.recording_manager
        try:
            manager.start_recording(
                db,
                stream=stream,
                actor=user,
                ip_address=client_ip(request),
            )
        except RecordingError as exc:
            return render_stream_list(
                templates,
                request,
                db,
                user=user,
                error=str(exc),
                status_code=400,
            )
        return RedirectResponse(url="/streams?status=started", status_code=303)

    @router.post("/recordings/{recording_id}/stop", include_in_schema=False)
    async def stop_recording(
        recording_id: int,
        request: Request,
        return_to: str = Form("/recordings", max_length=32),
        stop_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_stop_confirmation(stop_confirmed)
        recording = get_recording(db, recording_id)
        ensure_can_manage_recording(recording, user)
        manager: RecordingManager = request.app.state.recording_manager
        try:
            manager.stop_recording(
                db,
                recording=recording,
                actor=user,
                ip_address=client_ip(request),
            )
        except RecordingError as exc:
            return render_recordings(
                templates,
                request,
                db,
                error=str(exc),
                status_code=400,
            )
        destination = return_to if return_to in {"/", "/streams", "/recordings"} else "/recordings"
        return RedirectResponse(url=f"{destination}?status=stopping", status_code=303)

    @router.get("/recordings/{recording_id}/download", include_in_schema=False)
    async def download_recording(
        recording_id: int,
        request: Request,
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        recording = get_recording(db, recording_id)
        if recording.file_deleted_at is not None:
            raise HTTPException(status_code=404, detail="Aufnahmedatei nicht gefunden")
        manager: RecordingManager = request.app.state.recording_manager
        try:
            path = manager.output_path(recording)
        except RecordingError as exc:
            raise HTTPException(status_code=404, detail="Aufnahmedatei nicht gefunden") from exc
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Aufnahmedatei nicht gefunden")
        if recording.is_running:
            try:
                snapshot_size = path.stat().st_size
            except OSError as exc:
                raise HTTPException(
                    status_code=404,
                    detail="Aufnahmedatei nicht gefunden",
                ) from exc
            file_name = path.name
            return StreamingResponse(
                _file_snapshot(path, snapshot_size),
                media_type="application/octet-stream",
                headers={
                    "Content-Length": str(snapshot_size),
                    "Content-Disposition": (
                        "attachment; filename*=utf-8''" + quote(file_name)
                    ),
                },
            )
        return FileResponse(
            path,
            filename=recording.file_name,
            media_type="application/octet-stream",
        )

    @router.post("/recordings/{recording_id}/delete", include_in_schema=False)
    async def remove_recording(
        recording_id: int,
        request: Request,
        delete_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_delete_confirmation(delete_confirmed)
        recording = get_recording(db, recording_id)
        ensure_can_manage_recording(recording, user)
        manager: RecordingManager = request.app.state.recording_manager
        try:
            manager.delete_recording(
                db,
                recording=recording,
                actor=user,
                ip_address=client_ip(request),
            )
        except RecordingError as exc:
            return render_recordings(
                templates,
                request,
                db,
                error=str(exc),
                status_code=400,
            )
        return RedirectResponse(url="/recordings?status=deleted", status_code=303)

    return router


def get_recording(db: Session, recording_id: int) -> Recording:
    recording = db.get(Recording, recording_id)
    if recording is None:
        raise HTTPException(status_code=404, detail="Aufnahme nicht gefunden")
    return recording


def ensure_can_manage_recording(recording: Recording, user: User) -> None:
    if not user.is_admin and recording.started_by_id != user.id:
        raise AuthorizationDenied


def render_recordings(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
    *,
    notice: str | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    recordings = list(
        db.scalars(
            select(Recording)
            .options(
                joinedload(Recording.schedule),
                joinedload(Recording.started_by),
            )
            .order_by(Recording.started_at.desc())
            .limit(500)
        )
    )
    manager: RecordingManager = request.app.state.recording_manager
    storage = manager.storage_snapshot(db)
    file_sizes = {recording.id: manager.current_file_size(recording) for recording in recordings}
    return templates.TemplateResponse(
        request=request,
        name="recordings/list.html",
        context=template_context(
            request,
            recordings=recordings,
            storage=storage,
            file_sizes=file_sizes,
            status_labels=STATUS_LABELS,
            recorder_label=recorder_label,
            notice=notice,
            error=error,
        ),
        status_code=status_code,
    )


def _file_snapshot(path: Path, size: int) -> Iterator[bytes]:
    remaining = size
    with path.open("rb") as source:
        while remaining > 0:
            chunk = source.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
