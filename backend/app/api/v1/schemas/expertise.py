"""Expertise vocabulary schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ExpertiseTagOut(BaseModel):
    """One expertise area. ``label`` is English; the frontend translates by ``slug``."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    slug: str
    label: str
    sort_order: int


class ExpertiseTagList(BaseModel):
    total: int
    items: list[ExpertiseTagOut]
