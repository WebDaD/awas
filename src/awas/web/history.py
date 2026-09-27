from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from awas.models import User
from awas.web.dependencies import database, require_user
from awas.web.schedules import render_history


def build_history_router(templates: Jinja2Templates) -> APIRouter:
    router = APIRouter()

    @router.get("/history", response_class=HTMLResponse, include_in_schema=False)
    async def history_page(
        request: Request,
        _: User = Depends(require_user),
        db: Session = Depends(database),
    ) -> HTMLResponse:
        return render_history(templates, request, db)

    return router
