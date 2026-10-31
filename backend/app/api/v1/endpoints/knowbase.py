"""KNOWBASE proxy: public, read-only, cached pass-through of an allow-list of KNOWBASE routes.

Every response carries ``X-Knowbase-Cache: hit|miss|stale``. Measures gain ``photo_url``.
Errors: unknown lookup 404 ``knowbase.unknown_lookup``, upstream 404 ``knowbase.not_found``,
upstream down with nothing cached 503 ``knowbase.unavailable``, other upstream 4xx 502
``knowbase.upstream_error``.
"""

from __future__ import annotations

from collections.abc import Awaitable
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response
from pydantic import BaseModel

from app.api.v1.schemas.knowbase import (
    DocumentFilters,
    DocumentLookupFilters,
    KnowbaseDocument,
    KnowbaseDocumentList,
    KnowbaseItem,
    KnowbaseMeasure,
    KnowbaseMeasureList,
    KnowbaseStatus,
    MeasureFilters,
    MeasureLookupFilters,
)
from app.api.v1.schemas.post import PaginatedPosts, paginated_posts
from app.core.deps import CurrentUser, DbTx, Knowbase
from app.core.exceptions import AppError, error_body, validation_error
from app.crud import post as crud_post
from app.db.enums import KbType
from app.services.knowbase import (
    DOCUMENT_LOOKUPS,
    MEASURE_LOOKUPS,
    KnowbaseError,
    KnowbaseNotFound,
    KnowbaseResult,
    KnowbaseUnavailable,
    with_photo_url,
)

router = APIRouter()

CACHE_HEADER = "X-Knowbase-Cache"
MAX_ID = 2**31 - 1
MAX_MENTIONS_PAGE = 50

ItemId = Annotated[int, Path(ge=1, le=MAX_ID)]


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


UPSTREAM_ERRORS = (404, 422, 502, 503)


async def _proxy(call: Awaitable[KnowbaseResult], response: Response) -> Any:
    """Await a service call, map its errors to codes and set the cache header."""
    try:
        result = await call
    except KnowbaseNotFound as exc:
        raise AppError(404, "knowbase.not_found", "Not found in the KNOWBASE.") from exc
    except KnowbaseUnavailable as exc:
        raise AppError(
            503, "knowbase.unavailable", "The KNOWBASE is temporarily unavailable."
        ) from exc
    except KnowbaseError as exc:
        raise AppError(
            502, "knowbase.upstream_error", "The KNOWBASE rejected the request."
        ) from exc
    response.headers[CACHE_HEADER] = result.cache
    return result.data


def _query(filters: BaseModel) -> dict[str, Any]:
    return filters.model_dump(exclude_none=True)


def _lookup_query(name: str, filters: BaseModel, allowed: frozenset[str]) -> dict[str, Any]:
    """The lookup's filters; a filter the upstream lookup does not take is a 422."""
    query = _query(filters)
    extra = sorted(set(query) - allowed)
    if extra:
        raise validation_error({f"query.{field}": "extra_forbidden" for field in extra})
    return query


def _unknown_lookup() -> AppError:
    return AppError(404, "knowbase.unknown_lookup", "Unknown KNOWBASE lookup.")


def _with_photo_urls(page: Any) -> Any:
    if isinstance(page, dict) and isinstance(page.get("items"), list):
        return {**page, "items": [with_photo_url(item) for item in page["items"]]}
    return page


# --- documents --------------------------------------------------------------------------------


@router.get(
    "/documents/",
    response_model=KnowbaseDocumentList,
    response_model_exclude_unset=True,
    responses=_error_responses(*UPSTREAM_ERRORS),
)
async def list_documents(
    filters: Annotated[DocumentFilters, Query()], kb: Knowbase, response: Response
) -> Any:
    """Legal and policy documents (search and filters as on the KNOWBASE)."""
    return await _proxy(kb.list_documents(_query(filters)), response)


@router.get(
    "/documents/{document_id}",
    response_model=KnowbaseDocument,
    response_model_exclude_unset=True,
    responses=_error_responses(*UPSTREAM_ERRORS),
)
async def get_document(document_id: ItemId, kb: Knowbase, response: Response) -> Any:
    """One document."""
    return await _proxy(kb.get_document(document_id), response)


# --- measures ---------------------------------------------------------------------------------


@router.get(
    "/measures/",
    response_model=KnowbaseMeasureList,
    response_model_exclude_unset=True,
    responses=_error_responses(*UPSTREAM_ERRORS),
)
async def list_measures(
    filters: Annotated[MeasureFilters, Query()], kb: Knowbase, response: Response
) -> Any:
    """Flood-management measures, each with an absolute ``photo_url``."""
    return _with_photo_urls(await _proxy(kb.list_measures(_query(filters)), response))


@router.get(
    "/measures/lookups/{name}",
    response_model=list[KnowbaseItem],
    response_model_exclude_unset=True,
    responses=_error_responses(*UPSTREAM_ERRORS),
)
async def get_measure_lookup(
    name: str,
    filters: Annotated[MeasureLookupFilters, Query()],
    kb: Knowbase,
    response: Response,
) -> Any:
    """Measure filter options with counts: ``categories``, ``levels-of-application``,
    ``scales``, ``keywords``."""
    allowed = MEASURE_LOOKUPS.get(name)
    if allowed is None:
        raise _unknown_lookup()
    query = _lookup_query(name, filters, allowed)
    return await _proxy(kb.get_measure_lookup(name, query), response)


@router.get(
    "/measures/{measure_id}",
    response_model=KnowbaseMeasure,
    response_model_exclude_unset=True,
    responses=_error_responses(*UPSTREAM_ERRORS),
)
async def get_measure(measure_id: ItemId, kb: Knowbase, response: Response) -> Any:
    """One measure, with an absolute ``photo_url``."""
    return with_photo_url(await _proxy(kb.get_measure(measure_id), response))


# --- reference lists and lookups --------------------------------------------------------------


@router.get(
    "/levels/",
    response_model=list[KnowbaseItem],
    response_model_exclude_unset=True,
    responses=_error_responses(502, 503),
)
async def list_levels(kb: Knowbase, response: Response) -> Any:
    """Document levels (national, regional, local, ...)."""
    return await _proxy(kb.get_levels(), response)


@router.get(
    "/subjects/",
    response_model=list[KnowbaseItem],
    response_model_exclude_unset=True,
    responses=_error_responses(502, 503),
)
async def list_subjects(kb: Knowbase, response: Response) -> Any:
    """Document subjects."""
    return await _proxy(kb.get_subjects(), response)


@router.get(
    "/keyword-labels/",
    response_model=list[KnowbaseItem],
    response_model_exclude_unset=True,
    responses=_error_responses(502, 503),
)
async def list_keyword_labels(kb: Knowbase, response: Response) -> Any:
    """Document keyword labels."""
    return await _proxy(kb.get_keyword_labels(), response)


@router.get(
    "/lookups/{name}",
    response_model=list[KnowbaseItem],
    response_model_exclude_unset=True,
    responses=_error_responses(*UPSTREAM_ERRORS),
)
async def get_document_lookup(
    name: str,
    filters: Annotated[DocumentLookupFilters, Query()],
    kb: Knowbase,
    response: Response,
) -> Any:
    """Document filter options with counts: ``countries``, ``levels``, ``subjects``,
    ``keywords``."""
    allowed = DOCUMENT_LOOKUPS.get(name)
    if allowed is None:
        raise _unknown_lookup()
    query = _lookup_query(name, filters, allowed)
    return await _proxy(kb.get_document_lookup(name, query), response)


# --- status -----------------------------------------------------------------------------------


@router.get("/status", response_model=KnowbaseStatus)
async def knowbase_status(kb: Knowbase) -> KnowbaseStatus:
    """Whether the KNOWBASE answered the last call, and cache sizes. Makes no request."""
    return KnowbaseStatus.model_validate(kb.status())


# --- mentions (posts linking a KNOWBASE item) -------------------------------------------------


@router.get(
    "/{kb_type}/{kb_id}/mentions/",
    response_model=PaginatedPosts,
    responses=_error_responses(422),
)
async def list_mentions(
    kb_type: KbType,
    kb_id: ItemId,
    db: DbTx,
    user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_MENTIONS_PAGE)] = 20,
) -> PaginatedPosts:
    """Posts that link this KNOWBASE document or measure (visible to the caller), newest first.
    Answered from our own database; the KNOWBASE is not called."""
    total, posts = await crud_post.list_mentions(
        db, kb_type=kb_type, kb_id=kb_id, user=user, skip=skip, limit=limit
    )
    return paginated_posts(total, posts)
