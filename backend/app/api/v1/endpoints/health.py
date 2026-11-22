from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.deps import DbSession

router = APIRouter(prefix="/health", tags=["Health"])


@router.get("/live", summary="Liveness probe")
def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", summary="Readiness probe (checks the database)")
def ready(db: DbSession) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - exercised against a down database
        return JSONResponse({"status": "unavailable", "database": str(exc)[:200]}, status_code=503)
    return JSONResponse({"status": "ok", "database": "ok"})
