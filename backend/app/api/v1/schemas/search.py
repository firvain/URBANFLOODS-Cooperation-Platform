"""Search schemas: one ranked hit (a blog post or a forum thread) and a page of hits.

``snippet`` is plain text in which the only markup is ``<mark>…</mark>`` around matched words;
everything else from the body is HTML-escaped. The frontend renders it through ``SafeHtml`` with
only ``mark`` allowed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, StringConstraints

Q_MIN_LENGTH = 2
Q_MAX_LENGTH = 200

SearchQuery = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=Q_MIN_LENGTH, max_length=Q_MAX_LENGTH),
]


class SearchAuthor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    display_name: str


class SearchCategory(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str


class SearchHit(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    type: Literal["post", "thread"]
    id: int
    slug: str
    title: str
    snippet: str
    locale: str
    author: SearchAuthor | None
    category: SearchCategory
    published_at: datetime | None
    rank: float


class PaginatedSearch(BaseModel):
    total: int
    items: list[SearchHit]
