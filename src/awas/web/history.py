from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from awas.models import User
from awas.web.dependencies import database, require_user, selected_user_filter
from awas.web.schedules import render_history


def build_history_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/history", response_class=HTMLResponse, include_in_schema=False)
    async def history_page(
        request: Request,
        page: int = Query(1, ge=1),
        q: str = Query("", max_length=256),
        user_id: str | None = Query(None, max_length=20),
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        selected_user_id = selected_user_filter(request, db, value=user_id)
        return render_history(
            templates,
            request,
            db,
            page=page,
            filter_query=q,
            filter_user_id=selected_user_id,
        )

    return router
