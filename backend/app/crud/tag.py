"""Tag data access: find-or-create (used by posts), usage counts, list, delete and merge.
Never commits; the caller (``get_db_tx``) does.

Tags are matched by slug (``slugify_title`` lowercases), so "NBS", " nbs " and "Nbs" are one tag;
the first spelling seen becomes its display name. ``usage_count`` is the number of published,
not-deleted posts carrying the tag; callers refresh it with :func:`recount_tag_usage`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from sqlalchemy import Integer, delete, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, validation_error
from app.db.enums import ContentStatus
from app.db.models import Post, Tag, post_tags
from app.services.slugs import FALLBACK_SLUG, slugify_title

TAG_NAME_MAX_LENGTH = 40
TAG_SLUG_MAX_LENGTH = 80
MAX_TAGS_PER_CALL = 10

TagSort = Literal["popular", "name"]


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def not_found() -> AppError:
    return AppError(404, "tags.not_found", "Tag not found.")


def normalise_tag_name(raw: str) -> tuple[str, str]:
    """``(name, slug)`` for a user-typed tag: trimmed, inner whitespace collapsed, at most 40
    characters, and with something to build a slug from. Raises 422 ``{"tags": "invalid"}``."""
    name = " ".join(raw.split())
    if not name or len(name) > TAG_NAME_MAX_LENGTH:
        raise validation_error({"tags": "invalid"})
    slug = slugify_title(name, max_length=TAG_SLUG_MAX_LENGTH)
    # slugify_title falls back to "item" for names with nothing to transliterate ("???").
    if slug == FALLBACK_SLUG and FALLBACK_SLUG not in name.casefold():
        raise validation_error({"tags": "invalid"})
    return name, slug


async def list_tags(
    db: AsyncSession,
    *,
    q: str | None = None,
    sort: TagSort = "popular",
    skip: int = 0,
    limit: int = 50,
) -> tuple[int, list[Tag]]:
    """``(total, tags)``. ``q`` is a case-insensitive substring of the name (trigram index).
    ``popular`` orders by ``usage_count`` desc then name; ``name`` alphabetically."""
    conditions = []
    if q:
        conditions.append(Tag.name.ilike(f"%{_escape_like(q)}%", escape="\\"))

    total_stmt = select(func.count()).select_from(select(Tag.id).where(*conditions).subquery())
    total = (await db.execute(total_stmt)).scalar_one()

    by_name = (func.lower(Tag.name), Tag.id)
    order = (Tag.usage_count.desc(), *by_name) if sort == "popular" else by_name
    stmt = select(Tag).where(*conditions).order_by(*order).offset(skip).limit(limit)
    return total, list((await db.execute(stmt)).scalars().all())


async def get_tag(db: AsyncSession, *, tag_id: int) -> Tag | None:
    return await db.get(Tag, tag_id)


async def get_or_create_tags(db: AsyncSession, *, names: Sequence[str]) -> list[Tag]:
    """The tags for ``names`` in input order (duplicates folded), creating missing ones.

    Raises 422 ``{"tags": "too_many"}`` for more than 10 names, ``{"tags": "invalid"}`` for an
    empty or over-long name. Safe against a concurrent insert of the same slug.
    """
    if len(names) > MAX_TAGS_PER_CALL:
        raise validation_error({"tags": "too_many"})
    wanted: dict[str, str] = {}  # slug -> first spelling
    for raw in names:
        name, slug = normalise_tag_name(raw)
        wanted.setdefault(slug, name)
    if not wanted:
        return []

    rows = [{"slug": slug, "name": name} for slug, name in wanted.items()]
    await db.execute(insert(Tag).values(rows).on_conflict_do_nothing(index_elements=["slug"]))
    found = (await db.execute(select(Tag).where(Tag.slug.in_(wanted)))).scalars().all()
    by_slug = {tag.slug: tag for tag in found}
    return [by_slug[slug] for slug in wanted]


async def recount_tag_usage(db: AsyncSession, *, tag_ids: Iterable[int]) -> None:
    """Set ``usage_count`` of the given tags to their number of published, not-deleted posts."""
    ids = list(set(tag_ids))
    if not ids:
        return
    published = (
        select(func.count())
        .select_from(post_tags.join(Post, Post.id == post_tags.c.post_id))
        .where(
            post_tags.c.tag_id == Tag.id,
            Post.status == ContentStatus.PUBLISHED,
            Post.deleted_at.is_(None),
        )
        .correlate(Tag)
        .scalar_subquery()
    )
    await db.execute(
        update(Tag)
        .where(Tag.id.in_(ids))
        .values(usage_count=published)
        .execution_options(synchronize_session=False)
    )
    # Loaded Tag objects would otherwise keep their stale counts.
    for tag in list(db.identity_map.values()):
        if isinstance(tag, Tag) and tag.id in ids:
            db.expire(tag, ["usage_count"])


async def delete_tag(db: AsyncSession, *, tag: Tag) -> None:
    """Delete ``tag``; its ``post_tags`` rows go with it (ON DELETE CASCADE)."""
    await db.execute(delete(Tag).where(Tag.id == tag.id))
    db.expunge(tag)


async def merge_tags(db: AsyncSession, *, source_id: int, target_id: int) -> Tag:
    """Move every post of ``source`` to ``target`` (posts already on both keep one row), delete
    ``source`` and recount ``target``. Returns the target.

    Raises ``AppError`` 409 ``tags.same`` or 404 ``tags.not_found``.
    """
    if source_id == target_id:
        raise AppError(409, "tags.same", "A tag cannot be merged into itself.")
    source = await get_tag(db, tag_id=source_id)
    target = await get_tag(db, tag_id=target_id)
    if source is None or target is None:
        raise not_found()

    moved = select(post_tags.c.post_id, literal(target.id, Integer)).where(
        post_tags.c.tag_id == source.id
    )
    await db.execute(
        insert(post_tags).from_select(["post_id", "tag_id"], moved).on_conflict_do_nothing()
    )
    await delete_tag(db, tag=source)
    await recount_tag_usage(db, tag_ids=[target.id])
    await db.refresh(target)
    return target
