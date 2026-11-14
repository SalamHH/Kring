"""GET /v1/health: liveness and the last successful Politiloggen poll (§8.3, §8.6)."""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.deps import Session

log = logging.getLogger(__name__)
router = APIRouter(prefix="/v1", tags=["health"])


class Health(BaseModel):
    status: Literal["ok", "stale", "db_unavailable"]
    last_success_at: datetime | None
    age_s: int | None


@router.get("/health", response_model=Health, responses={503: {"model": Health}})
async def health(request: Request, session: Session) -> JSONResponse:
    try:
        row = (
            await session.execute(
                text(
                    "SELECT last_success_at, EXTRACT(EPOCH FROM now() - last_success_at) AS age "
                    "FROM ingest_state WHERE id"
                )
            )
        ).one_or_none()
    except SQLAlchemyError:
        log.exception("health: database unavailable")
        with contextlib.suppress(SQLAlchemyError):
            await session.rollback()
        body = Health(status="db_unavailable", last_success_at=None, age_s=None)
        return JSONResponse(body.model_dump(mode="json"), 503)
    last = row.last_success_at if row else None
    age = int(row.age) if row and row.age is not None else None
    stale = age is None or age > request.app.state.settings.health_stale_after_s
    body = Health(status="stale" if stale else "ok", last_success_at=last, age_s=age)
    return JSONResponse(body.model_dump(mode="json"), 503 if stale else 200)
