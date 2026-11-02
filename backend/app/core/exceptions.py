"""Uniform error responses.

Every error body is ``{"detail": {"code": "<dotted.code>", "message": "<English fallback>",
"fields": {<field>: "<code>"}?}}``. The frontend translates ``code`` (and each field code); the
message is only a fallback for API users.
"""

from __future__ import annotations

from typing import Any

import asyncpg.exceptions
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.utils import is_body_allowed_for_status_code
from sqlalchemy.exc import DataError
from starlette.exceptions import HTTPException as StarletteHTTPException

VALIDATION_CODE = "validation.failed"
VALIDATION_MESSAGE = "The request is invalid."
# Key used in ``fields`` for errors that belong to the whole body (e.g. a model validator).
ROOT_FIELD = "__root__"
INVALID_VALUE_CODE = "request.invalid_value"
INVALID_VALUE_MESSAGE = "The request contains a value the database cannot store."

log = structlog.get_logger(__name__)


def error_body(code: str, message: str, fields: dict[str, str] | None = None) -> dict[str, Any]:
    detail: dict[str, Any] = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return {"detail": detail}


class AppError(Exception):
    """An error with a client-facing code. Raise it from endpoints or crud.

    ``keep_changes=True`` makes ``get_db_tx`` commit the request transaction instead of rolling
    it back, for errors that must leave a trace (a failed-login audit row, the revocation of a
    disabled user's session).
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str | None = None,
        fields: dict[str, str] | None = None,
        *,
        keep_changes: bool = False,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message or code
        self.fields = fields
        self.keep_changes = keep_changes
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


def asyncpg_error(exc: DataError) -> BaseException | None:
    """The asyncpg exception behind a SQLAlchemy error. SQLAlchemy's asyncpg adapter wraps it,
    so ``exc.orig`` is the adapter's exception and asyncpg's is its ``__cause__``."""
    for candidate in (exc.orig, getattr(exc.orig, "__cause__", None)):
        if isinstance(candidate, asyncpg.exceptions.PostgresError):
            return candidate
    return None


def is_invalid_value_error(exc: DataError) -> bool:
    """Whether the database refused a value the client sent: a NUL character in text (the
    server's ``CharacterNotInRepertoireError``), or an argument asyncpg could not encode before
    sending the query (its bare ``DataError``, e.g. an integer past the column's range).

    A server-side overflow (``NumericValueOutOfRangeError``) or any other data error comes from
    a value we computed: our bug, so it stays a 500.
    """
    cause = asyncpg_error(exc)
    return (
        isinstance(cause, asyncpg.exceptions.CharacterNotInRepertoireError)
        or type(cause) is asyncpg.exceptions.DataError
    )


async def db_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 ``request.invalid_value`` for values the client sent that the database refuses (the
    fallback for what validation misses). Registered for ``sqlalchemy.exc.DataError`` only
    (``db/session.py`` raises asyncpg's data errors as that), so integrity, operational and other
    database errors never pass through it. Any other data error is re-raised, so it is logged
    with its traceback and answered 500 as before."""
    assert isinstance(exc, DataError)
    if not is_invalid_value_error(exc):
        raise exc
    log.warning("invalid_value", error=type(asyncpg_error(exc)).__name__, path=request.url.path)
    return JSONResponse(
        status_code=422, content=error_body(INVALID_VALUE_CODE, INVALID_VALUE_MESSAGE)
    )


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
    app.add_exception_handler(DataError, db_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
