"""Tag schemas (public list; admin merge)."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.api.v1.params import DbId


class TagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    name: str
    usage_count: int


class TagList(BaseModel):
    total: int
    items: list[TagOut]


class TagMerge(BaseModel):
    target_id: DbId
