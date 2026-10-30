from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.db import session as db_session_module

UNREACHABLE_DB = "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"


async def test_health_returns_ok(client):
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": settings.VERSION, "env": "test"}


async def test_health_ready_when_db_reachable(client, database_url):
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def test_health_ready_reports_db_failure(client, monkeypatch):
    broken_engine = create_async_engine(UNREACHABLE_DB, pool_pre_ping=True)
    monkeypatch.setattr(db_session_module, "engine", broken_engine)
    try:
        response = await client.get("/health/ready")
    finally:
        await broken_engine.dispose()

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "database": "error"}


async def test_openapi_served_under_api_prefix(client):
    response = await client.get("/api/v1/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"] == settings.PROJECT_NAME


async def test_cors_allows_dev_origin(client):
    response = await client.options(
        "/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert response.headers["access-control-allow-credentials"] == "true"
