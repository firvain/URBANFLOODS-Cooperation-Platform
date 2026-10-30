"""Expertise vocabulary: the public list of active tags (profile editor, directory filter)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.schemas.expertise import ExpertiseTagList, ExpertiseTagOut
from app.core.deps import DbTx
from app.crud import expertise as crud_expertise

router = APIRouter()


@router.get("/", response_model=ExpertiseTagList)
async def list_expertise(db: DbTx) -> ExpertiseTagList:
    """Every active expertise tag, in display order."""
    tags = await crud_expertise.list_active_tags(db)
    return ExpertiseTagList(
        total=len(tags), items=[ExpertiseTagOut.model_validate(tag) for tag in tags]
    )
