"""Forum threads: public list (pinned first) and detail (visibility rules), create (verified;
status by trust), update and soft delete (author or admin; a locked thread is admin-only), admin
pin/unpin/lock/unlock, and the threads linking a KNOWBASE item. Replies live in increment 3c."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.api.v1.schemas.post import KnowbaseLinkOut
from app.api.v1.schemas.thread import (
    PaginatedThreads,
    ThreadCreate,
    ThreadDetail,
    ThreadUpdate,
    paginated_threads,
)
from app.core.deps import AdminUser, CurrentUser, DbTx, Knowbase, VerifiedUser
from app.core.exceptions import error_body
from app.core.rate_limit import limit
from app.crud import audit as crud_audit
from app.crud import knowbase_link as crud_links
from app.crud import thread as crud_thread
from app.db.enums import ContentStatus, ContentType, KbType
from app.db.models import Thread, User

router = APIRouter()

MAX_PAGE_SIZE = 50
MAX_ID = 2**31 - 1
CREATE_LIMIT = limit("threads.create", 20, 3600)

ItemId = Annotated[int, Path(ge=1, le=MAX_ID)]


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


async def _detail(db: DbTx, thread: Thread) -> ThreadDetail:
    detail = ThreadDetail.model_validate(thread)
    links = await crud_links.list_links(db, content_type=ContentType.THREAD, content_id=thread.id)
    detail.knowbase_links = [KnowbaseLinkOut.model_validate(link) for link in links]
    return detail


async def _refreshed_detail(db: DbTx, thread_id: int) -> ThreadDetail:
    refreshed = await crud_thread.get_thread_by_id(db, thread_id=thread_id)
    assert refreshed is not None
    return await _detail(db, refreshed)


@router.get("/", response_model=PaginatedThreads, responses=_error_responses(422))
async def list_threads(
    db: DbTx,
    user: CurrentUser,
    q: Annotated[str | None, Query(max_length=200)] = None,
    category: Annotated[str | None, Query(max_length=80, description="Category slug")] = None,
    tag: Annotated[str | None, Query(max_length=80, description="Tag slug")] = None,
    author_id: int | None = None,
    locale: Annotated[str | None, Query(max_length=5)] = None,
    status_: Annotated[
        ContentStatus | None, Query(alias="status", description="Admins only")
    ] = None,
    sort: crud_thread.ThreadSort | None = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> PaginatedThreads:
    """Threads visible to the caller: pinned first, then latest activity (or ``sort=newest``).
    ``q`` searches titles and bodies (ranked unless ``sort`` is given)."""
    total, threads = await crud_thread.list_threads(
        db,
        user=user,
        q=q,
        category_slug=category,
        tag_slug=tag,
        author_id=author_id,
        locale=locale,
        status=status_,
        sort=sort,
        skip=skip,
        limit=limit_,
    )
    return paginated_threads(total, threads)


@router.get(
    "/mentions/{kb_type}/{kb_id}/",
    response_model=PaginatedThreads,
    responses=_error_responses(422),
)
async def list_mentions(
    kb_type: KbType,
    kb_id: ItemId,
    db: DbTx,
    user: CurrentUser,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit_: Annotated[int, Query(alias="limit", ge=1, le=MAX_PAGE_SIZE)] = 20,
) -> PaginatedThreads:
    """Threads that link this KNOWBASE document or measure (visible to the caller), latest
    activity first. Answered from our own database; the KNOWBASE is not called."""
    total, threads = await crud_thread.list_mentions(
        db, kb_type=kb_type, kb_id=kb_id, user=user, skip=skip, limit=limit_
    )
    return paginated_threads(total, threads)


@router.get("/{slug}", response_model=ThreadDetail, responses=_error_responses(404))
async def get_thread(slug: str, db: DbTx, user: CurrentUser) -> ThreadDetail:
    """One thread, if the caller may see it."""
    thread = await crud_thread.get_thread_by_slug(db, slug=slug, user=user)
    if thread is None:
        raise crud_thread.not_found()
    return await _detail(db, thread)


@router.post(
    "/",
    response_model=ThreadDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(CREATE_LIMIT)],
    responses=_error_responses(401, 403, 422, 429, 502, 503),
)
async def create_thread(
    body: ThreadCreate, user: VerifiedUser, db: DbTx, kb: Knowbase
) -> ThreadDetail:
    """Open a thread. Trusted members and admins publish immediately; a first thread waits for
    approval (``pending``)."""
    thread = await crud_thread.create_thread(
        db,
        author=user,
        category_id=body.category_id,
        title=body.title,
        body_html=body.body_html,
        locale=body.locale,
        tag_names=body.tags,
        knowbase_links=[(link.kb_type, link.kb_id) for link in body.knowbase_links],
        knowbase=kb,
    )
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="thread.created",
        target_type="thread",
        target_id=thread.id,
        metadata={
            "thread_id": thread.id,
            "status": thread.status.value,
            "category_id": thread.category_id,
        },
    )
    return await _detail(db, thread)


@router.patch(
    "/{thread_id}",
    response_model=ThreadDetail,
    responses=_error_responses(401, 403, 404, 409, 422, 423, 502, 503),
)
async def update_thread(
    thread_id: int, body: ThreadUpdate, user: VerifiedUser, db: DbTx, kb: Knowbase
) -> ThreadDetail:
    """Edit a thread (its author, or an admin; only admins edit a locked thread). The status
    does not change."""
    thread = await crud_thread.get_editable_thread(db, thread_id=thread_id, user=user)
    changed = await crud_thread.update_thread(
        db, thread=thread, user=user, data=body.model_dump(exclude_unset=True), knowbase=kb
    )
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="thread.updated",
            target_type="thread",
            target_id=thread.id,
            metadata={"fields": changed},
        )
    return await _refreshed_detail(db, thread.id)


@router.delete(
    "/{thread_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=_error_responses(401, 403, 404),
)
async def delete_thread(thread_id: int, user: VerifiedUser, db: DbTx) -> Response:
    """Soft-delete a thread (its author, or an admin)."""
    thread = await crud_thread.get_editable_thread(
        db, thread_id=thread_id, user=user, editing=False
    )
    previous = thread.status
    await crud_thread.soft_delete_thread(db, thread=thread)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="thread.deleted",
        target_type="thread",
        target_id=thread.id,
        metadata={"thread_id": thread.id, "previous_status": previous.value},
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- admin: pin / lock ------------------------------------------------------------------------


async def _toggle(
    db: DbTx, *, thread_id: int, user: User, flag: str, value: bool, action: str
) -> ThreadDetail:
    """Set ``is_pinned`` / ``is_locked``; audit only an actual change (repeats are no-ops)."""
    thread = await crud_thread.get_live_thread(db, thread_id=thread_id, user=user)
    if flag == "pinned":
        changed = await crud_thread.set_pinned(db, thread=thread, pinned=value)
    else:
        changed = await crud_thread.set_locked(db, thread=thread, locked=value)
    if changed:
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action=action,
            target_type="thread",
            target_id=thread.id,
            metadata={"thread_id": thread.id},
        )
    return await _refreshed_detail(db, thread.id)


_ADMIN_RESPONSES = _error_responses(401, 403, 404)


@router.post("/{thread_id}/pin", response_model=ThreadDetail, responses=_ADMIN_RESPONSES)
async def pin_thread(thread_id: int, user: AdminUser, db: DbTx) -> ThreadDetail:
    """Pin a thread to the top of its lists (admins; idempotent)."""
    return await _toggle(
        db, thread_id=thread_id, user=user, flag="pinned", value=True, action="thread.pinned"
    )


@router.post("/{thread_id}/unpin", response_model=ThreadDetail, responses=_ADMIN_RESPONSES)
async def unpin_thread(thread_id: int, user: AdminUser, db: DbTx) -> ThreadDetail:
    """Unpin a thread (admins; idempotent)."""
    return await _toggle(
        db, thread_id=thread_id, user=user, flag="pinned", value=False, action="thread.unpinned"
    )


@router.post("/{thread_id}/lock", response_model=ThreadDetail, responses=_ADMIN_RESPONSES)
async def lock_thread(thread_id: int, user: AdminUser, db: DbTx) -> ThreadDetail:
    """Lock a thread: no new replies, no edits by its author (admins; idempotent)."""
    return await _toggle(
        db, thread_id=thread_id, user=user, flag="locked", value=True, action="thread.locked"
    )


@router.post("/{thread_id}/unlock", response_model=ThreadDetail, responses=_ADMIN_RESPONSES)
async def unlock_thread(thread_id: int, user: AdminUser, db: DbTx) -> ThreadDetail:
    """Unlock a thread (admins; idempotent)."""
    return await _toggle(
        db, thread_id=thread_id, user=user, flag="locked", value=False, action="thread.unlocked"
    )
