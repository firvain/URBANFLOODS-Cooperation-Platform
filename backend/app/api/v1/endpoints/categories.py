"""Categories (blog and forum): public list and detail, admin create, update and archive."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Response, status

from app.api.v1.schemas.category import CategoryCreate, CategoryList, CategoryOut, CategoryUpdate
from app.core.deps import ADMIN_ROLES, AdminUser, CurrentUser, DbTx
from app.core.exceptions import AppError, error_body
from app.crud import audit as crud_audit
from app.crud import category as crud_category
from app.db.enums import CategoryKind
from app.db.models import Category

router = APIRouter()


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


def _out(category: Category, post_count: int) -> CategoryOut:
    return CategoryOut.model_validate(category).model_copy(update={"post_count": post_count})


def _not_found() -> AppError:
    return AppError(404, "categories.not_found", "Category not found.")


async def _get_or_404(db: DbTx, category_id: int) -> Category:
    category = await crud_category.get_category_by_id(db, category_id=category_id)
    if category is None:
        raise _not_found()
    return category


async def _out_with_count(db: DbTx, category: Category) -> CategoryOut:
    count = await crud_category.count_published_posts(db, category_id=category.id)
    return _out(category, count)


@router.get("/", response_model=CategoryList, responses=_error_responses(422))
async def list_categories(
    db: DbTx,
    user: CurrentUser,
    kind: CategoryKind | None = None,
    include_archived: bool = False,
) -> CategoryList:
    """Categories by kind and ``sort_order``. ``include_archived`` is honoured for admins only;
    everyone else always gets the active categories."""
    is_admin = user is not None and user.is_verified and user.role in ADMIN_ROLES
    rows = await crud_category.list_categories(
        db, kind=kind, include_archived=include_archived and is_admin
    )
    return CategoryList(total=len(rows), items=[_out(c, count) for c, count in rows])


@router.get("/{kind}/{slug}", response_model=CategoryOut, responses=_error_responses(404, 422))
async def get_category(kind: CategoryKind, slug: str, db: DbTx) -> CategoryOut:
    """One category (archived ones too, so links from old posts keep working)."""
    category = await crud_category.get_category(db, kind=kind, slug=slug)
    if category is None:
        raise _not_found()
    return await _out_with_count(db, category)


@router.post(
    "/",
    response_model=CategoryOut,
    status_code=status.HTTP_201_CREATED,
    responses=_error_responses(401, 403, 409, 422),
)
async def create_category(body: CategoryCreate, admin: AdminUser, db: DbTx) -> CategoryOut:
    """Add a category (admin). The slug is derived from the name when omitted."""
    category = await crud_category.create_category(db, **body.model_dump())
    await crud_audit.log_action(
        db,
        actor_id=admin.id,
        action="category.created",
        target_type="category",
        target_id=category.id,
        metadata={"kind": category.kind.value, "slug": category.slug, "name": category.name},
    )
    return _out(category, 0)


@router.patch(
    "/{category_id}",
    response_model=CategoryOut,
    responses=_error_responses(401, 403, 404, 409, 422),
)
async def update_category(
    category_id: int, body: CategoryUpdate, admin: AdminUser, db: DbTx
) -> CategoryOut:
    """Update a category (admin). Omitted fields are kept; ``description: null`` clears."""
    category = await _get_or_404(db, category_id)
    changed = await crud_category.update_category(
        db, category=category, changes=body.model_dump(exclude_unset=True)
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=admin.id,
            action="category.updated",
            target_type="category",
            target_id=category.id,
            metadata={"fields": changed},
        )
    return await _out_with_count(db, category)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(401, 403, 404, 409),
)
async def archive_category(category_id: int, admin: AdminUser, db: DbTx) -> Response:
    """Archive a category (admin): hidden from lists, its posts stay. Never a hard delete."""
    category = await _get_or_404(db, category_id)
    if await crud_category.archive_category(db, category=category):
        await crud_audit.log_action(
            db,
            actor_id=admin.id,
            action="category.archived",
            target_type="category",
            target_id=category.id,
            metadata={"kind": category.kind.value, "slug": category.slug},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
