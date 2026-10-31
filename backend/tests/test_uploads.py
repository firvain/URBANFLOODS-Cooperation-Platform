"""Increment 2f: image uploads (``/uploads``), static serving of ``/static/uploads`` and the
avatar on ``/auth/me``.

Files go to the session-wide temporary ``upload_dir`` (conftest). Users are committed and
removed by ``cleanup_users``; attachments they own are deleted first by the autouse
``_cleanup_attachments`` fixture below.
"""

from __future__ import annotations

import io
import os
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime

import pytest
from PIL import Image
from sqlalchemy import delete, select

from app.api.v1.endpoints import uploads as uploads_endpoints
from app.core import rate_limit
from app.core.config import settings
from app.db.models import Attachment, AuditLog, User
from app.db.session import AsyncSessionLocal
from tests.factories import (
    create_admin,
    create_attachment,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
IMAGES = f"{API}/uploads/images/"
MINE = f"{API}/uploads/mine/"
ME = f"{API}/auth/me"


def _upload_path(attachment_id: int) -> str:
    return f"{API}/uploads/{attachment_id}"


# --- fixtures and helpers ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
async def _cleanup_attachments(cleanup_users: set[str]) -> AsyncIterator[None]:
    """Delete attachments uploaded by the test's users (before ``cleanup_users`` removes the
    users, since this fixture is torn down first)."""
    yield
    if not cleanup_users:
        return
    async with AsyncSessionLocal() as session, session.begin():
        ids = select(User.id).where(User.email.in_(cleanup_users))
        await session.execute(delete(Attachment).where(Attachment.uploader_id.in_(ids)))


@pytest.fixture
def limits(monkeypatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    rate_limit.reset()
    yield
    rate_limit.reset()


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


def _png(size: tuple[int, int] = (64, 48), color=(20, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def _gif() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, "GIF")
    return buf.getvalue()


async def _upload(
    client,
    data: bytes | None = None,
    *,
    alt_text: str | None = "A river gauge at dawn",
    kind: str | None = None,
    content_type: str = "image/png",
    filename: str = "photo.png",
):
    form: dict[str, str] = {}
    if alt_text is not None:
        form["alt_text"] = alt_text
    if kind is not None:
        form["kind"] = kind
    files = {"file": (filename, _png() if data is None else data, content_type)}
    return await client.post(IMAGES, files=files, data=form)


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_validation(response, field: str) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert field in detail["fields"], detail


async def _attachment(db, attachment_id: int) -> Attachment:
    stmt = (
        select(Attachment)
        .where(Attachment.id == attachment_id)
        .execution_options(populate_existing=True)
    )
    return (await db.execute(stmt)).scalar_one()


async def _attachments_of(db, user_id: int) -> list[Attachment]:
    stmt = (
        select(Attachment)
        .where(Attachment.uploader_id == user_id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


async def _audit(db, action: str, attachment_id: int) -> list[AuditLog]:
    stmt = select(AuditLog).where(
        AuditLog.action == action,
        AuditLog.target_type == "attachment",
        AuditLog.target_id == attachment_id,
    )
    return list((await db.scalars(stmt)).all())


def _files_of(upload_dir, attachment: Attachment) -> list:
    return [upload_dir / attachment.storage_path, upload_dir / attachment.thumb_path]


# --- auth -------------------------------------------------------------------------------------


async def test_anonymous_upload_is_401(client):
    _assert_error(await _upload(client), 401, "auth.not_authenticated")


async def test_unverified_upload_is_403(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, factory=create_user)
    await login_as(client, user)

    _assert_error(await _upload(client), 403, "auth.email_not_verified")


# --- create -----------------------------------------------------------------------------------


async def test_valid_png_is_stored_as_webp(client, db_session, cleanup_users, upload_dir):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await _upload(client, _png((64, 48)), alt_text="  A river gauge at dawn  ")

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "id",
        "url",
        "thumb_url",
        "width",
        "height",
        "size_bytes",
        "mime",
        "alt_text",
        "created_at",
    }
    assert body["mime"] == "image/webp"
    assert (body["width"], body["height"]) == (64, 48)
    assert body["alt_text"] == "A river gauge at dawn"
    now = datetime.now(UTC)
    prefix = f"{settings.UPLOAD_URL_PREFIX}/{now:%Y/%m}/"
    assert body["url"].startswith(prefix) and body["url"].endswith(".webp")
    assert body["thumb_url"] == body["url"].removesuffix(".webp") + "_thumb.webp"

    row = await _attachment(db_session, body["id"])
    assert row.uploader_id == user.id
    assert row.deleted_at is None
    assert row.mime == "image/webp"
    assert row.original_filename == "photo.png"
    assert row.alt_text == "A river gauge at dawn"
    assert body["url"] == f"{settings.UPLOAD_URL_PREFIX}/{row.storage_path}"
    main, thumb = _files_of(upload_dir, row)
    assert main.is_file() and thumb.is_file()
    assert main.read_bytes()[8:12] == b"WEBP"
    assert row.size_bytes == body["size_bytes"] == main.stat().st_size
    # Random, unguessable names; nothing of the original filename is on disk.
    assert "photo" not in row.storage_path

    (entry,) = await _audit(db_session, "upload.created", row.id)
    assert entry.actor_id == user.id
    assert entry.metadata_ == {
        "attachment_id": row.id,
        "size_bytes": row.size_bytes,
        "kind": "image",
    }
    assert "photo" not in str(entry.metadata_)


async def test_cover_kind_is_accepted_and_audited(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await _upload(client, kind="cover")

    assert response.status_code == 201, response.text
    (entry,) = await _audit(db_session, "upload.created", response.json()["id"])
    assert entry.metadata_["kind"] == "cover"


@pytest.mark.parametrize(
    "alt_text", [None, "", "   ", "x" * 301], ids=["missing", "empty", "blank", "too-long"]
)
async def test_alt_text_is_required_and_bounded(client, db_session, cleanup_users, alt_text):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    _assert_validation(await _upload(client, alt_text=alt_text), "alt_text")
    assert await _attachments_of(db_session, user.id) == []


async def test_alt_text_of_300_characters_is_accepted(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await _upload(client, alt_text="x" * 300)

    assert response.status_code == 201, response.text


async def test_unknown_kind_is_422(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    _assert_validation(await _upload(client, kind="banner"), "kind")


async def test_missing_file_is_422(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await client.post(IMAGES, data={"alt_text": "An image"}, files={"x": ("a", b"b")})

    _assert_validation(response, "file")


async def test_oversized_body_is_413(client, db_session, cleanup_users, upload_dir, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    before = sorted(upload_dir.rglob("*"))

    response = await _upload(client, os.urandom(1536 * 1024))

    _assert_error(response, 413, "uploads.too_large")
    assert await _attachments_of(db_session, user.id) == []
    assert sorted(upload_dir.rglob("*")) == before


async def test_declared_non_image_type_is_415(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    response = await _upload(client, content_type="text/plain", filename="notes.txt")

    _assert_error(response, 415, "uploads.unsupported_type")


async def test_gif_declared_as_png_is_415(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    _assert_error(await _upload(client, _gif()), 415, "uploads.unsupported_type")
    assert await _attachments_of(db_session, user.id) == []


async def test_garbage_declared_as_png_is_422(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    _assert_error(await _upload(client, os.urandom(4096)), 422, "uploads.invalid_image")


# --- static serving ---------------------------------------------------------------------------


async def test_uploaded_file_is_served_as_webp_with_nosniff(
    client, db_session, cleanup_users, upload_dir
):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    body = (await _upload(client)).json()
    row = await _attachment(db_session, body["id"])

    for url, path in ((body["url"], row.storage_path), (body["thumb_url"], row.thumb_path)):
        response = await client.get(url)

        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/webp"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.content == (upload_dir / path).read_bytes()


async def test_missing_static_file_is_404_with_nosniff(client):
    response = await client.get(f"{settings.UPLOAD_URL_PREFIX}/2026/01/nope.webp")

    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"


async def test_static_path_traversal_is_refused(client):
    response = await client.get(f"{settings.UPLOAD_URL_PREFIX}/../../pyproject.toml")

    assert response.status_code == 404


async def test_static_rejects_unsafe_methods(client):
    response = await client.post(f"{settings.UPLOAD_URL_PREFIX}/2026/01/nope.webp")

    assert response.status_code == 405


# --- list mine --------------------------------------------------------------------------------


async def test_list_mine_requires_auth(client):
    _assert_error(await client.get(MINE), 401, "auth.not_authenticated")


async def test_list_mine_is_newest_first_and_excludes_deleted_and_others(
    client, db_session, cleanup_users
):
    user = await _committed(db_session, cleanup_users)
    other = await _committed(db_session, cleanup_users)
    await create_attachment(db_session, uploader_id=user.id, deleted_at=datetime.now(UTC))
    await create_attachment(db_session, uploader_id=other.id)
    await db_session.commit()
    await login_as(client, user)
    first = (await _upload(client, alt_text="first")).json()
    second = (await _upload(client, alt_text="second")).json()

    response = await client.get(MINE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == [second["id"], first["id"]]
    assert body["items"][0] == second


async def test_list_mine_paginates(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    for _ in range(3):
        await create_attachment(db_session, uploader_id=user.id)
    await db_session.commit()
    await login_as(client, user)

    body = (await client.get(MINE, params={"skip": 1, "limit": 1})).json()

    assert body["total"] == 3
    assert len(body["items"]) == 1


async def test_unverified_user_can_list_own_uploads(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users, factory=create_user)
    await login_as(client, user)

    response = await client.get(MINE)

    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}


# --- delete -----------------------------------------------------------------------------------


async def test_owner_deletes_upload(client, db_session, cleanup_users, upload_dir):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    body = (await _upload(client)).json()
    row = await _attachment(db_session, body["id"])
    files = _files_of(upload_dir, row)

    response = await client.delete(_upload_path(row.id))

    assert response.status_code == 204, response.text
    assert all(not path.exists() for path in files)
    assert (await _attachment(db_session, row.id)).deleted_at is not None
    (entry,) = await _audit(db_session, "upload.deleted", row.id)
    assert entry.actor_id == user.id
    assert (await client.get(MINE)).json()["total"] == 0
    assert (await client.get(body["url"])).status_code == 404
    _assert_error(await client.delete(_upload_path(row.id)), 404, "uploads.not_found")


async def test_other_user_cannot_delete(
    client, other_client, db_session, cleanup_users, upload_dir
):
    owner = await _committed(db_session, cleanup_users)
    intruder = await _committed(db_session, cleanup_users)
    await login_as(client, owner)
    await login_as(other_client, intruder)
    row = await _attachment(db_session, (await _upload(client)).json()["id"])

    response = await other_client.delete(_upload_path(row.id))

    _assert_error(response, 404, "uploads.not_found")
    assert all(path.exists() for path in _files_of(upload_dir, row))
    assert (await _attachment(db_session, row.id)).deleted_at is None


async def test_admin_deletes_any_upload(
    client, other_client, db_session, cleanup_users, upload_dir
):
    owner = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    await login_as(client, owner)
    await login_as(other_client, admin)
    row = await _attachment(db_session, (await _upload(client)).json()["id"])

    response = await other_client.delete(_upload_path(row.id))

    assert response.status_code == 204, response.text
    assert all(not path.exists() for path in _files_of(upload_dir, row))
    (entry,) = await _audit(db_session, "upload.deleted", row.id)
    assert entry.actor_id == admin.id


async def test_delete_unknown_upload_is_404(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)

    _assert_error(await client.delete(_upload_path(2_000_000_000)), 404, "uploads.not_found")


async def test_delete_requires_auth(client):
    _assert_error(await client.delete(_upload_path(1)), 401, "auth.not_authenticated")


# --- avatar -----------------------------------------------------------------------------------


async def test_avatar_upload_sets_and_replaces_avatar(
    client, db_session, cleanup_users, upload_dir
):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    assert (await client.get(ME)).json()["avatar_url"] is None

    first = (await _upload(client, kind="avatar")).json()

    assert (await client.get(ME)).json()["avatar_url"] == first["url"]
    old = await _attachment(db_session, first["id"])
    old_files = _files_of(upload_dir, old)

    second = (await _upload(client, _png(color=(200, 0, 0)), kind="avatar")).json()

    assert (await client.get(ME)).json()["avatar_url"] == second["url"]
    assert (await _attachment(db_session, first["id"])).deleted_at is not None
    assert all(not path.exists() for path in old_files)
    new = await _attachment(db_session, second["id"])
    assert all(path.exists() for path in _files_of(upload_dir, new))
    assert [item["id"] for item in (await client.get(MINE)).json()["items"]] == [second["id"]]


async def test_non_avatar_upload_keeps_avatar(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    avatar = (await _upload(client, kind="avatar")).json()

    await _upload(client, kind="image")

    assert (await client.get(ME)).json()["avatar_url"] == avatar["url"]


async def test_deleting_the_avatar_clears_it(client, db_session, cleanup_users):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    avatar = (await _upload(client, kind="avatar")).json()

    assert (await client.delete(_upload_path(avatar["id"]))).status_code == 204

    assert (await client.get(ME)).json()["avatar_url"] is None


async def test_admin_deleting_a_users_avatar_clears_it(
    client, other_client, db_session, cleanup_users
):
    user = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    await login_as(client, user)
    await login_as(other_client, admin)
    avatar = (await _upload(client, kind="avatar")).json()

    assert (await other_client.delete(_upload_path(avatar["id"]))).status_code == 204

    assert (await client.get(ME)).json()["avatar_url"] is None


# --- limits -----------------------------------------------------------------------------------


async def test_daily_cap_per_user(client, db_session, cleanup_users, monkeypatch):
    monkeypatch.setattr(uploads_endpoints, "DAILY_UPLOAD_CAP", 2)
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    first = (await _upload(client)).json()
    assert (await _upload(client)).status_code == 201
    # Deleting does not give the slot back.
    assert (await client.delete(_upload_path(first["id"]))).status_code == 204

    _assert_error(await _upload(client), 409, "uploads.daily_limit")
    assert len(await _attachments_of(db_session, user.id)) == 2


async def test_daily_cap_defaults_to_thirty():
    assert uploads_endpoints.DAILY_UPLOAD_CAP == 30


async def test_ip_rate_limit_is_429(client, db_session, cleanup_users, limits):
    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    # Requests the endpoint rejects still count against the limit.
    statuses = [(await _upload(client, content_type="text/plain")).status_code for _ in range(30)]
    assert statuses == [415] * 30

    response = await _upload(client)

    assert response.status_code == 429, response.text
    assert response.json()["detail"]["code"] == "rate.limited"
    assert 1 <= int(response.headers["retry-after"]) <= 86400


async def test_admin_user_list_and_detail_show_avatar_url(
    client, other_client, db_session, cleanup_users
):
    user = await _committed(db_session, cleanup_users)
    admin = await _committed(db_session, cleanup_users, factory=create_admin)
    await login_as(client, user)
    await login_as(other_client, admin)
    avatar = (await _upload(client, kind="avatar")).json()

    listed = await other_client.get(f"{API}/admin/users/", params={"q": user.email})
    detail = await other_client.get(f"{API}/admin/users/{user.id}")

    assert listed.status_code == 200, listed.text
    (item,) = [item for item in listed.json()["items"] if item["id"] == user.id]
    assert item["avatar_url"] == avatar["url"]
    assert detail.status_code == 200, detail.text
    assert detail.json()["avatar_url"] == avatar["url"]


async def test_served_upload_has_the_webp_content_type(
    client, db_session, cleanup_users, monkeypatch
):
    """The container's Python knows no .webp mapping by default; the endpoint module registers
    it, so the served file is image/webp with nosniff (otherwise browsers show a broken image)."""
    import mimetypes

    from app.api.v1.endpoints import uploads as uploads_module

    # Simulate a platform without the mapping, then re-run the module-level registration.
    monkeypatch.setitem(mimetypes.types_map, ".webp", "application/octet-stream")
    mimetypes.add_type("image/webp", ".webp")
    assert mimetypes.guess_type("x.webp")[0] == "image/webp"
    assert hasattr(uploads_module, "UploadStaticFiles")

    user = await _committed(db_session, cleanup_users)
    await login_as(client, user)
    response = await _upload(client)
    assert response.status_code == 201, response.text
    url = response.json()["url"]
    served = await client.get(url)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/webp")
    assert served.headers["x-content-type-options"] == "nosniff"
