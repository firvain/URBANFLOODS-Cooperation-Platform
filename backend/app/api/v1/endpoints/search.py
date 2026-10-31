"""Site search: one ranked list of blog posts and forum threads (public; visibility rules apply,
so signed-in authors also find their own pending content and admins everything not deleted).

Replies and comments are not searched; see ``crud/search.py``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from app.api.v1.schemas.search import PaginatedSearch, SearchHit, SearchQuery
from app.core.deps import CurrentUser, DbTx
from app.core.exceptions import error_body
from app.core.rate_limit import limit
from app.crud import search as crud_search

router = APIRouter()

MAX_PAGE_SIZE = 50
SEARCH_LIMIT = limit("search", 60, 60)


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


@router.get(
    "/",
    response_model=PaginatedSearch,
    dependencies=[Depends(SEARCH_LIMIT)],
    responses=_error_responses(422, 429),
)
async def search(
    db: DbTx,
    user: CurrentUser,
    q: Annotated[SearchQuery, Query(description="2-200 characters after trimming")],
    type_: Annotated[crud_search.SearchType, Query(alias="type")] = "all",
    locale: Annotated[str | None, Query(max_length=5)] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> PaginatedSearch:
    """Posts and threads matching ``q`` (titles and bodies, stemmed, typo-tolerant on titles),
    best match first. ``snippet`` is escaped text whose only markup is ``<mark>``."""
    total, hits = await crud_search.search(
        db, q=q, user=user, type_=type_, locale=locale, skip=skip, limit=limit_
    )
    return PaginatedSearch(total=total, items=[SearchHit.model_validate(hit) for hit in hits])
