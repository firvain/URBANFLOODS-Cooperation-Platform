"""KNOWBASE proxy schemas.

Filters mirror the upstream query parameters (``extra="forbid"``: unknown parameters are a 422);
list ``limit`` is capped at 200 through the proxy. Responses are loose (``extra="allow"``) so
upstream fields pass through unchanged and API drift does not break the proxy; endpoints
serialise them with ``response_model_exclude_unset`` so nothing is added except ``photo_url`` on
measures. The declared fields are documentation (and frontend types), all optional.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.db.limits import MAX_ID

PROXY_MAX_LIMIT = 200

SearchText = Annotated[str, Field(min_length=2, max_length=200)]
KeywordSearch = Annotated[str, Field(min_length=2, max_length=100)]
# KNOWBASE ids are INTEGER too: a larger one is a 422 here rather than an upstream error.
PositiveId = Annotated[int, Field(ge=1, le=MAX_ID)]


class _Filters(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ListFilters(_Filters):
    skip: int = Field(0, ge=0)
    limit: int = Field(100, ge=1, le=PROXY_MAX_LIMIT)


class DocumentFilters(_ListFilters):
    q: SearchText | None = None
    country: Annotated[str, Field(max_length=100)] | None = None
    level_id: PositiveId | None = None
    subject_id: PositiveId | None = None
    keyword_ids: list[PositiveId] | None = None
    keyword_search: KeywordSearch | None = None


class MeasureFilters(_ListFilters):
    q: SearchText | None = None
    category_id: Annotated[int, Field(ge=1, le=4)] | None = None
    level_of_application_ids: list[PositiveId] | None = None
    scale_ids: list[PositiveId] | None = None
    keyword_ids: list[PositiveId] | None = None
    keyword_search: KeywordSearch | None = None


class DocumentLookupFilters(_Filters):
    """Union of the document lookups' cross filters; each lookup accepts a subset of these."""

    country: Annotated[str, Field(max_length=100)] | None = None
    level_id: PositiveId | None = None
    subject_id: PositiveId | None = None
    keyword_ids: list[PositiveId] | None = None


class MeasureLookupFilters(_Filters):
    """Union of the measure lookups' cross filters; each lookup accepts a subset of these."""

    category_id: PositiveId | None = None
    level_of_application_ids: list[PositiveId] | None = None
    scale_ids: list[PositiveId] | None = None
    keyword_ids: list[PositiveId] | None = None


# --- responses (loose pass-through) -----------------------------------------------------------


class KnowbaseItem(BaseModel):
    """Any upstream object (reference lists, lookup options), passed through unchanged."""

    model_config = ConfigDict(extra="allow")


class KnowbaseDocument(KnowbaseItem):
    id: int
    name_of_document_en: str | None = None
    name_of_document_local: str | None = None
    country: str | None = None
    level: dict[str, Any] | None = None
    subject: dict[str, Any] | None = None
    no: int | str | None = None
    official_gazzette_ref: str | None = None
    extended_description_en: str | None = None
    extended_description_local: str | None = None
    web_links: str | None = None
    keywords: str | None = None
    comments: str | None = None
    keyword_labels: list[dict[str, Any]] | None = None
    all_keywords: list[Any] | None = None


class KnowbaseDocumentList(BaseModel):
    total: int
    items: list[KnowbaseDocument]


class KnowbaseMeasure(KnowbaseItem):
    id: int
    measure_code: int | str | None = None
    title_en: str | None = None
    title_local: str | None = None
    photo_filename: str | None = None
    photo_url: str | None = Field(None, description="Absolute URL of the photo on the KNOWBASE")
    category: dict[str, Any] | None = None
    levels_of_application: list[dict[str, Any]] | None = None
    scales: list[dict[str, Any]] | None = None
    keywords: list[dict[str, Any]] | None = None
    description_en: str | None = None
    description_local: str | None = None
    resources_required_en: str | None = None
    resources_required_local: str | None = None
    benefits_en: str | None = None
    benefits_local: str | None = None
    constraints_en: str | None = None
    constraints_local: str | None = None
    other_keywords: str | None = None
    photo_source: str | None = None
    all_keywords: list[Any] | None = None


class KnowbaseMeasureList(BaseModel):
    total: int
    items: list[KnowbaseMeasure]


class KnowbaseCacheCounts(BaseModel):
    lists: int
    details: int
    lookups: int
    stale: int


class KnowbaseStatus(BaseModel):
    reachable: bool
    last_success_at: datetime | None
    last_error_at: datetime | None
    last_error: str | None
    cache: KnowbaseCacheCounts
