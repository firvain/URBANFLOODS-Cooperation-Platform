"""Uniform error responses.

Every error body is ``{"detail": {"code": "<dotted.code>", "message": "<English fallback>",
"fields": {<field>: "<code>"}?}}``. The frontend translates ``code`` (and each field code); the
message is only a fallback for API users.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from starlette.exceptions import HTTPException as StarletteHTTPException

VALIDATION_CODE = "validation.failed"
VALIDATION_MESSAGE = "The request is invalid."
# Key used in ``fields`` for errors that belong to the whole body (e.g. a model validator).
ROOT_FIELD = "__root__"

log = structlog.get_logger(__name__)


def error_body(code: str, message: str, fields: dict[str, str] | None = None) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return {"detail": detail}


class AppError(Exception):
    """An error with a client-facing code. Raise it from endpoints or crud."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str | None = None,
        fields: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message or code
        self.fields = fields
        super().__init__(code)


def validation_error(fields: dict[str, str], message: str = VALIDATION_MESSAGE) -> AppError:
    """A 422 ``validation.failed`` raised by application code (same shape as pydantic's)."""
    return AppError(422, VALIDATION_CODE, message, fields)


def _field_path(loc: tuple[Any, ...] | list[Any]) -> str:
    parts = list(loc)
    if parts and parts[0] == "body":
        parts = parts[1:]
    return ".".join(str(part) for part in parts) or ROOT_FIELD


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        status_code=exc.status_code, content=error_body(exc.code, exc.message, exc.fields)
    )


async def request_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    fields: dict[str, str] = {}
    for error in exc.errors():
        # First error per field wins (a union can report several for one field).
        fields.setdefault(_field_path(error.get("loc", ())), str(error.get("type", "invalid")))
    return JSONResponse(
        status_code=422, content=error_body(VALIDATION_CODE, VALIDATION_MESSAGE, fields)
    )


async def http_exception_handler(request: Request, exc: Exception) -> Response:
    assert isinstance(exc, StarletteHTTPException)
    headers = getattr(exc, "headers", None)
    if not is_body_allowed_for_status_code(exc.status_code):
        return Response(status_code=exc.status_code, headers=headers)
    if isinstance(exc.detail, dict):
        content: dict[str, Any] = {"detail": exc.detail}
    else:
        content = error_body(f"http.{exc.status_code}", str(exc.detail))
    return JSONResponse(status_code=exc.status_code, content=content, headers=headers)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Starlette's ServerErrorMiddleware still re-raises, so the traceback reaches the server log.
    log.error("unhandled_exception", error=type(exc).__name__, path=request.url.path)
    return JSONResponse(
        status_code=500, content=error_body("server.error", "Internal server error.")
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
