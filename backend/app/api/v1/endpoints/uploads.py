"""Image uploads (post covers, inline editor images, avatars) and the static files app that
serves them under ``UPLOAD_URL_PREFIX``.

Every upload is re-encoded to WebP by ``services/images.py`` (format sniffed by Pillow, metadata
stripped). Files are written before the row is inserted (and removed again if the insert
fails); files of deleted attachments are removed only after the transaction has committed, as a
background task. Orphans left by a failed commit are for the scheduled sweep.
"""

from __future__ import annotations

import mimetypes
import os
import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Query,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from pydantic import StringConstraints
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.api.v1.schemas.upload import UploadKind, UploadList, UploadOut
from app.core.config import settings
from app.core.deps import ADMIN_ROLES, AuthUser, DbTx, VerifiedUser
from app.core.exceptions import AppError, error_body
from app.core.rate_limit import limit
from app.crud import attachment as crud_attachment
from app.crud import audit as crud_audit
from app.db.models import Attachment, User
from app.services import images
from app.services.images import ALLOWED_MIME, ImageError

router = APIRouter()

# Uploads a user may make per UTC day (deleted ones count), on top of the per-IP rate limit.
DAILY_UPLOAD_CAP = 30
MIB = 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
ORIGINAL_FILENAME_MAX = 255
NOSNIFF = ("X-Content-Type-Options", "nosniff")

AltText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]

_IMAGE_ERRORS: dict[str, tuple[int, str]] = {
    images.UNSUPPORTED_TYPE: (415, "Only JPEG, PNG and WebP images are accepted."),
    images.INVALID_IMAGE: (422, "The file is not a valid image."),
    images.ANIMATED: (422, "Animated images are not accepted."),
    images.TOO_LARGE_PIXELS: (422, "The image has too many pixels."),
}


def _error_responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI docs for the uniform error body."""
    example = error_body("some.code", "English fallback message.")
    return {
        code: {"description": "Error", "content": {"application/json": {"example": example}}}
        for code in codes
    }


def _not_found() -> AppError:
    return AppError(404, "uploads.not_found", "Upload not found.")


def _unsupported_type() -> AppError:
    code = images.UNSUPPORTED_TYPE
    return AppError(_IMAGE_ERRORS[code][0], code, _IMAGE_ERRORS[code][1])


def _media_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _original_filename(filename: str | None) -> str:
    """The client's file name without any directory part, truncated (kept in the row only)."""
    name = os.path.basename((filename or "").replace("\\", "/")).strip()
    return name[:ORIGINAL_FILENAME_MAX] or "upload"


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read the upload in chunks, aborting with 413 as soon as it exceeds ``max_bytes``."""
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(READ_CHUNK_BYTES):
        size += len(chunk)
        if size > max_bytes:
            raise AppError(
                413,
                "uploads.too_large",
                f"The file is larger than {settings.MAX_UPLOAD_MB} MiB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


async def _process(data: bytes) -> images.ProcessedImage:
    try:
        return await run_in_threadpool(
            images.process_image,
            data,
            max_px=settings.UPLOAD_MAX_PX,
            thumb_px=settings.UPLOAD_THUMB_PX,
        )
    except ImageError as exc:
        status_code, message = _IMAGE_ERRORS.get(exc.code, (422, "The image is invalid."))
        raise AppError(status_code, exc.code, message) from exc


def _schedule_file_deletion(background: BackgroundTasks, attachment: Attachment) -> None:
    """Remove the attachment's files after the response (so after the commit)."""
    background.add_task(
        images.delete_files, settings.UPLOAD_DIR, attachment.storage_path, attachment.thumb_path
    )


async def _replace_avatar(
    db: DbTx, *, user: User, attachment: Attachment, background: BackgroundTasks
) -> None:
    previous = user.avatar
    user.avatar = attachment
    await db.flush()
    if previous is not None and previous.deleted_at is None:
        await crud_attachment.soft_delete_attachment(db, attachment=previous)
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="upload.deleted",
            target_type="attachment",
            target_id=previous.id,
            metadata={"attachment_id": previous.id, "reason": "avatar_replaced"},
        )
        _schedule_file_deletion(background, previous)


@router.post(
    "/images/",
    response_model=UploadOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(limit("uploads.images", 30, 86400))],
    responses=_error_responses(401, 403, 409, 413, 415, 422, 429),
)
async def upload_image(
    user: VerifiedUser,
    db: DbTx,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File(description="A JPEG, PNG or WebP image.")],
    alt_text: Annotated[AltText, Form(description="Alternative text (required).")],
    kind: Annotated[UploadKind, Form()] = UploadKind.IMAGE,
) -> UploadOut:
    """Upload an image (verified users). It is re-encoded to WebP (longest edge at most
    ``UPLOAD_MAX_PX``) with a thumbnail, and stripped of all metadata. ``kind=avatar`` also
    makes it the user's avatar, replacing (and deleting) the previous one."""
    if _media_type(file.content_type) not in ALLOWED_MIME:
        raise _unsupported_type()
    if await crud_attachment.count_uploads_today(db, user_id=user.id) >= DAILY_UPLOAD_CAP:
        raise AppError(409, "uploads.daily_limit", "You have reached today's upload limit.")
    data = await _read_limited(file, settings.MAX_UPLOAD_MB * MIB)
    processed = await _process(data)

    upload_dir = settings.UPLOAD_DIR
    rel_path = images.storage_relative_path(datetime.now(UTC), uuid.uuid4())
    thumb_rel = images.thumb_relative_path(rel_path)
    await run_in_threadpool(
        images.save_files,
        upload_dir,
        rel_path,
        processed.main_bytes,
        thumb_rel,
        processed.thumb_bytes,
    )
    try:
        attachment = await crud_attachment.create_attachment(
            db,
            uploader_id=user.id,
            storage_path=rel_path,
            thumb_path=thumb_rel,
            original_filename=_original_filename(file.filename),
            mime=processed.mime,
            size_bytes=len(processed.main_bytes),
            width=processed.width,
            height=processed.height,
            alt_text=alt_text,
        )
        await crud_audit.log_action(
            db,
            actor_id=user.id,
            action="upload.created",
            target_type="attachment",
            target_id=attachment.id,
            metadata={
                "attachment_id": attachment.id,
                "size_bytes": attachment.size_bytes,
                "kind": kind.value,
            },
        )
        if kind is UploadKind.AVATAR:
            await _replace_avatar(db, user=user, attachment=attachment, background=background)
    except BaseException:
        await run_in_threadpool(images.delete_files, upload_dir, rel_path, thumb_rel)
        raise
    return UploadOut.model_validate(attachment)


@router.get("/mine/", response_model=UploadList, responses=_error_responses(401, 422))
async def list_my_uploads(
    user: AuthUser,
    db: DbTx,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> UploadList:
    """The signed-in user's uploads (not deleted), newest first."""
    total, items = await crud_attachment.list_for_uploader(
        db, user_id=user.id, skip=skip, limit=limit
    )
    return UploadList(total=total, items=[UploadOut.model_validate(item) for item in items])


@router.delete(
    "/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_error_responses(401, 404, 422),
)
async def delete_upload(
    attachment_id: int, user: AuthUser, db: DbTx, background: BackgroundTasks
) -> None:
    """Delete an upload (its uploader, or an admin). If it is someone's avatar, the avatar is
    cleared. Someone else's upload answers 404 to a member, as if it did not exist."""
    attachment = await crud_attachment.get_attachment(db, attachment_id=attachment_id)
    is_admin = user.role in ADMIN_ROLES and user.is_verified
    if attachment is None or (attachment.uploader_id != user.id and not is_admin):
        raise _not_found()
    await crud_attachment.soft_delete_attachment(db, attachment=attachment)
    await crud_audit.log_action(
        db,
        actor_id=user.id,
        action="upload.deleted",
        target_type="attachment",
        target_id=attachment.id,
        metadata={"attachment_id": attachment.id, "uploader_id": attachment.uploader_id},
    )
    _schedule_file_deletion(background, attachment)


# --- static files -----------------------------------------------------------------------------


# Slim Linux images ship no mapping for .webp, so StaticFiles would serve the re-encoded uploads
# as application/octet-stream (and nosniff then stops browsers from treating them as images).
mimetypes.add_type("image/webp", ".webp")


class UploadStaticFiles(StaticFiles):
    """Serves ``settings.UPLOAD_DIR`` (read on every request, so it follows the setting) and
    adds ``X-Content-Type-Options: nosniff`` to every response, errors included."""

    def __init__(self) -> None:
        super().__init__(directory=settings.UPLOAD_DIR, check_dir=False)

    async def check_config(self) -> None:
        # The lifespan creates the directory; nothing to check at the first request.
        return None

    def lookup_path(self, path: str) -> tuple[str, os.stat_result | None]:
        self.all_directories = [settings.UPLOAD_DIR]
        return super().lookup_path(path)

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            response = JSONResponse(
                status_code=exc.status_code,
                content=error_body(f"http.{exc.status_code}", str(exc.detail)),
                headers=exc.headers,
            )
        response.headers.setdefault(*NOSNIFF)
        return response
