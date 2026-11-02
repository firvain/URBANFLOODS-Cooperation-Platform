"""Blog posts: public list and detail (visibility rules), create (verified; status by trust),
update and soft delete (author or admin). Moderation transitions live in /moderation (4b)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.v1.params import PathId, QueryId
from app.api.v1.schemas.post import (
    KnowbaseLinkOut,
    PaginatedPosts,
    PostCreate,
    PostDetail,
    PostUpdate,
    paginated_posts,
)
from app.core.deps import CurrentUser, DbTx, Knowbase, VerifiedUser
from app.core.exceptions import error_body
from app.core.rate_limit import limit
from app.crud import audit as crud_audit
from app.crud import knowbase_link as crud_links
from app.crud import post as crud_post
from app.db.enums import ContentStatus, ContentType
from app.db.models import Post

router = APIRouter()

MAX_PAGE_SIZE = 50
CREATE_LIMIT = limit("posts.create", 20, 3600)


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


async def _detail(db: DbTx, post: Post) -> PostDetail:
    detail = PostDetail.model_validate(post)
    links = await crud_links.list_links(db, content_type=ContentType.POST, content_id=post.id)
    detail.knowbase_links = [KnowbaseLinkOut.model_validate(link) for link in links]
    return detail


@router.get("/", response_model=PaginatedPosts, responses=_error_responses(422))
async def list_posts(
    db: DbTx,
    user: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    category: Annotated[str | None, Query(max_length=80, description="Category slug")] = None,
    tag: Annotated[str | None, Query(max_length=80, description="Tag slug")] = None,
    author_id: QueryId = None,
    locale: Annotated[str | None, Query(max_length=5)] = None,
    status_: Annotated[
        ContentStatus | None, Query(alias="status", description="Admins only")
    ] = None,
    sort: crud_post.PostSort | None = None,
    upcoming_only: bool = False,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> PaginatedPosts:
    """Posts visible to the caller. ``q`` searches titles and bodies (ranked unless ``sort`` is
    given); ``sort=events`` lists posts with an event, soonest first."""
    total, posts = await crud_post.list_posts(
        db,
        user=user,
        q=q,
        category_slug=category,
        tag_slug=tag,
        author_id=author_id,
        locale=locale,
        status=status_,
        sort=sort,
        upcoming_only=upcoming_only,
        skip=skip,
        limit=limit_,
    )
    return paginated_posts(total, posts)


@router.get("/{slug}", response_model=PostDetail, responses=_error_responses(404))
async def get_post(slug: str, db: DbTx, user: CurrentUser) -> PostDetail:
    """One post, if the caller may see it."""
    post = await crud_post.get_post_by_slug(db, slug=slug, user=user)
    if post is None:
        raise crud_post.not_found()
    return await _detail(db, post)


@router.post(
    "/",
    response_model=PostDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(CREATE_LIMIT)],
    responses=_error_responses(401, 403, 422, 429, 502, 503),
)
async def create_post(body: PostCreate, user: VerifiedUser, db: DbTx, kb: Knowbase) -> PostDetail:
    """Write a post. Trusted members and admins publish immediately; a first post waits for
    approval (``pending``)."""
    post = await crud_post.create_post(
        db,
        author=user,
        category_id=body.category_id,
        title=body.title,
        body_html=body.body_html,
        excerpt=body.excerpt,
        cover_attachment_id=body.cover_attachment_id,
        locale=body.locale,
        event_at=body.event_at,
        event_url=body.event_url,
        tag_names=body.tags,
        knowbase_links=[(link.kb_type, link.kb_id) for link in body.knowbase_links],
        knowbase=kb,
    )
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="post.created",
        target_type="post",
        target_id=post.id,
        metadata={"post_id": post.id, "status": post.status.value, "category_id": post.category_id},
    )
    return await _detail(db, post)


@router.patch(
    "/{post_id}",
    response_model=PostDetail,
    responses=_error_responses(401, 403, 404, 409, 422, 502, 503),
)
async def update_post(
    post_id: PathId, body: PostUpdate, user: VerifiedUser, db: DbTx, kb: Knowbase
) -> PostDetail:
    """Edit a post (its author, or an admin). The status does not change."""
    post = await crud_post.get_editable_post(db, post_id=post_id, user=user)
    changed = await crud_post.update_post(
        db, post=post, user=user, data=body.model_dump(exclude_unset=True), knowbase=kb
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="post.updated",
            target_type="post",
            target_id=post.id,
            metadata={"fields": changed},
        )
    refreshed = await crud_post.get_post_by_id(db, post_id=post.id)
    assert refreshed is not None
    return await _detail(db, refreshed)


@router.delete(
    "/{post_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(401, 403, 404),
)
async def delete_post(post_id: PathId, user: VerifiedUser, db: DbTx) -> Response:
    """Soft-delete a post (its author, or an admin)."""
    post = await crud_post.get_editable_post(db, post_id=post_id, user=user)
    previous = post.status
    await crud_post.soft_delete_post(db, post=post)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="post.deleted",
        target_type="post",
        target_id=post.id,
        metadata={"post_id": post.id, "previous_status": previous.value},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
