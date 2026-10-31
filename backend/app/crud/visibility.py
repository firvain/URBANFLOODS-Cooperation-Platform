"""The single "who may see this content" rule (docs/PLAN.md, "visible_to").

- anonymous users and members see ``published`` content;
- an author additionally sees their own content in any status except ``deleted``;
- admins and superadmins see everything that is not deleted (deleted too with
  ``include_deleted``).

:func:`visible_filter` is the SQL criterion every list, detail and mention query uses;
:func:`is_visible` is the same rule for an already loaded row. Both take any model with
``status`` and ``author_id`` (posts now, threads in M3).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ColumnElement, and_, or_, true

from app.db.enums import ContentStatus, UserRole
from app.db.models import Post, User

ADMIN_ROLES = frozenset({UserRole.ADMIN, UserRole.SUPERADMIN})


def is_admin(user: User | None) -> bool:
    """A verified admin or superadmin (the same test as ``require_admin``)."""
    return user is not None and user.is_verified and user.role in ADMIN_ROLES


def visible_filter(
    model: Any, user: User | None, *, include_deleted: bool = False
) -> ColumnElement[bool]:
    """A criterion for ``.where()`` selecting the rows of ``model`` that ``user`` may see."""
    if is_admin(user):
        return true() if include_deleted else model.status != ContentStatus.DELETED
    published = model.status == ContentStatus.PUBLISHED
    if user is None:
        return published
    own = and_(model.author_id == user.id, model.status != ContentStatus.DELETED)
    return or_(published, own)


def visible_posts_filter(
    user: User | None, *, include_deleted: bool = False
) -> ColumnElement[bool]:
    return visible_filter(Post, user, include_deleted=include_deleted)


def is_visible(obj: Any, user: User | None, *, include_deleted: bool = False) -> bool:
    """:func:`visible_filter` evaluated in Python for a loaded row."""
    if is_admin(user):
        return include_deleted or obj.status != ContentStatus.DELETED
    if obj.status == ContentStatus.PUBLISHED:
        return True
    return user is not None and obj.author_id == user.id and obj.status != ContentStatus.DELETED
