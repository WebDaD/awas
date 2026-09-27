from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from awas.models import RecurringSchedule, Stream, User
from awas.services.recorders import FILE_TYPE_CHOICES, RECORDER_CHOICES
from awas.services.recurrence import (
    RecurringInputError,
    calculate_duration,
    create_recurring_schedule,
    hide_recurring_schedule,
    parse_clock,
    parse_date,
    parse_weekday_mask,
    set_recurring_schedule_active,
    update_recurring_schedule,
)
from awas.services.scheduling import RecordingScheduler
from awas.services.streams import stream_name_sort_key
from awas.web.dependencies import (
    AuthorizationDenied,
    client_ip,
    database,
    require_user,
    template_context,
    validate_csrf,
    validate_delete_confirmation,
)

WEEKDAY_OPTIONS = (
    (0, "Montag"),
    (1, "Dienstag"),
    (2, "Mittwoch"),
    (3, "Donnerstag"),
    (4, "Freitag"),
    (5, "Samstag"),
    (6, "Sonntag"),
)
RECURRENCE_TYPE_OPTIONS = (
    ("hourly", "Stündlich"),
    ("daily", "Täglich"),
    ("weekly", "Wöchentlich"),
    ("monthly_day", "Monatlich an einem Kalendertag"),
    ("monthly_weekday", "Monatlich nach Wochentag"),
)
MONTH_WEEK_OPTIONS = (
    (1, "Erster"),
    (2, "Zweiter"),
    (3, "Dritter"),
    (4, "Vierter"),
    (5, "Fünfter"),
    (-1, "Letzter"),
)


def build_recurring_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/schedules/recurring")

    @router.get("/new", response_class=HTMLResponse, include_in_schema=False)
    async def new_recurring_page(
        request: Request,
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        return render_recurring_form(
            templates,
            request,
            db,
            values={
                "title": "",
                "file_name_base": "",
                "stream_id": "",
                "recorder": "",
                "file_type": "",
                "recurrence_type": "",
                "interval_count": "",
                "weekdays": [],
                "month_day": "",
                "month_week": "",
                "month_weekday": "",
                "start_time": "",
                "end_time": "",
                "valid_from": "",
                "valid_until": "",
            },
        )

    @router.post("", response_class=HTMLResponse, include_in_schema=False)
    async def add_recurring(
        request: Request,
        title: str = Form(..., max_length=128),
        file_name_base: str | None = Form(None, max_length=128),
        stream_id: int = Form(...),
        recorder: str | None = Form(None, max_length=32),
        file_type: str | None = Form(None, max_length=16),
        recurrence_type: str = Form("weekly", max_length=24),
        interval_count: str = Form("1", max_length=3),
        weekdays: list[str] = Form(default=[]),
        month_day: str = Form("", max_length=2),
        month_week: str = Form("", max_length=2),
        month_weekday: str = Form("", max_length=1),
        start_time: str = Form(..., max_length=5),
        end_time: str = Form(..., max_length=5),
        valid_from: str = Form(..., max_length=10),
        valid_until: str = Form("", max_length=10),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        values = recurring_values(
            title,
            file_name_base or "",
            stream_id,
            recorder or "",
            file_type or "",
            recurrence_type,
            interval_count,
            weekdays,
            month_day,
            month_week,
            month_weekday,
            start_time,
            end_time,
            valid_from,
            valid_until,
        )
        try:
            stream = get_stream(db, stream_id)
            selected_recorder = recorder or stream.preferred_recorder
            selected_file_type = file_type or stream.preferred_file_type
            values["recorder"] = selected_recorder
            values["file_type"] = selected_file_type
            start_minute = parse_clock(start_time, "Die Startzeit")
            end_minute = parse_clock(end_time, "Die Endzeit")
            parsed_interval = parse_interval_count(interval_count)
            weekday_mask, parsed_month_day, parsed_month_week = parse_recurrence_pattern(
                recurrence_type,
                weekdays=weekdays,
                month_day=month_day,
                month_week=month_week,
                month_weekday=month_weekday,
            )
            create_recurring_schedule(
                db,
                stream=stream,
                title=title,
                file_name_base=file_name_base,
                recorder=selected_recorder,
                file_type=selected_file_type,
                recurrence_type=recurrence_type,
                interval_count=parsed_interval,
                weekday_mask=weekday_mask,
                month_day=parsed_month_day,
                month_week=parsed_month_week,
                start_minute=start_minute,
                duration_minutes=calculate_duration(start_minute, end_minute),
                valid_from=require_date(parse_date(valid_from, "Das Startdatum")),
                valid_until=parse_date(valid_until, "Das Enddatum", optional=True),
                timezone=request.app.state.settings.general.timezone,
                actor=user,
                ip_address=client_ip(request),
            )
        except RecurringInputError as exc:
            db.rollback()
            return render_recurring_form(
                templates,
                request,
                db,
                values=values,
                error=str(exc),
                status_code=400,
            )
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        scheduler.wake(refresh_recurring=True)
        return RedirectResponse(url="/?status=recurrence-created", status_code=303)

    @router.get("/{rule_id}/edit", response_class=HTMLResponse, include_in_schema=False)
    async def edit_recurring_page(
        rule_id: int,
        request: Request,
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        rule = get_rule(db, rule_id)
        ensure_can_manage(rule, user)
        return render_recurring_form(
            templates,
            request,
            db,
            rule=rule,
            values=values_from_rule(rule),
        )

    @router.post("/{rule_id}", response_class=HTMLResponse, include_in_schema=False)
    async def edit_recurring(
        rule_id: int,
        request: Request,
        title: str = Form(..., max_length=128),
        file_name_base: str | None = Form(None, max_length=128),
        stream_id: int = Form(...),
        recorder: str | None = Form(None, max_length=32),
        file_type: str | None = Form(None, max_length=16),
        recurrence_type: str = Form("weekly", max_length=24),
        interval_count: str = Form("1", max_length=3),
        weekdays: list[str] = Form(default=[]),
        month_day: str = Form("", max_length=2),
        month_week: str = Form("", max_length=2),
        month_weekday: str = Form("", max_length=1),
        start_time: str = Form(..., max_length=5),
        end_time: str = Form(..., max_length=5),
        valid_from: str = Form(..., max_length=10),
        valid_until: str = Form("", max_length=10),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        rule = get_rule(db, rule_id)
        ensure_can_manage(rule, user)
        values = recurring_values(
            title,
            file_name_base or "",
            stream_id,
            recorder or "",
            file_type or "",
            recurrence_type,
            interval_count,
            weekdays,
            month_day,
            month_week,
            month_weekday,
            start_time,
            end_time,
            valid_from,
            valid_until,
        )
        try:
            stream = get_stream(db, stream_id)
            selected_recorder = recorder or stream.preferred_recorder
            selected_file_type = file_type or stream.preferred_file_type
            values["recorder"] = selected_recorder
            values["file_type"] = selected_file_type
            start_minute = parse_clock(start_time, "Die Startzeit")
            end_minute = parse_clock(end_time, "Die Endzeit")
            parsed_interval = parse_interval_count(interval_count)
            weekday_mask, parsed_month_day, parsed_month_week = parse_recurrence_pattern(
                recurrence_type,
                weekdays=weekdays,
                month_day=month_day,
                month_week=month_week,
                month_weekday=month_weekday,
            )
            update_recurring_schedule(
                db,
                rule,
                stream=stream,
                title=title,
                file_name_base=file_name_base,
                recorder=selected_recorder,
                file_type=selected_file_type,
                recurrence_type=recurrence_type,
                interval_count=parsed_interval,
                weekday_mask=weekday_mask,
                month_day=parsed_month_day,
                month_week=parsed_month_week,
                start_minute=start_minute,
                duration_minutes=calculate_duration(start_minute, end_minute),
                valid_from=require_date(parse_date(valid_from, "Das Startdatum")),
                valid_until=parse_date(valid_until, "Das Enddatum", optional=True),
                timezone=request.app.state.settings.general.timezone,
                actor=user,
                ip_address=client_ip(request),
            )
        except RecurringInputError as exc:
            db.rollback()
            return render_recurring_form(
                templates,
                request,
                db,
                rule=rule,
                values=values,
                error=str(exc),
                status_code=400,
            )
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        scheduler.wake(refresh_recurring=True)
        return RedirectResponse(url="/?status=recurrence-updated", status_code=303)

    @router.post("/{rule_id}/status", include_in_schema=False)
    async def change_recurring_status(
        rule_id: int,
        request: Request,
        enabled: str = Form(..., max_length=5),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        rule = get_rule(db, rule_id)
        ensure_can_manage(rule, user)
        activate = enabled == "true"
        try:
            set_recurring_schedule_active(
                db,
                rule,
                enabled=activate,
                timezone=request.app.state.settings.general.timezone,
                actor=user,
                ip_address=client_ip(request),
            )
        except RecurringInputError as exc:
            db.rollback()
            return templates.TemplateResponse(
                request=request,
                name="error.html",
                context=template_context(
                    request,
                    title="Wiederholung nicht aktiviert",
                    message=str(exc),
                ),
                status_code=409,
            )
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        scheduler.wake(refresh_recurring=True)
        status = "recurrence-enabled" if activate else "recurrence-disabled"
        return RedirectResponse(url=f"/?status={status}", status_code=303)

    @router.post("/{rule_id}/delete", include_in_schema=False)
    async def delete_recurring_entry(
        rule_id: int,
        request: Request,
        delete_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        user: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_delete_confirmation(delete_confirmed)
        rule = get_rule(db, rule_id)
        ensure_can_manage(rule, user)
        try:
            hide_recurring_schedule(
                db,
                rule,
                actor=user,
                ip_address=client_ip(request),
            )
        except RecurringInputError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        scheduler.wake(refresh_recurring=True)
        return RedirectResponse(url="/?status=recurrence-deleted", status_code=303)

    return router


def get_stream(db: Session, stream_id: int) -> Stream:
    stream = db.get(Stream, stream_id)
    if stream is None:
        raise RecurringInputError("Der ausgewählte Stream wurde nicht gefunden.")
    return stream


def get_rule(db: Session, rule_id: int) -> RecurringSchedule:
    rule = db.get(RecurringSchedule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Wiederholung nicht gefunden")
    return rule


def ensure_can_manage(rule: RecurringSchedule, user: User) -> None:
    if not user.is_admin and rule.created_by_id != user.id:
        raise AuthorizationDenied


def require_date(value):
    if value is None:
        raise RecurringInputError("Das Startdatum ist erforderlich.")
    return value


def recurring_values(
    title: str,
    file_name_base: str,
    stream_id: int,
    recorder: str,
    file_type: str,
    recurrence_type: str,
    interval_count: str,
    weekdays: list[str],
    month_day: str,
    month_week: str,
    month_weekday: str,
    start_time: str,
    end_time: str,
    valid_from: str,
    valid_until: str,
) -> dict[str, object]:
    selected_days = []
    for value in weekdays:
        try:
            day = int(value)
        except ValueError:
            continue
        if 0 <= day <= 6:
            selected_days.append(day)
    return {
        "title": title,
        "file_name_base": file_name_base,
        "stream_id": str(stream_id),
        "recorder": recorder,
        "file_type": file_type,
        "recurrence_type": recurrence_type,
        "interval_count": interval_count,
        "weekdays": selected_days,
        "month_day": month_day,
        "month_week": month_week,
        "month_weekday": month_weekday,
        "start_time": start_time,
        "end_time": end_time,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }


def values_from_rule(rule: RecurringSchedule) -> dict[str, object]:
    return {
        "title": rule.title,
        "file_name_base": rule.file_name_base,
        "stream_id": str(rule.stream_id),
        "recorder": rule.recorder,
        "file_type": rule.file_type,
        "recurrence_type": rule.recurrence_type,
        "interval_count": str(rule.interval_count),
        "weekdays": list(rule.weekdays),
        "month_day": str(rule.month_day) if rule.month_day is not None else "",
        "month_week": str(rule.month_week) if rule.month_week is not None else "",
        "month_weekday": (
            str(rule.weekdays[0])
            if rule.recurrence_type == "monthly_weekday" and rule.weekdays
            else ""
        ),
        "start_time": rule.start_time_label,
        "end_time": f"{rule.end_minute // 60:02d}:{rule.end_minute % 60:02d}",
        "valid_from": rule.valid_from.isoformat(),
        "valid_until": rule.valid_until.isoformat() if rule.valid_until else "",
    }


def parse_recurrence_pattern(
    recurrence_type: str,
    *,
    weekdays: list[str],
    month_day: str,
    month_week: str,
    month_weekday: str,
) -> tuple[int, int | None, int | None]:
    if recurrence_type in {"hourly", "daily"}:
        return 127, None, None
    if recurrence_type == "weekly":
        return parse_weekday_mask(weekdays), None, None
    if recurrence_type == "monthly_day":
        try:
            parsed_day = int(month_day)
        except ValueError as exc:
            raise RecurringInputError("Der Monatstag ist erforderlich.") from exc
        if parsed_day not in range(1, 32):
            raise RecurringInputError("Der Monatstag muss zwischen 1 und 31 liegen.")
        return 127, parsed_day, None
    if recurrence_type == "monthly_weekday":
        if not month_weekday:
            raise RecurringInputError("Der Wochentag ist erforderlich.")
        try:
            parsed_week = int(month_week)
        except ValueError as exc:
            raise RecurringInputError("Die Position im Monat ist erforderlich.") from exc
        return parse_weekday_mask([month_weekday]), None, parsed_week
    raise RecurringInputError("Die ausgewählte Wiederholung ist ungültig.")


def parse_interval_count(value: str) -> int:
    try:
        interval = int(value)
    except ValueError as exc:
        raise RecurringInputError("Das Wiederholungsintervall ist erforderlich.") from exc
    if not 1 <= interval <= 999:
        raise RecurringInputError(
            "Das Wiederholungsintervall muss zwischen 1 und 999 liegen."
        )
    return interval


def render_recurring_form(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
    *,
    values: dict[str, object],
    rule: RecurringSchedule | None = None,
    error: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    streams = sorted(
        db.scalars(select(Stream)),
        key=lambda stream: stream_name_sort_key(stream.name),
    )
    if rule is not None and all(stream.id != rule.stream_id for stream in streams):
        streams.append(rule.stream)
    return templates.TemplateResponse(
        request=request,
        name="schedules/recurring_form.html",
        context=template_context(
            request,
            rule=rule,
            streams=streams,
            values=values,
            weekday_options=WEEKDAY_OPTIONS,
            recurrence_type_options=RECURRENCE_TYPE_OPTIONS,
            month_week_options=MONTH_WEEK_OPTIONS,
            recorder_choices=RECORDER_CHOICES,
            file_type_choices=FILE_TYPE_CHOICES,
            timezone=request.app.state.settings.general.timezone,
            error=error,
        ),
        status_code=status_code,
    )
