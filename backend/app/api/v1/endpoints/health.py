"""Liveness and readiness probes (mounted without the API prefix)."""

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from app.api.v1.schemas.health import HealthResponse, ReadinessResponse
from app.core.config import settings
from app.db import session as db_session

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Liveness: the process is up. Does not touch the database."""
    return HealthResponse(status="ok", version=settings.VERSION, env=settings.ENV)


@router.get(
    "/health/ready",
    response_model=ReadinessResponse,
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
async def health_ready() -> ReadinessResponse | JSONResponse:
    """Readiness: the database answers ``SELECT 1``; 503 otherwise."""
    if await db_session.check_database():
        return ReadinessResponse(status="ok", database="ok")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content=ReadinessResponse(status="degraded", database="error").model_dump(),
    )
