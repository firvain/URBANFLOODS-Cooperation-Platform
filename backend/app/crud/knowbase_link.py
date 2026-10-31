"""KNOWBASE links of posts and threads (polymorphic: ``content_type`` + ``content_id``).
Never commits; the caller (``get_db_tx``) does.

Links are validated against the KNOWBASE through the proxy (``KnowbaseClient.resolve_links``,
which uses its detail cache) and their titles are cached on the row, so reading a post never
calls the KNOWBASE.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, validation_error
from app.db.enums import ContentType, KbType
from app.db.models import KnowbaseLink
from app.services.knowbase import KnowbaseClient, KnowbaseError, KnowbaseUnavailable

MAX_LINKS = 10


def _dedupe(links: Sequence[tuple[KbType | str, int]]) -> list[tuple[KbType, int]]:
    unique: list[tuple[KbType, int]] = []
    for kb_type, kb_id in links:
        key = (KbType(kb_type), int(kb_id))
        if key not in unique:
            unique.append(key)
    return unique


async def replace_links(
    db: AsyncSession,
    *,
    content_type: ContentType,
    content_id: int,
    links: Sequence[tuple[KbType | str, int]],
    knowbase: KnowbaseClient,
) -> list[KnowbaseLink]:
    """Replace the content's links with ``links`` (duplicates folded, input order kept).

    Raises 422 ``{"knowbase_links": "too_many"}`` for more than 10 links and
    ``{"knowbase_links": "not_found"}`` when an item does not exist; 503 ``knowbase.unavailable``
    when the KNOWBASE is down (and the item is not cached), 502 ``knowbase.upstream_error`` when
    it rejects the request.
    """
    unique = _dedupe(links)
    if len(unique) > MAX_LINKS:
        raise validation_error({"knowbase_links": "too_many"})

    titles: dict[tuple[str, int], dict[str, str | None] | None] = {}
    if unique:
        try:
            titles = await knowbase.resolve_links(
                [(kb_type.value, kb_id) for kb_type, kb_id in unique]
            )
        except KnowbaseUnavailable as exc:
            raise AppError(
                503, "knowbase.unavailable", "The KNOWBASE is temporarily unavailable."
            ) from exc
        except KnowbaseError as exc:
            raise AppError(
                502, "knowbase.upstream_error", "The KNOWBASE rejected the request."
            ) from exc
        if any(titles.get((kb_type.value, kb_id)) is None for kb_type, kb_id in unique):
            raise validation_error({"knowbase_links": "not_found"})

    await db.execute(
        delete(KnowbaseLink).where(
            KnowbaseLink.content_type == content_type, KnowbaseLink.content_id == content_id
        )
    )
    rows: list[KnowbaseLink] = []
    for order, (kb_type, kb_id) in enumerate(unique):
        title = titles[(kb_type.value, kb_id)] or {}
        rows.append(
            KnowbaseLink(
                content_type=content_type,
                content_id=content_id,
                kb_type=kb_type,
                kb_id=kb_id,
                cached_title_en=title.get("title_en") or f"{kb_type.value} {kb_id}",
                cached_title_local=title.get("title_local") or None,
                sort_order=order,
            )
        )
    db.add_all(rows)
    await db.flush()
    return rows


async def list_links(
    db: AsyncSession, *, content_type: ContentType, content_id: int
) -> list[KnowbaseLink]:
    """The content's links in their saved order."""
    stmt = (
        select(KnowbaseLink)
        .where(KnowbaseLink.content_type == content_type, KnowbaseLink.content_id == content_id)
        .order_by(KnowbaseLink.sort_order, KnowbaseLink.id)
    )
    return list((await db.scalars(stmt)).all())
