"""7n (#13): ids past a column's range and NUL characters answer 422, never 500.

Path and query ids are bounded by the shared aliases in ``app/api/v1/params.py``; what they miss
(a NUL in text, an id in a body) is caught by the ``DBAPIError`` handler in
``core/exceptions.py`` and answered with 422 ``request.invalid_value``.
"""

from __future__ import annotations

import typing
from types import UnionType
from typing import Annotated, Any

import annotated_types
import asyncpg.exceptions
import pytest
from fastapi import Path, Query
from fastapi.routing import APIRoute
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.enums import CategoryKind
from tests.factories import create_category, create_superadmin, login_as

API = settings.API_V1_PREFIX
INT_OVER = 2**31  # one past INTEGER
BIGINT_OVER = 2**63  # one past BIGINT
INVALID_VALUE = "request.invalid_value"
VALIDATION = "validation.failed"


async def _superadmin(client, db, cleanup_users):
    user = await create_superadmin(db)
    cleanup_users.add(user.email)
    await db.commit()
    await login_as(client, user)
    return user


def _assert_id_rejected(response, param: str) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == VALIDATION, detail
    assert any(param in key.split(".") for key in detail.get("fields", {})), detail


# (method, path template, the id parameter, JSON body or None). ``{id}`` is replaced.
INTEGER_ID_CASES: list[tuple[str, str, str, dict[str, Any] | None]] = [
    ("PATCH", "/posts/{id}", "post_id", {"title": "A valid title"}),
    ("DELETE", "/posts/{id}", "post_id", None),
    ("GET", "/posts/?author_id={id}", "author_id", None),
    ("PATCH", "/threads/{id}", "thread_id", {"title": "A valid title"}),
    ("DELETE", "/threads/{id}", "thread_id", None),
    ("POST", "/threads/{id}/pin", "thread_id", None),
    ("POST", "/threads/{id}/lock", "thread_id", None),
    ("GET", "/threads/?author_id={id}", "author_id", None),
    ("GET", "/threads/mentions/measure/{id}/", "kb_id", None),
    ("GET", "/threads/{id}/replies/", "thread_id", None),
    ("POST", "/threads/{id}/replies/", "thread_id", {"body_html": "<p>Hello there</p>"}),
    ("GET", "/posts/{id}/comments/", "post_id", None),
    ("POST", "/posts/{id}/comments/", "post_id", {"body_html": "<p>Hello there</p>"}),
    ("GET", "/admin/users/{id}", "user_id", None),
    ("PATCH", "/admin/users/{id}", "user_id", {}),
    ("POST", "/admin/users/{id}/promote", "user_id", None),
    ("POST", "/admin/users/{id}/ban", "user_id", None),
    ("POST", "/admin/users/{id}/resend-verification", "user_id", None),
    ("GET", "/admin/users/?organisation_id={id}", "organisation_id", None),
    ("GET", "/members/{id}", "member_id", None),
    ("GET", "/members/?organisation_id={id}", "organisation_id", None),
    ("GET", "/members/?expertise_ids={id}", "expertise_ids", None),
    ("GET", "/organisations/{id}", "organisation_id", None),
    ("PATCH", "/organisations/{id}", "organisation_id", {}),
    ("PATCH", "/expertise/{id}", "tag_id", {}),
    ("DELETE", "/tags/{id}", "tag_id", None),
    ("POST", "/tags/{id}/merge", "tag_id", {"target_id": 1}),
    ("PATCH", "/categories/{id}", "category_id", {}),
    ("DELETE", "/categories/{id}", "category_id", None),
    ("DELETE", "/uploads/{id}", "attachment_id", None),
    ("GET", "/moderation/log/?actor_id={id}", "actor_id", None),
    ("GET", "/knowbase/measures/{id}", "measure_id", None),
]

# Replies, comments, reports (and moderation, which covers every content type) have BIGINT ids.
BIGINT_ID_CASES: list[tuple[str, str, str, dict[str, Any] | None]] = [
    ("PATCH", "/replies/{id}", "reply_id", {"body_html": "<p>Hello there</p>"}),
    ("DELETE", "/replies/{id}", "reply_id", None),
    ("PATCH", "/comments/{id}", "comment_id", {"body_html": "<p>Hello there</p>"}),
    ("DELETE", "/comments/{id}", "comment_id", None),
    ("GET", "/reports/{id}", "report_id", None),
    ("POST", "/reports/{id}/resolve", "report_id", None),
    ("POST", "/moderation/reply/{id}/hide", "content_id", None),
    ("POST", "/moderation/post/{id}/approve", "content_id", None),
]


async def _send(client, method: str, template: str, value: int, body: dict | None):
    url = API + template.replace("{id}", str(value))
    return await client.request(method, url, json=body)


@pytest.mark.parametrize(("method", "template", "param", "body"), INTEGER_ID_CASES)
async def test_integer_id_past_range_is_422(
    client, db_session, cleanup_users, method, template, param, body
):
    await _superadmin(client, db_session, cleanup_users)

    response = await _send(client, method, template, INT_OVER, body)

    _assert_id_rejected(response, param)


@pytest.mark.parametrize(("method", "template", "param", "body"), BIGINT_ID_CASES)
async def test_bigint_id_past_range_is_422(
    client, db_session, cleanup_users, method, template, param, body
):
    await _superadmin(client, db_session, cleanup_users)

    response = await _send(client, method, template, BIGINT_OVER, body)

    _assert_id_rejected(response, param)


@pytest.mark.parametrize(("method", "template", "param", "body"), BIGINT_ID_CASES)
async def test_bigint_id_past_integer_range_is_not_found(
    client, db_session, cleanup_users, method, template, param, body
):
    """2**31 fits a BIGINT bound; the row does not exist (posts and threads, INTEGER, are
    simply not found through moderation)."""
    await _superadmin(client, db_session, cleanup_users)

    response = await _send(client, method, template, INT_OVER, body)

    assert response.status_code == 404, response.text


@pytest.mark.parametrize(
    "path",
    [
        "/knowbase/documents/?level_id={id}",
        "/knowbase/documents/?keyword_ids={id}",
        "/knowbase/measures/?scale_ids={id}",
        "/knowbase/measures/lookups/keywords?category_id={id}",
        "/knowbase/lookups/keywords?subject_id={id}",
    ],
)
async def test_knowbase_filter_id_past_range_is_422(client, path):
    """Never forwarded to the KNOWBASE: no route is mocked, so any outgoing request fails."""
    import respx

    with respx.mock(assert_all_mocked=True, assert_all_called=False):
        response = await client.get(API + path.replace("{id}", str(2**40)))

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == VALIDATION


async def test_huge_skip_is_422_not_500(client):
    """``skip`` has no upper bound; asyncpg cannot encode a huge OFFSET (client-side DataError),
    which the handler answers 422 ``request.invalid_value``."""
    response = await client.get(f"{API}/posts/", params={"skip": 2**63})

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == INVALID_VALUE


@pytest.mark.parametrize("value", ["0", "-1"])
async def test_id_below_one_is_422(client, value):
    response = await client.get(f"{API}/organisations/{value}")

    _assert_id_rejected(response, "organisation_id")


# --- body ids and NUL characters (the DBAPIError fallback) ------------------------------------


async def test_tag_merge_target_past_range_is_422(client, db_session, cleanup_users):
    await _superadmin(client, db_session, cleanup_users)

    response = await client.post(f"{API}/tags/1/merge", json={"target_id": INT_OVER})

    _assert_id_rejected(response, "target_id")


async def test_report_content_id_past_bigint_is_422(client, db_session, cleanup_users):
    await _superadmin(client, db_session, cleanup_users)

    response = await client.post(
        f"{API}/reports/",
        json={"content_type": "comment", "content_id": BIGINT_OVER, "reason": "spam"},
    )

    _assert_id_rejected(response, "content_id")


def _assert_invalid_value_or_field(response) -> None:
    """422, either from the handler (``request.invalid_value``) or from validation."""
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] in {INVALID_VALUE, VALIDATION}, response.text


async def _post_category(db, cleanup_categories):
    category = await create_category(db, kind=CategoryKind.BLOG)
    cleanup_categories.add(category.id)
    await db.commit()
    return category


@pytest.mark.parametrize(
    "overrides",
    [
        {"title": "Green roofs\x00 in Kozani"},
        {"body_html": "<p>Green roofs\x00 slow down run-off.</p>"},
        {"excerpt": "Short\x00 summary"},
    ],
    ids=["title", "body", "excerpt"],
)
async def test_nul_in_post_is_422(client, db_session, cleanup_users, cleanup_categories, overrides):
    await _superadmin(client, db_session, cleanup_users)
    category = await _post_category(db_session, cleanup_categories)
    body = {
        "title": "Green roofs in Kozani",
        "body_html": "<p>Green roofs slow down stormwater run-off.</p>",
        "category_id": category.id,
        "locale": "en",
        "tags": [],
        "knowbase_links": [],
    }
    body.update(overrides)

    response = await client.post(f"{API}/posts/", json=body)

    if response.status_code == 201:
        # nh3 may replace a NUL in the body; then nothing reaches Postgres and nothing breaks.
        assert "\x00" not in response.text
        return
    _assert_invalid_value_or_field(response)


@pytest.mark.parametrize(
    "path",
    ["/search/?q=flood%00risk", "/posts/?q=flood%00risk", "/threads/?q=flood%00risk"],
)
async def test_nul_in_search_query_is_422(client, path):
    response = await client.get(API + path)

    _assert_invalid_value_or_field(response)


async def test_db_data_error_maps_to_invalid_value(client, db_session, cleanup_users):
    """The fallback itself: a NUL that reaches Postgres answers 422 ``request.invalid_value``."""
    await _superadmin(client, db_session, cleanup_users)

    response = await client.get(f"{API}/admin/users/", params={"q": "a\x00b"})

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == INVALID_VALUE


# --- every id parameter is bounded -------------------------------------------------------------


def _has_upper_bound(metadata: list[Any]) -> bool:
    return any(isinstance(item, annotated_types.Le | annotated_types.Lt) for item in metadata)


def _int_bounded(annotation: Any, metadata: list[Any]) -> bool | None:
    """``None`` when ``annotation`` holds no ``int``; else whether every ``int`` is bounded."""
    origin = typing.get_origin(annotation)
    if origin is Annotated:
        inner, *extra = typing.get_args(annotation)
        return _int_bounded(inner, [*metadata, *_flatten_metadata(extra)])
    if origin in (typing.Union, UnionType) or origin in (list, set, tuple):
        inherited = [] if origin in (list, set, tuple) else metadata
        results = [_int_bounded(arg, inherited) for arg in typing.get_args(annotation)]
        results = [r for r in results if r is not None]
        return all(results) if results else None
    if annotation is int:
        return _has_upper_bound(metadata)
    return None


def _flatten_metadata(items: list[Any]) -> list[Any]:
    flat: list[Any] = []
    for item in items:
        flat.append(item)
        flat.extend(getattr(item, "metadata", []))
    return flat


def _path_and_query_params(dependant: Any) -> list[Any]:
    """Path and query fields of an endpoint and all its sub-dependencies."""
    fields = [*dependant.path_params, *dependant.query_params]
    for sub in dependant.dependencies:
        fields.extend(_path_and_query_params(sub))
    return fields


def _api_routes(routes: list[Any], prefix: str = "") -> list[tuple[str, APIRoute]]:
    """Every ``APIRoute`` with its full path, walking included routers (FastAPI keeps them as
    nested ``_IncludedRouter`` entries in ``app.routes``)."""
    found: list[tuple[str, APIRoute]] = []
    for route in routes:
        if isinstance(route, APIRoute):
            found.append((prefix + route.path, route))
        elif (inner := getattr(route, "original_router", None)) is not None:
            context = getattr(route, "include_context", None)
            found.extend(_api_routes(inner.routes, prefix + getattr(context, "prefix", "")))
    return found


def _unbounded_id_params(routes: list[Any]) -> list[str]:
    found: list[str] = []
    for path, route in _api_routes(routes):
        for field in _path_and_query_params(route.dependant):
            name = field.name
            annotation = field.field_info.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                # A query model (the KNOWBASE filters): check its own id fields.
                for sub_name, sub in annotation.model_fields.items():
                    if (
                        _is_id_name(sub_name)
                        and _int_bounded(sub.annotation, _flatten_metadata(sub.metadata)) is False
                    ):
                        found.append(f"{','.join(sorted(route.methods))} {path} {sub_name}")
                continue
            if not _is_id_name(name):
                continue
            bounded = _int_bounded(annotation, _flatten_metadata(field.field_info.metadata))
            if bounded is False:
                found.append(f"{','.join(sorted(route.methods))} {path} {name}")
    return found


def _is_id_name(name: str) -> bool:
    return name.endswith("_id") or name.endswith("_ids") or name == "id"


def test_every_integer_id_parameter_has_an_upper_bound():
    """A future endpoint with a bare ``int`` id fails here (7n)."""
    from app.main import app

    paths = {path for path, _ in _api_routes(app.routes)}
    assert f"{API}/admin/users/{{user_id}}" in paths  # the walk really reaches the routers
    assert len(paths) > 50
    assert _unbounded_id_params(app.routes) == []


class _ProbeFilters(BaseModel):
    """A query model for the probe below (module level: FastAPI resolves it from globals)."""

    level_id: int | None = None
    keyword_ids: list[int] | None = None
    scale_ids: list[Annotated[int, Field(le=10)]] | None = None


def test_bound_check_detects_a_bare_int():
    """The introspection really sees an unbounded id (guards the test above)."""
    from fastapi import APIRouter, FastAPI

    router = APIRouter()

    @router.get("/x/{item_id}")
    async def _bare(item_id: int, other_id: int | None = None) -> None: ...

    @router.get("/y/{item_id}")
    async def _ok(item_id: Annotated[int, Path(ge=1, le=10)]) -> None: ...

    @router.get("/z/")
    async def _model(filters: Annotated[_ProbeFilters, Query()]) -> None: ...

    probe = FastAPI()
    probe.include_router(router, prefix="/p")

    assert _unbounded_id_params(probe.routes) == [
        "GET /p/x/{item_id} item_id",
        "GET /p/x/{item_id} other_id",
        "GET /p/z/ level_id",
        "GET /p/z/ keyword_ids",
    ]


# --- the handler itself -------------------------------------------------------------------------


def _data_error(cause: BaseException) -> Any:
    """A ``sqlalchemy.exc.DataError`` shaped like the translated asyncpg error (cause behind
    the adapter's exception in ``orig``)."""
    from sqlalchemy.exc import DataError

    orig = Exception("adapter")
    orig.__cause__ = cause
    return DataError("SELECT 1", None, orig)


def _request() -> Any:
    from starlette.requests import Request

    return Request({"type": "http", "method": "GET", "path": "/x", "headers": []})


@pytest.mark.parametrize(
    "cause",
    [
        asyncpg.exceptions.CharacterNotInRepertoireError("invalid byte sequence"),
        asyncpg.exceptions.DataError("invalid input for query argument $1"),
    ],
    ids=lambda cause: type(cause).__name__,
)
async def test_handler_maps_input_problems_to_422(cause):
    from app.core.exceptions import db_error_handler

    response = await db_error_handler(_request(), _data_error(cause))

    assert response.status_code == 422
    assert b'"request.invalid_value"' in response.body


@pytest.mark.parametrize(
    "cause",
    [
        # A server-side overflow is our bug (a computed value), not the client's input.
        asyncpg.exceptions.NumericValueOutOfRangeError("integer out of range"),
        asyncpg.exceptions.DivisionByZeroError("division by zero"),
        asyncpg.exceptions.UniqueViolationError("duplicate key"),
        RuntimeError("not asyncpg"),
    ],
    ids=lambda cause: type(cause).__name__,
)
async def test_handler_reraises_other_data_errors(cause):
    """Anything else stays a 500 with its traceback in the log (ServerErrorMiddleware)."""
    from sqlalchemy.exc import DataError

    from app.core.exceptions import db_error_handler

    with pytest.raises(DataError):
        await db_error_handler(_request(), _data_error(cause))


def _handler_key(app: Any, exc_class: type[BaseException]) -> type[BaseException] | None:
    """The registered class whose handler Starlette picks for ``exc_class`` (first in MRO)."""
    return next((cls for cls in exc_class.__mro__ if cls in app.exception_handlers), None)


def test_handler_is_registered_for_data_errors_only():
    """Integrity, operational and other database errors never pass through it."""
    from sqlalchemy import exc as sa_exc

    from app.main import app

    assert sa_exc.DBAPIError not in app.exception_handlers
    assert _handler_key(app, sa_exc.DataError) is sa_exc.DataError
    for other in (
        sa_exc.IntegrityError,
        sa_exc.OperationalError,
        sa_exc.ProgrammingError,
        sa_exc.InternalError,
        sa_exc.DBAPIError,
    ):
        assert _handler_key(app, other) is Exception, other


@pytest.mark.parametrize(
    ("sql", "params", "cause"),
    [
        (
            "SELECT CAST(:x AS text)",
            {"x": "a\x00b"},
            asyncpg.exceptions.CharacterNotInRepertoireError,
        ),
        ("SELECT 1 WHERE 1 = :x", {"x": 2**31}, asyncpg.exceptions.DataError),
        (
            "SELECT CAST(:x AS bigint) * 10",
            {"x": 2**62},
            asyncpg.exceptions.NumericValueOutOfRangeError,
        ),
    ],
    ids=["nul", "int32-encoding", "server-overflow"],
)
async def test_asyncpg_data_errors_raise_sqlalchemy_data_error(db_session, sql, params, cause):
    """The asyncpg dialect wraps asyncpg's ``DataError`` family in a plain ``DBAPIError``;
    ``db/session.py`` translates it to ``sqlalchemy.exc.DataError`` (DB-API: problems with the
    processed data), the only class the handler is registered for."""
    from sqlalchemy import exc as sa_exc
    from sqlalchemy import text

    from app.core.exceptions import asyncpg_error

    with pytest.raises(sa_exc.DataError) as raised:
        await db_session.execute(text(sql), params)

    assert type(asyncpg_error(raised.value)) is cause


async def test_integrity_errors_are_not_translated(db_session):
    from sqlalchemy import exc as sa_exc
    from sqlalchemy import text

    with pytest.raises(sa_exc.IntegrityError):
        await db_session.execute(text("INSERT INTO tags (slug, name) VALUES (NULL, 'x')"))
