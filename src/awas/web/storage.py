from __future__ import annotations

from datetime import UTC
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from awas.models import ACTIVE_RECORDING_STATUSES, Recording, User, WebSession
from awas.models.auth import utc_now
from awas.services.auth import add_audit_entry
from awas.services.database_backup import (
    MAX_DATABASE_IMPORT_BYTES,
    DatabaseBackupError,
    DatabaseBackupManager,
)
from awas.services.recorder_settings import ensure_recorder_settings
from awas.services.recording import RecordingManager
from awas.services.retention import (
    MAX_DELETIONS_PER_RUN,
    RetentionInputError,
    RetentionManager,
    ensure_retention_policy,
    parse_retention_days,
    update_retention_policy,
)
from awas.services.scheduling import RecordingScheduler
from awas.services.storage_settings import (
    StorageInputError,
    ensure_storage_configuration,
    timezone_choices,
    update_recording_directory,
    update_timezone,
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
    "saved": "Die Aufbewahrungseinstellungen wurden gespeichert.",
    "directory-saved": "Der Aufnahmepfad wurde gespeichert.",
    "timezone-saved": "Die Zeitzone wurde gespeichert.",
    "cleaned": "Die Speicherbereinigung wurde abgeschlossen.",
    "partial": "Die Speicherbereinigung wurde mit Fehlern abgeschlossen.",
    "database-imported": "Die Datenbank wurde vollständig importiert.",
}


def build_storage_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter(prefix="/admin/storage")

    @router.get("", response_class=HTMLResponse, include_in_schema=False)
    async def storage_page(
        request: Request,
        _: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        return render_storage_page(
            templates,
            request,
            db,
            notice=STATUS_MESSAGES.get(request.query_params.get("status", "")),
        )

    @router.post("", response_class=HTMLResponse, include_in_schema=False)
    async def save_storage_settings(
        request: Request,
        retention_days: str = Form(..., max_length=8),
        enabled: str | None = Form(None, max_length=16),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        policy = ensure_retention_policy(db)
        enabled_value = enabled == "on"
        try:
            days = parse_retention_days(retention_days)
            update_retention_policy(
                db,
                policy,
                enabled=enabled_value,
                retention_days=days,
                actor=admin,
                ip_address=client_ip(request),
            )
        except RetentionInputError as exc:
            return render_storage_page(
                templates,
                request,
                db,
                error=str(exc),
                values={"enabled": enabled_value, "retention_days": retention_days},
                status_code=400,
            )
        if enabled_value:
            manager: RetentionManager = request.app.state.retention_manager
            manager.wake()
        return RedirectResponse(url="/admin/storage?status=saved", status_code=303)

    @router.post("/directory", response_class=HTMLResponse, include_in_schema=False)
    async def save_recording_directory(
        request: Request,
        recording_directory: str = Form(..., max_length=4096),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        configuration = ensure_storage_configuration(
            db,
            request.app.state.settings.recording.directory,
            request.app.state.settings.general.timezone,
        )
        try:
            normalized_directory = update_recording_directory(
                db,
                configuration,
                recording_directory=recording_directory,
                actor=admin,
                ip_address=client_ip(request),
            )
        except StorageInputError as exc:
            return render_storage_page(
                templates,
                request,
                db,
                error=str(exc),
                directory_value=recording_directory,
                status_code=400,
            )
        recording_manager: RecordingManager = request.app.state.recording_manager
        recording_manager.set_recording_directory(normalized_directory)
        return RedirectResponse(
            url="/admin/storage?status=directory-saved",
            status_code=303,
        )

    @router.post("/timezone", response_class=HTMLResponse, include_in_schema=False)
    async def save_timezone(
        request: Request,
        timezone: str = Form(..., max_length=64),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        configuration = ensure_storage_configuration(
            db,
            request.app.state.settings.recording.directory,
            request.app.state.settings.general.timezone,
        )
        try:
            normalized_timezone = update_timezone(
                db,
                configuration,
                timezone=timezone,
                actor=admin,
                ip_address=client_ip(request),
            )
        except StorageInputError as exc:
            return render_storage_page(
                templates,
                request,
                db,
                error=str(exc),
                timezone_value=timezone,
                status_code=400,
            )
        recording_manager: RecordingManager = request.app.state.recording_manager
        scheduler: RecordingScheduler = request.app.state.recording_scheduler
        recording_manager.set_timezone(normalized_timezone)
        scheduler.set_timezone(normalized_timezone, rebuild_pending=True)
        request.app.state.timezone = normalized_timezone
        return RedirectResponse(
            url="/admin/storage?status=timezone-saved",
            status_code=303,
        )

    @router.post("/cleanup", response_class=HTMLResponse, include_in_schema=False)
    async def run_cleanup(
        request: Request,
        delete_confirmed: str = Form("", max_length=5),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        validate_delete_confirmation(delete_confirmed)
        manager: RetentionManager = request.app.state.retention_manager
        result = manager.run_cleanup(
            mode="manual",
            actor=admin,
            ip_address=client_ip(request),
        )
        status = "partial" if result.failed_count else "cleaned"
        return RedirectResponse(url=f"/admin/storage?status={status}", status_code=303)

    @router.get("/database/export", include_in_schema=False)
    async def export_database(
        request: Request,
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> FileResponse:
        manager: DatabaseBackupManager = request.app.state.database_backup_manager
        try:
            export_path = manager.create_export()
        except DatabaseBackupError as exc:
            return render_storage_page(
                templates,
                request,
                db,
                error=str(exc),
                status_code=500,
            )
        add_audit_entry(
            db,
            "database.exported",
            actor=admin,
            target_type="database",
            ip_address=client_ip(request),
        )
        db.commit()
        timezone = ZoneInfo(request.app.state.timezone)
        timestamp = utc_now().replace(tzinfo=UTC).astimezone(timezone).strftime("%Y%m%d-%H%M%S")
        return FileResponse(
            export_path,
            filename=f"awas-database-{timestamp}.db",
            media_type="application/vnd.sqlite3",
            background=BackgroundTask(export_path.unlink, missing_ok=True),
        )

    @router.post("/database/import", response_class=HTMLResponse, include_in_schema=False)
    async def import_database(
        request: Request,
        database_file: UploadFile = File(...),
        csrf_token: str = Form(..., max_length=128),
        admin: User = Depends(require_admin),
        db: Session = Depends(database),
    ) -> Response:
        validate_csrf(request, csrf_token)
        manager: DatabaseBackupManager = request.app.state.database_backup_manager
        import_path = manager.new_import_path()
        file_size = 0
        try:
            file_size = await _write_database_upload(database_file, import_path)
            manager.validate_database(
                import_path,
                required_admin_username=admin.username,
            )
            session_values = _session_values(request)
            original_filename = Path(database_file.filename or "awas-database.db").name[:255]
            db.close()
            _install_database(
                request,
                manager,
                import_path,
                admin_username=admin.username,
                original_filename=original_filename,
                file_size=file_size,
                session_values=session_values,
            )
        except DatabaseBackupError as exc:
            with request.app.state.session_factory() as response_db:
                return render_storage_page(
                    templates,
                    request,
                    response_db,
                    error=str(exc),
                    status_code=400,
                )
        finally:
            await database_file.close()
            import_path.unlink(missing_ok=True)
        return RedirectResponse(
            url="/admin/storage?status=database-imported",
            status_code=303,
        )

    return router


def render_storage_page(
    templates: Jinja2Templates,
    request: Request,
    db: Session,
    *,
    notice: str | None = None,
    error: str | None = None,
    values: dict[str, object] | None = None,
    directory_value: str | None = None,
    timezone_value: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    policy = ensure_retention_policy(db)
    configuration = ensure_storage_configuration(
        db,
        request.app.state.settings.recording.directory,
        request.app.state.settings.general.timezone,
    )
    recording_manager: RecordingManager = request.app.state.recording_manager
    retention_manager: RetentionManager = request.app.state.retention_manager
    return templates.TemplateResponse(
        request=request,
        name="storage/index.html",
        context=template_context(
            request,
            policy=policy,
            preview=retention_manager.preview(db, policy, limit=20),
            storage=recording_manager.storage_snapshot(db),
            recording_directory=(
                directory_value
                if directory_value is not None
                else str(recording_manager.recording_directory)
            ),
            selected_timezone=(
                timezone_value if timezone_value is not None else configuration.timezone
            ),
            timezone_choices=timezone_choices(),
            batch_limit=MAX_DELETIONS_PER_RUN,
            max_database_import_mib=MAX_DATABASE_IMPORT_BYTES // (1024 * 1024),
            notice=notice,
            error=error,
            values=values,
        ),
        status_code=status_code,
    )


async def _write_database_upload(database_file: UploadFile, destination: Path) -> int:
    total = 0
    try:
        with destination.open("wb") as target:
            while chunk := await database_file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_DATABASE_IMPORT_BYTES:
                    raise DatabaseBackupError(
                        "Die Datenbankdatei ist größer als "
                        f"{MAX_DATABASE_IMPORT_BYTES // (1024 * 1024)} MiB."
                    )
                target.write(chunk)
    except DatabaseBackupError:
        raise
    except OSError as exc:
        raise DatabaseBackupError(
            "Die hochgeladene Datei konnte nicht gespeichert werden."
        ) from exc
    if total == 0:
        raise DatabaseBackupError("Die hochgeladene Datenbankdatei ist leer.")
    return total


def _session_values(request: Request) -> dict[str, object]:
    web_session = request.state.web_session
    if web_session is None:
        raise DatabaseBackupError("Die Administratorsitzung ist nicht mehr gültig.")
    return {
        "token_hash": web_session.token_hash,
        "created_at": web_session.created_at,
        "last_seen_at": web_session.last_seen_at,
        "expires_at": web_session.expires_at,
        "ip_address": web_session.ip_address,
        "user_agent": web_session.user_agent,
    }


def _install_database(
    request: Request,
    manager: DatabaseBackupManager,
    import_path: Path,
    *,
    admin_username: str,
    original_filename: str,
    file_size: int,
    session_values: dict[str, object],
) -> None:
    scheduler: RecordingScheduler = request.app.state.recording_scheduler
    retention_manager: RetentionManager = request.app.state.retention_manager
    recording_manager: RecordingManager = request.app.state.recording_manager
    session_factory = request.app.state.session_factory
    engine = request.app.state.engine
    rollback = None
    scheduler.shutdown()
    retention_manager.shutdown()
    try:
        with session_factory() as current_db:
            active_count = current_db.scalar(
                select(func.count(Recording.id)).where(
                    Recording.status.in_(ACTIVE_RECORDING_STATUSES)
                )
            )
        if active_count:
            raise DatabaseBackupError(
                "Die Datenbank kann nicht importiert werden, solange Aufnahmen laufen."
            )

        engine.dispose()
        rollback = manager.install_import(import_path)
        try:
            with session_factory() as imported_db:
                imported_admin = imported_db.scalar(
                    select(User).where(
                        User.username == admin_username,
                        User.role == "admin",
                        User.is_active.is_(True),
                    )
                )
                if imported_admin is None:
                    raise DatabaseBackupError(
                        "Das Administratorkonto ist in der importierten Datenbank nicht verfügbar."
                    )
                ensure_retention_policy(imported_db)
                ensure_recorder_settings(imported_db)
                storage_configuration = ensure_storage_configuration(
                    imported_db,
                    request.app.state.settings.recording.directory,
                    request.app.state.settings.general.timezone,
                )
                imported_db.execute(delete(WebSession))
                imported_db.add(
                    WebSession(
                        user_id=imported_admin.id,
                        **session_values,
                    )
                )
                add_audit_entry(
                    imported_db,
                    "database.imported",
                    actor=imported_admin,
                    target_type="database",
                    ip_address=client_ip(request),
                    details={
                        "file_name": original_filename,
                        "file_size_bytes": file_size,
                    },
                )
                imported_db.commit()
                recording_directory = Path(storage_configuration.recording_directory)
                recording_timezone = storage_configuration.timezone
            recording_manager.set_recording_directory(recording_directory)
            recording_manager.set_timezone(recording_timezone)
            scheduler.set_timezone(recording_timezone)
            request.app.state.timezone = recording_timezone
            recording_manager.reconcile_staged_deletions()
            recording_manager.reconcile_interrupted()
        except Exception:
            engine.dispose()
            manager.restore_import(rollback)
            rollback = None
            raise
        manager.finish_import(rollback)
        rollback = None
    except DatabaseBackupError:
        raise
    except Exception as exc:
        raise DatabaseBackupError("Die Datenbank konnte nicht importiert werden.") from exc
    finally:
        if rollback is not None:
            engine.dispose()
            manager.restore_import(rollback)
        with session_factory() as runtime_db:
            storage_configuration = ensure_storage_configuration(
                runtime_db,
                request.app.state.settings.recording.directory,
                request.app.state.settings.general.timezone,
            )
            recording_manager.set_recording_directory(
                Path(storage_configuration.recording_directory)
            )
            recording_manager.set_timezone(storage_configuration.timezone)
            scheduler.set_timezone(storage_configuration.timezone)
            request.app.state.timezone = storage_configuration.timezone
        scheduler.start()
        scheduler.wake(refresh_recurring=True)
        retention_manager.start()
