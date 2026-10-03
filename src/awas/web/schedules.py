from __future__ import annotations

from datetime import UTC
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from awas.models import (
    ACTIVE_RECORDING_STATUSES,
    Recording,
    RecordingSchedule,
    RecurringSchedule,
    Stream,
    User,
)
from awas.models.auth import utc_now
from awas.services.recorders import FILE_TYPE_CHOICES, RECORDER_CHOICES, recorder_label
from awas.services.recording import RecordingGroup
from awas.services.scheduling import (
    RecordingScheduler,
    ScheduleInputError,
    cancel_schedule,
    create_schedule,
    datetime_local_value,
    hide_schedule,
    parse_local_datetime,
    update_schedule,
)
from awas.services.streams import stream_name_sort_key
from awas.web.dependencies import (
    AuthorizationDenied,
    client_ip,
    database,
    require_user,
    template_context,
    validate_csrf,
    validate_delete_confirmation,
    validate_discard_confirmation,
    validate_stop_confirmation,
)

STATUS_MESSAGES = {
    "created": "Der Zeitplan wurde angelegt.",
    "updated": "Der Zeitplan wurde gespeichert.",
    "discarded": "Der Zeitplan wurde verworfen.",
    "stopped": "Die Aufnahme wurde beendet. Weitere Versuche finden nicht statt.",
    "deleted": "Der Zeitplaneintrag wurde ausgeblendet.",
    "recurrence-created": "Die Wiederholung wurde angelegt.",
    "recurrence-updated": "Die Wiederholung wurde gespeichert.",
    "recurrence-enabled": "Die Wiederholung wurde aktiviert.",
    "recurrence-disabled": "Die Wiederholung wurde pausiert.",
    "recurrence-deleted": "Die Wiederholung wurde gelöscht.",
}

STATUS_LABELS = {
    "scheduled": "Geplant",
    "running": "Läuft",
    "completed": "Abgeschlossen",
    "cancelled": "Verworfen",
    "missed": "Verpasst",
    "failed": "Fehlgeschlagen",
}

HISTORY_SCHEDULE_STATUSES = ("completed", "missed", "failed")


def build_schedule_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/schedules")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def schedule_list(
        request: Request,
        _: User = Depends(require_user),
    ) -> RedirectResponse:
        status = request.query_params.get("status", "")
        destination = f"/?status={status}" if status else "/"
        return RedirectResponse(
            url=destination,
            status_code=303,
        )

    @router.get("/new", response_class=HTMLResponse, include_in_schema=False)
    async def new_schedule_page(
        request: Request,
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        return render_schedule_form(
            templates,
            request,
            db,
            values={
                "title": "",
                "file_name_base": "",
                "stream_id": "",
                "starts_at": "",
                "ends_at": "",
                "recorder": "",
                "file_type": "",
            },
        )

    @router.post("", response_class=HTMLResponse, include_in_schema=False)
    async def add_schedule(
        request: Request,
        title: str = Form(..., max_length=128),
        file_name_base: str | None = Form(None, max_length=128),
        stream_id: int = Form(...),
        recorder: str | None = Form(None, max_length=32),
        file_type: str | None = Form(None, max_length=16),
        starts_at: str = Form(..., max_length=32),
        ends_at: str = Form(..., max_length=32),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        values = {
            "title": title,
            "file_name_base": file_name_base or "",
            "stream_id": str(stream_id),
            "recorder": recorder or "",
            "file_type": file_type or "",
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
        try:
            stream = get_stream(db, stream_id)
            selected_recorder = recorder or stream.preferred_recorder
            selected_file_type = file_type or stream.preferred_file_type
            values["recorder"] = selected_recorder
            values["file_type"] = selected_file_type
            timezone = request.app.state.timezone
            create_schedule(
                db,
                stream=stream,
                title=title,
                file_name_base=file_name_base,
                recorder=selected_recorder,
                file_type=selected_file_type,
                starts_at=parse_local_datetime(starts_at, timezone, "Die Startzeit"),
                ends_at=parse_local_datetime(ends_at, timezone, "Die Endzeit"),
                actor=user,
                ip_address=client_ip(request),
            )
        except ScheduleInputError as exc:
            return render_schedule_form(
                templates,
                request,
                db,
                values=values,
                error=str(exc),
                status_code=400,
            )
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        scheduler.wake()
        return RedirectResponse(url="/?status=created", status_code=303)

    @router.get("/{schedule_id}/edit", response_class=HTMLResponse, include_in_schema=False)
    async def edit_schedule_page(
        schedule_id: int,
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        schedule = get_schedule(db, schedule_id)
        ensure_can_manage(schedule, user)
        if not schedule.is_editable:
            raise HTTPException(status_code=409, detail="Zeitplan ist nicht mehr bearbeitbar")
        timezone = request.app.state.timezone
        return render_schedule_form(
            templates,
            request,
            db,
            schedule=schedule,
            values={
                "title": schedule.title,
                "file_name_base": schedule.file_name_base,
                "stream_id": str(schedule.stream_id),
                "starts_at": datetime_local_value(schedule.starts_at, timezone),
                "ends_at": datetime_local_value(schedule.ends_at, timezone),
                "recorder": schedule.recorder,
                "file_type": schedule.file_type,
            },
        )

    @router.post("/{schedule_id}", response_class=HTMLResponse, include_in_schema=False)
    async def edit_schedule(
        schedule_id: int,
        request: Request,
        title: str = Form(..., max_length=128),
        file_name_base: str | None = Form(None, max_length=128),
        stream_id: int = Form(...),
        recorder: str | None = Form(None, max_length=32),
        file_type: str | None = Form(None, max_length=16),
        starts_at: str = Form(..., max_length=32),
        ends_at: str = Form(..., max_length=32),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        schedule = get_schedule(db, schedule_id)
        ensure_can_manage(schedule, user)
        values = {
            "title": title,
            "file_name_base": file_name_base or "",
            "stream_id": str(stream_id),
            "recorder": recorder or "",
            "file_type": file_type or "",
            "starts_at": starts_at,
            "ends_at": ends_at,
        }
        try:
            stream = get_stream(db, stream_id)
            selected_recorder = recorder or stream.preferred_recorder
            selected_file_type = file_type or stream.preferred_file_type
            values["recorder"] = selected_recorder
            values["file_type"] = selected_file_type
            timezone = request.app.state.timezone
            update_schedule(
                db,
                schedule,
                stream=stream,
                title=title,
                file_name_base=file_name_base,
                recorder=selected_recorder,
                file_type=selected_file_type,
                starts_at=parse_local_datetime(starts_at, timezone, "Die Startzeit"),
                ends_at=parse_local_datetime(ends_at, timezone, "Die Endzeit"),
                actor=user,
                ip_address=client_ip(request),
            )
        except ScheduleInputError as exc:
            return render_schedule_form(
                templates,
                request,
                db,
                schedule=schedule,
                values=values,
                error=str(exc),
                status_code=400,
            )
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        scheduler.wake()
        return RedirectResponse(url="/?status=updated", status_code=303)

    @router.post("/{schedule_id}/cancel", include_in_schema=False)
    async def remove_schedule(
        schedule_id: int,
        request: Request,
        discard_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_discard_confirmation(discard_confirmed)
        schedule = get_schedule(db, schedule_id)
        ensure_can_manage(schedule, user)
        try:
            cancel_schedule(
                db,
                schedule,
                actor=user,
                ip_address=client_ip(request),
            )
        except ScheduleInputError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        scheduler.wake()
        return RedirectResponse(url="/?status=discarded", status_code=303)

    @router.post("/{schedule_id}/stop", include_in_schema=False)
    async def stop_schedule(
        schedule_id: int,
        request: Request,
        return_to: str = Form("/", max_length=32),
        stop_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_stop_confirmation(stop_confirmed)
        schedule = get_schedule(db, schedule_id)
        ensure_can_manage(schedule, user)
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        try:
            scheduler.stop_schedule(
                schedule.id,
                actor=user,
                ip_address=client_ip(request),
            )
        except ScheduleInputError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        destination = return_to if return_to in {"/", "/recordings"} else "/"
        return RedirectResponse(url=f"{destination}?status=stopped", status_code=303)

    @router.post("/{schedule_id}/delete", include_in_schema=False)
    async def delete_schedule_entry(
        schedule_id: int,
        request: Request,
        delete_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_delete_confirmation(delete_confirmed)
        schedule = get_schedule(db, schedule_id)
        ensure_can_manage(schedule, user)
        try:
            hide_schedule(
                db,
                schedule,
                actor=user,
                ip_address=client_ip(request),
            )
        except ScheduleInputError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return RedirectResponse(url="/history?status=deleted", status_code=303)

    return router


def render_planning(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
) -> HTMLResponse:
    timezone = request.app.state.timezone
    local_today = utc_now().replace(tzinfo=UTC).astimezone(ZoneInfo(timezone)).date()
    schedule_options = (
        joinedload(RecordingSchedule.stream),
        joinedload(RecordingSchedule.created_by),
    )
    running_schedules = list(
        db.scalars(
            select(RecordingSchedule)
            .options(*schedule_options)
            .where(
                RecordingSchedule.status == "running",
                RecordingSchedule.is_hidden.is_(False),
            )
            .order_by(RecordingSchedule.starts_at, RecordingSchedule.id)
        )
    )
    upcoming_schedules = list(
        db.scalars(
            select(RecordingSchedule)
            .options(*schedule_options)
            .where(
                RecordingSchedule.status == "scheduled",
                RecordingSchedule.is_hidden.is_(False),
                RecordingSchedule.recurrence_id.is_(None),
            )
            .order_by(RecordingSchedule.starts_at, RecordingSchedule.id)
        )
    )
    recurring_schedules = list(
        db.scalars(
            select(RecurringSchedule)
            .options(
                joinedload(RecurringSchedule.stream),
                joinedload(RecurringSchedule.created_by),
            )
            .where(
                RecurringSchedule.is_hidden.is_(False),
                (RecurringSchedule.valid_until.is_(None))
                | (RecurringSchedule.valid_until >= local_today),
            )
            .order_by(RecurringSchedule.is_active.desc(), RecurringSchedule.title)
        )
    )
    active_recordings = list(
        db.scalars(
            select(Recording)
            .options(joinedload(Recording.started_by))
            .where(
                Recording.status.in_(ACTIVE_RECORDING_STATUSES),
            )
            .order_by(Recording.started_at.desc(), Recording.id.desc())
        )
    )
    running_schedule_ids = {schedule.id for schedule in running_schedules}
    schedule_attempts = (
        list(
            db.scalars(
                select(Recording)
                .options(joinedload(Recording.started_by))
                .where(Recording.schedule_id.in_(running_schedule_ids))
                .order_by(Recording.started_at, Recording.id)
            )
        )
        if running_schedule_ids
        else []
    )
    group_inputs = schedule_attempts + [
        recording for recording in active_recordings if recording.schedule_id is None
    ]
    recording_manager = request.app.state.recording_manager
    active_groups = recording_manager.recording_groups(db, group_inputs)
    running_recordings: dict[int, RecordingGroup] = {}
    for recording in active_groups:
        if recording.schedule_id in running_schedule_ids:
            running_recordings.setdefault(recording.schedule_id, recording)
    running_entries: list[dict[str, RecordingSchedule | RecordingGroup | None]] = [
        {
            "schedule": schedule,
            "recording": running_recordings.get(schedule.id),
        }
        for schedule in running_schedules
    ]
    running_entries.extend(
        {"schedule": None, "recording": recording}
        for recording in active_groups
        if recording.schedule_id is None and recording.is_running
    )
    running_entries.sort(
        key=lambda entry: (
            entry["recording"].started_at
            if isinstance(entry["recording"], RecordingGroup)
            else entry["schedule"].starts_at
            if isinstance(entry["schedule"], RecordingSchedule)
            else utc_now()
        ),
        reverse=True,
    )
    return templates.TemplateResponse(
        request=request,
        name="schedules/list.html",
        context=template_context(
            request,
            running_entries=running_entries,
            upcoming_schedules=upcoming_schedules,
            recurring_schedules=recurring_schedules,
            local_today=local_today,
            status_labels=STATUS_LABELS,
            recorder_label=recorder_label,
            notice=STATUS_MESSAGES.get(request.query_params.get("status", "")),
        ),
    )


def render_history(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
) -> HTMLResponse:
    schedules = list(
        db.scalars(
            select(RecordingSchedule)
            .options(
                joinedload(RecordingSchedule.stream),
                joinedload(RecordingSchedule.created_by),
            )
            .where(
                RecordingSchedule.status.in_(HISTORY_SCHEDULE_STATUSES),
                RecordingSchedule.is_hidden.is_(False),
            )
            .order_by(RecordingSchedule.starts_at.desc(), RecordingSchedule.id.desc())
            .limit(500)
        )
    )
    return templates.TemplateResponse(
        request=request,
        name="schedules/history.html",
        context=template_context(
            request,
            schedules=schedules,
            status_labels=STATUS_LABELS,
            recorder_label=recorder_label,
            notice=STATUS_MESSAGES.get(request.query_params.get("status", "")),
        ),
    )


def get_stream(db: Session, stream_id: int) -> Stream:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise ScheduleInputError("Der ausgewählte Stream wurde nicht gefunden.")
    return stream


def get_schedule(db: Session, schedule_id: int) -> RecordingSchedule:
    schedule = db.get(RecordingSchedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Zeitplan nicht gefunden")
    return schedule


def ensure_can_manage(schedule: RecordingSchedule, user: User) -> None:
    if not user.is_admin and schedule.created_by_id != user.id:
        raise AuthorizationDenied


def render_schedule_form(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
    *,
    values: dict[str, str],
    schedule: RecordingSchedule | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    streams = sorted(
        db.scalars(select(Stream)),
        key=lambda stream: stream_name_sort_key(stream.name),
    )
    return templates.TemplateResponse(
        request=request,
        name="schedules/form.html",
        context=template_context(
            request,
            schedule=schedule,
            streams=streams,
            values=values,
            recorder_choices=RECORDER_CHOICES,
            file_type_choices=FILE_TYPE_CHOICES,
            timezone=request.app.state.timezone,
            error=error,
        ),
        status_code=status_code,
    )
