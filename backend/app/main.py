"""Main FastAPI application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.endpoints import (
    admin,
    auth,
    expertise,
    health,
    knowbase,
    members,
    organisations,
)
from app.core.config import settings
from app.core.csrf import CSRFMiddleware
from app.core.exceptions import register_exception_handlers
from app.core.logging import REQUEST_ID_HEADER, RequestIdMiddleware, configure_logging
from app.core.rate_limit import RateLimitMiddleware
from app.db import session as db_session
from app.services import turnstile
from app.services.knowbase import KnowbaseClient


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging(settings)
    app.state.knowbase = KnowbaseClient()
    try:
        yield
    finally:
        await app.state.knowbase.aclose()
    await turnstile.aclose_client()
    await db_session.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description="Blog and forum hub for flood-management stakeholders (URBANFLOODS D.5.1.1)",
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if settings.ENABLE_DOCS else None,
        docs_url="/docs" if settings.ENABLE_DOCS else None,
        redoc_url=None,
        lifespan=lifespan,
    )

    # Each add_middleware wraps the previous ones, so the order on a request is:
    # RequestId -> CORS -> RateLimit -> CSRF -> routes. Rate limiting and CSRF sit inside CORS so
    # the browser can read their 429/403 bodies; CSRF rejections still count against the limits.
    app.add_middleware(CSRFMiddleware)
    app.add_middleware(RateLimitMiddleware)
    # allow_headers "*" mirrors the preflight's requested headers, which covers the
    # X-Requested-With header the CSRF middleware requires.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )
    # Added last, so it is outermost: every response, including CORS preflights, gets an id.
    app.add_middleware(RequestIdMiddleware)

    register_exception_handlers(app)

    # Probes are mounted without the API prefix.
    app.include_router(health.router, tags=["health"])
    app.include_router(auth.router, prefix=f"{settings.API_V1_PREFIX}/auth", tags=["auth"])
    app.include_router(
        organisations.router,
        prefix=f"{settings.API_V1_PREFIX}/organisations",
        tags=["organisations"],
    )
    app.include_router(
        expertise.router, prefix=f"{settings.API_V1_PREFIX}/expertise", tags=["expertise"]
    )
    app.include_router(members.router, prefix=f"{settings.API_V1_PREFIX}/members", tags=["members"])
    app.include_router(admin.router, prefix=f"{settings.API_V1_PREFIX}/admin", tags=["admin"])
    app.include_router(
        knowbase.router, prefix=f"{settings.API_V1_PREFIX}/knowbase", tags=["knowbase"]
    )

    return app


app = create_app()
