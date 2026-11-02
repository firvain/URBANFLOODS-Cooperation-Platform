"""Bounded id types shared by every endpoint and request schema (7n).

An id past its column's range would reach asyncpg, which cannot encode it, and the request would
end in a 500. Every integer id taken from a path, a query string or a body uses one of these, so
it is answered with a 422 instead (``tests/test_input_bounds.py`` checks every route).

Posts, threads, users, categories, tags, organisations, expertise tags, uploads and KNOWBASE
items have INTEGER ids; replies, comments and reports have BIGINT ids. Moderation takes any
content type with the BIGINT bound and treats a post or thread id past the INTEGER range as not
found (``crud/moderation.py``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Path, Query
from pydantic import Field

from app.db.limits import MAX_BIGINT_ID, MAX_ID

__all__ = [
    "MAX_BIGINT_ID",
    "MAX_ID",
    "BigDbId",
    "BigPathId",
    "DbId",
    "PathId",
    "QueryId",
    "QueryIds",
]

# Request bodies.
DbId = Annotated[int, Field(ge=1, le=MAX_ID)]
BigDbId = Annotated[int, Field(ge=1, le=MAX_BIGINT_ID)]
# Path parameters.
PathId = Annotated[int, Path(ge=1, le=MAX_ID)]
BigPathId = Annotated[int, Path(ge=1, le=MAX_BIGINT_ID)]
# Query parameters: optional id filters (``?author_id=``), and a repeated one (``?ids=1&ids=2``).
QueryId = Annotated[int | None, Query(ge=1, le=MAX_ID)]
QueryIds = Annotated[list[DbId] | None, Query()]
