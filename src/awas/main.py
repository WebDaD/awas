from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context
from jinja2.runtime import Context
from sqlalchemy import delete, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from awas import __version__
from awas.auth.tokens import session_cookie_name
from awas.config import Settings, get_settings
from awas.db.session import create_database_engine, create_session_factory
from awas.models import User, WebSession
from awas.models.auth import utc_now
from awas.services.auth import resolve_web_session
from awas.services.database_backup import DatabaseBackupManager, sqlite_database_path
from awas.services.recorder_settings import ensure_recorder_settings
from awas.services.recording import RecordingManager
from awas.services.retention import RetentionManager, ensure_retention_policy
from awas.services.scheduling import RecordingScheduler
from awas.services.storage_settings import ensure_storage_configuration
from awas.web.auth import build_auth_router
from awas.web.dependencies import (
    AuthenticationRequired,
    AuthorizationDenied,
    CsrfValidationFailed,
    PasswordChangeRequired,
    database,
    require_user,
    template_context,
)
from awas.web.history import build_history_router
from awas.web.recorder_admin import build_recorder_admin_router
from awas.web.recordings import build_recording_router
from awas.web.recurring import build_recurring_router
from awas.web.schedules import build_schedule_router, render_planning
from awas.web.storage import build_storage_router
from awas.web.streams import build_stream_router
from awas.web.users import build_user_router

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")
logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    engine = create_database_engine(app_settings.database.url)
    session_factory = create_session_factory(engine)
    recording_manager = RecordingManager(
        session_factory,
        app_settings.recording.directory,
        app_settings.general.timezone,
    )
    recording_scheduler = RecordingScheduler(
        session_factory,
        recording_manager,
        app_settings.general.timezone,
    )
    retention_manager = RetentionManager(session_factory, recording_manager)
    database_backup_manager = DatabaseBackupManager(
        sqlite_database_path(app_settings.database.url)
    )

    @pass_context
    def local_datetime(context: Context, value: datetime) -> str:
        request = context.get("request")
        timezone = (
            request.app.state.timezone
            if isinstance(request, Request)
            else app_settings.general.timezone
        )
        return (
            value.replace(tzinfo=UTC)
            .astimezone(ZoneInfo(timezone))
            .strftime("%d.%m.%Y %H:%M")
        )

    def duration(value: int) -> str:
        hours, remainder = divmod(max(0, value), 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def filesize(value: int) -> str:
        size = float(max(0, value))
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TiB"

    templates.env.filters["local_datetime"] = local_datetime
    templates.env.filters["duration"] = duration
    templates.env.filters["filesize"] = filesize

    @asynccontextmanager
    async def lifespan(lifespan_app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        try:
            with engine.begin() as connection:
                connection.execute(text("SELECT 1"))
                connection.execute(delete(WebSession).where(WebSession.expires_at <= utc_now()))
        except SQLAlchemyError:
            logger.exception("Database startup check failed")
            raise
        with session_factory() as db:
            ensure_retention_policy(db)
            ensure_recorder_settings(db)
            storage_configuration = ensure_storage_configuration(
                db,
                app_settings.recording.directory,
                app_settings.general.timezone,
            )
            recording_manager.set_recording_directory(
                Path(storage_configuration.recording_directory)
            )
            recording_manager.set_timezone(storage_configuration.timezone)
            recording_scheduler.set_timezone(storage_configuration.timezone)
            lifespan_app.state.timezone = storage_configuration.timezone
        recording_manager.reconcile_staged_deletions()
        recording_manager.reconcile_interrupted()
        recording_scheduler.start()
        retention_manager.start()
        logger.info("AWAS %s started", __version__)
        try:
            yield
        finally:
            retention_manager.shutdown()
            recording_scheduler.shutdown()
            recording_manager.shutdown()
            engine.dispose()

    app = FastAPI(
        title="AWAS",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = app_settings
    app.state.timezone = app_settings.general.timezone
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.recording_manager = recording_manager
    app.state.recording_scheduler = recording_scheduler
    app.state.retention_manager = retention_manager
    app.state.database_backup_manager = database_backup_manager

    @app.middleware("http")
    async def session_and_security_middleware(request: Request, call_next):
        db = session_factory()
        request.state.db = db
        request.state.user = None
        request.state.web_session = None
        clear_session_cookie = False
        https_request = request.url.scheme == "https"
        secure_cookie = https_request or app_settings.security.session_cookie_secure
        active_session_cookie = session_cookie_name(https=https_request)
        raw_session_token = request.cookies.get(active_session_cookie)
        try:
            if raw_session_token:
                web_session = resolve_web_session(db, raw_session_token)
                if web_session is not None:
                    request.state.web_session = web_session
                    request.state.user = web_session.user
                else:
                    clear_session_cookie = True
            response = await call_next(request)
        finally:
            db.close()

        if clear_session_cookie:
            response.delete_cookie(
                active_session_cookie,
                path="/",
                secure=secure_cookie,
                httponly=True,
                samesite="lax",
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if not request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(AuthenticationRequired)
    async def authentication_required(_: Request, exc: AuthenticationRequired) -> RedirectResponse:
        return RedirectResponse(url=f"/login?next={quote(exc.next_url, safe='/')}", status_code=303)

    @app.exception_handler(PasswordChangeRequired)
    async def password_change_required(_: Request, __: PasswordChangeRequired) -> RedirectResponse:
        return RedirectResponse(url="/account/password?required=1", status_code=303)

    @app.exception_handler(AuthorizationDenied)
    async def authorization_denied(request: Request, _: AuthorizationDenied) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context=template_context(
                request,
                title="Zugriff verweigert",
                message="Für diese Seite sind Administratorrechte erforderlich.",
            ),
            status_code=403,
        )

    @app.exception_handler(CsrfValidationFailed)
    async def csrf_failed(request: Request, _: CsrfValidationFailed) -> HTMLResponse:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context=template_context(
                request,
                title="Anfrage abgelehnt",
                message="Das Sicherheitsmerkmal ist ungültig oder abgelaufen.",
            ),
            status_code=403,
        )

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> FileResponse:
        return FileResponse(PACKAGE_DIR / "static" / "favicon.ico", media_type="image/x-icon")

    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    app.include_router(build_auth_router(templates))
    app.include_router(build_stream_router(templates))
    app.include_router(build_recording_router(templates))
    app.include_router(build_recurring_router(templates))
    app.include_router(build_schedule_router(templates))
    app.include_router(build_history_router(templates))
    app.include_router(build_storage_router(templates))
    app.include_router(build_recorder_admin_router(templates))
    app.include_router(build_user_router(templates))

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def planning_home(
        request: Request,
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        return render_planning(templates, request, db)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        database_status = "ok"
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except SQLAlchemyError:
            database_status = "error"
        return {
            "status": "ok" if database_status == "ok" else "degraded",
            "version": __version__,
            "database": database_status,
        }

    return app


app = create_app()
