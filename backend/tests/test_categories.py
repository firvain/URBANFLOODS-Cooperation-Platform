"""Increment 2d: blog/forum categories - public list and detail, admin create/update/archive.

Rows the app commits are removed by ``cleanup_users`` / ``cleanup_categories`` /
``cleanup_posts``. Tests that would archive seeded categories run through the crud layer inside
the ``db_session`` transaction (rolled back), so the seed is never changed for other tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.core.config import settings
from app.core.exceptions import AppError
from app.crud import category as crud_category
from app.db.enums import CategoryKind, ContentStatus
from app.db.models import AuditLog, Category, User
from tests.factories import (
    create_admin,
    create_category,
    create_post,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
CATS = f"{API}/categories/"

SEEDED_BLOG = ["news", "best-practices", "events", "resources", "policy"]
SEEDED_FORUM = ["general", "measures", "early-warning", "policy"]
OUT_FIELDS = {
    "id",
    "kind",
    "slug",
    "name",
    "name_i18n",
    "description",
    "sort_order",
    "is_archived",
    "admin_only",
    "post_count",
}


# --- helpers ----------------------------------------------------------------------------------


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _admin_client(client, db, cleanup_users) -> User:
    admin = await _committed(db, cleanup_users, factory=create_admin)
    await login_as(client, admin)
    return admin


async def _committed_category(db, cleanup_categories, **kwargs) -> Category:
    category = await create_category(db, **kwargs)
    cleanup_categories.add(category.id)
    await db.commit()
    return category


async def _audit(db, category_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "category",
            AuditLog.target_id == category_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_validation(response, field_prefix: str) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert any(field.startswith(field_prefix) for field in detail["fields"]), detail


def _slugs(items, kind: str, seeded: list[str]) -> list[str]:
    return [i["slug"] for i in items if i["kind"] == kind and i["slug"] in seeded]


# --- public list and detail -------------------------------------------------------------------


async def test_list_returns_seeded_categories_in_order(client):
    response = await client.get(CATS)

    assert response.status_code == 200, response.text
    body = response.json()
    items = body["items"]
    assert body["total"] == len(items)
    assert _slugs(items, "blog", SEEDED_BLOG) == SEEDED_BLOG
    assert _slugs(items, "forum", SEEDED_FORUM) == SEEDED_FORUM
    news = next(i for i in items if i["kind"] == "blog" and i["slug"] == "news")
    assert set(news) == OUT_FIELDS
    assert news["name"] == "News"
    assert news["is_archived"] is False
    assert news["post_count"] == 0
    resources = next(i for i in items if i["kind"] == "blog" and i["slug"] == "resources")
    assert resources["admin_only"] is True
    # Blog before forum, then sort_order within the kind.
    kinds = [i["kind"] for i in items]
    assert kinds == sorted(kinds)


async def test_list_filters_by_kind(client):
    blog = (await client.get(CATS, params={"kind": "blog"})).json()
    forum = (await client.get(CATS, params={"kind": "forum"})).json()

    assert {i["kind"] for i in blog["items"]} == {"blog"}
    assert [i["slug"] for i in blog["items"]][:5] == SEEDED_BLOG
    assert {i["kind"] for i in forum["items"]} == {"forum"}
    assert [i["slug"] for i in forum["items"]][:4] == SEEDED_FORUM
    assert (await client.get(CATS, params={"kind": "wiki"})).status_code == 422


async def test_archived_hidden_for_anon_and_members_shown_to_admin_with_flag(
    client, db_session, cleanup_users, cleanup_categories
):
    archived = await _committed_category(
        db_session, cleanup_categories, is_archived=True, sort_order=1000
    )

    anon = (await client.get(CATS, params={"include_archived": "true"})).json()
    assert archived.id not in {i["id"] for i in anon["items"]}

    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    as_member = (await client.get(CATS, params={"include_archived": "true"})).json()
    assert archived.id not in {i["id"] for i in as_member["items"]}

    await _admin_client(client, db_session, cleanup_users)
    default = (await client.get(CATS)).json()
    assert archived.id not in {i["id"] for i in default["items"]}
    with_flag = (await client.get(CATS, params={"include_archived": "true"})).json()
    row = next(i for i in with_flag["items"] if i["id"] == archived.id)
    assert row["is_archived"] is True


async def test_detail_by_kind_and_slug(client):
    response = await client.get(f"{CATS}forum/policy")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "forum"
    assert body["slug"] == "policy"
    assert body["name"] == "Policy and governance"
    assert body["post_count"] == 0

    _assert_error(await client.get(f"{CATS}blog/no-such-thing"), 404, "categories.not_found")
    _assert_error(await client.get(f"{CATS}forum/resources"), 404, "categories.not_found")


async def test_post_count_counts_only_published_posts(
    client, db_session, cleanup_categories, cleanup_posts
):
    category = await create_category(db_session)
    cleanup_categories.add(category.id)
    for status in (
        ContentStatus.PUBLISHED,
        ContentStatus.PUBLISHED,
        ContentStatus.PENDING,
        ContentStatus.HIDDEN,
        ContentStatus.DELETED,
    ):
        post = await create_post(db_session, category_id=category.id, status=status)
        cleanup_posts.add(post.id)
    await db_session.commit()

    detail = (await client.get(f"{CATS}blog/{category.slug}")).json()
    assert detail["post_count"] == 2
    listed = (await client.get(CATS, params={"kind": "blog"})).json()
    assert next(i for i in listed["items"] if i["id"] == category.id)["post_count"] == 2


# --- admin create -----------------------------------------------------------------------------


async def test_create_requires_admin(client, db_session, cleanup_users, cleanup_categories):
    body = {"kind": "blog", "name": "Flood Maps & Data"}

    _assert_error(await client.post(CATS, json=body), 401, "auth.not_authenticated")

    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    _assert_error(await client.post(CATS, json=body), 403, "auth.forbidden")

    admin = await _admin_client(client, db_session, cleanup_users)
    response = await client.post(CATS, json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    cleanup_categories.add(created["id"])
    assert set(created) == OUT_FIELDS
    assert created["slug"] == "flood-maps-data"
    assert created["kind"] == "blog"
    assert created["name_i18n"] == {}
    assert created["admin_only"] is False
    assert created["is_archived"] is False
    assert created["post_count"] == 0

    rows = await _audit(db_session, created["id"], "category.created")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_["slug"] == "flood-maps-data"


async def test_create_with_explicit_slug_i18n_and_admin_only(
    client, db_session, cleanup_users, cleanup_categories
):
    await _admin_client(client, db_session, cleanup_users)

    response = await client.post(
        CATS,
        json={
            "kind": "forum",
            "name": "Datasets",
            "slug": "open-datasets-2d",
            "name_i18n": {"el": "Σύνολα δεδομένων", "it": "Dati"},
            "description": "Open flood data.",
            "sort_order": 50,
            "admin_only": True,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    cleanup_categories.add(body["id"])
    assert body["slug"] == "open-datasets-2d"
    assert body["name_i18n"] == {"el": "Σύνολα δεδομένων", "it": "Dati"}
    assert body["description"] == "Open flood data."
    assert body["sort_order"] == 50
    assert body["admin_only"] is True


async def test_duplicate_slug_per_kind_conflicts_but_other_kind_is_fine(
    client, db_session, cleanup_users, cleanup_categories
):
    await _admin_client(client, db_session, cleanup_users)

    # "news" exists for blog only.
    _assert_error(
        await client.post(CATS, json={"kind": "blog", "name": "News"}), 409, "categories.slug_taken"
    )
    response = await client.post(CATS, json={"kind": "forum", "name": "News"})
    assert response.status_code == 201, response.text
    cleanup_categories.add(response.json()["id"])
    assert response.json()["slug"] == "news"


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({"kind": "blog", "name": "x"}, "name"),
        ({"kind": "blog", "name": "a" * 81}, "name"),
        ({"kind": "wiki", "name": "Valid name"}, "kind"),
        ({"kind": "blog", "name": "Valid name", "slug": "Bad Slug"}, "slug"),
        ({"kind": "blog", "name": "Valid name", "slug": "-bad"}, "slug"),
        ({"kind": "blog", "name": "Valid name", "slug": "a" * 81}, "slug"),
        ({"kind": "blog", "name": "Valid name", "name_i18n": {"de": "Name"}}, "name_i18n"),
        ({"kind": "blog", "name": "Valid name", "name_i18n": {"el": ""}}, "name_i18n"),
        ({"kind": "blog", "name": "Valid name", "description": "d" * 501}, "description"),
    ],
)
async def test_create_validation(client, db_session, cleanup_users, body, field):
    await _admin_client(client, db_session, cleanup_users)

    _assert_validation(await client.post(CATS, json=body), field)


# --- admin update -----------------------------------------------------------------------------


async def test_patch_renames_and_audits_changed_fields(
    client, db_session, cleanup_users, cleanup_categories
):
    category = await _committed_category(db_session, cleanup_categories)
    admin = await _admin_client(client, db_session, cleanup_users)

    response = await client.patch(
        f"{CATS}{category.id}",
        json={"name": "Renamed category", "sort_order": category.sort_order, "admin_only": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "Renamed category"
    assert body["admin_only"] is True
    assert body["slug"] == category.slug  # renaming never changes the slug
    rows = await _audit(db_session, category.id, "category.updated")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_ == {"fields": ["admin_only", "name"]}

    # A no-op PATCH writes no audit row; admin_only toggles back.
    await client.patch(f"{CATS}{category.id}", json={"name": "Renamed category"})
    assert len(await _audit(db_session, category.id, "category.updated")) == 1
    response = await client.patch(f"{CATS}{category.id}", json={"admin_only": False})
    assert response.json()["admin_only"] is False


async def test_patch_slug_allowed_without_posts_and_locked_with_posts(
    client, db_session, cleanup_users, cleanup_categories, cleanup_posts
):
    empty = await create_category(db_session)
    used = await create_category(db_session)
    cleanup_categories.update({empty.id, used.id})
    post = await create_post(db_session, category_id=used.id, status=ContentStatus.PENDING)
    cleanup_posts.add(post.id)
    await db_session.commit()
    await _admin_client(client, db_session, cleanup_users)

    new_slug = f"{empty.slug}-renamed"
    response = await client.patch(f"{CATS}{empty.id}", json={"slug": new_slug})
    assert response.status_code == 200, response.text
    assert response.json()["slug"] == new_slug

    _assert_error(
        await client.patch(f"{CATS}{used.id}", json={"slug": "something-else"}),
        409,
        "categories.slug_locked",
    )
    # The same slug again is not a change.
    response = await client.patch(f"{CATS}{used.id}", json={"slug": used.slug})
    assert response.status_code == 200, response.text


async def test_patch_slug_taken_and_validation_and_404(
    client, db_session, cleanup_users, cleanup_categories
):
    category = await _committed_category(db_session, cleanup_categories)
    await _admin_client(client, db_session, cleanup_users)

    _assert_error(
        await client.patch(f"{CATS}{category.id}", json={"slug": "news"}),
        409,
        "categories.slug_taken",
    )
    _assert_validation(
        await client.patch(f"{CATS}{category.id}", json={"name_i18n": {"xx": "Nope"}}),
        "name_i18n",
    )
    _assert_validation(await client.patch(f"{CATS}{category.id}", json={"name": None}), "name")
    _assert_error(
        await client.patch(f"{CATS}999999999", json={"name": "Whatever"}),
        404,
        "categories.not_found",
    )


async def test_patch_requires_admin(client, db_session, cleanup_users, cleanup_categories):
    category = await _committed_category(db_session, cleanup_categories)

    _assert_error(
        await client.patch(f"{CATS}{category.id}", json={"name": "Hacked"}),
        401,
        "auth.not_authenticated",
    )
    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    _assert_error(
        await client.patch(f"{CATS}{category.id}", json={"name": "Hacked"}), 403, "auth.forbidden"
    )


# --- admin archive ----------------------------------------------------------------------------


async def test_delete_archives_hides_and_audits(
    client, db_session, cleanup_users, cleanup_categories
):
    category = await _committed_category(db_session, cleanup_categories)
    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    _assert_error(await client.delete(f"{CATS}{category.id}"), 403, "auth.forbidden")

    admin = await _admin_client(client, db_session, cleanup_users)
    response = await client.delete(f"{CATS}{category.id}")

    assert response.status_code == 204, response.text
    listed = (await client.get(CATS)).json()
    assert category.id not in {i["id"] for i in listed["items"]}
    category_id, admin_id = category.id, admin.id
    db_session.expire_all()
    assert (await db_session.get(Category, category_id)).is_archived is True
    rows = await _audit(db_session, category_id, "category.archived")
    assert len(rows) == 1
    assert rows[0].actor_id == admin_id

    # Archiving again is a no-op.
    assert (await client.delete(f"{CATS}{category_id}")).status_code == 204
    assert len(await _audit(db_session, category_id, "category.archived")) == 1
    _assert_error(await client.delete(f"{CATS}999999999"), 404, "categories.not_found")


async def test_patch_unarchive(client, db_session, cleanup_users, cleanup_categories):
    category = await _committed_category(db_session, cleanup_categories, is_archived=True)
    await _admin_client(client, db_session, cleanup_users)

    response = await client.patch(f"{CATS}{category.id}", json={"is_archived": False})

    assert response.status_code == 200, response.text
    assert response.json()["is_archived"] is False


async def test_archive_last_active_category_of_a_kind_is_refused(db_session):
    """Runs in the rolled-back ``db_session`` so the seeded categories are never changed."""
    general = await crud_category.get_category(db_session, kind=CategoryKind.FORUM, slug="general")
    assert general is not None
    await db_session.execute(
        update(Category)
        .where(Category.kind == CategoryKind.FORUM, Category.id != general.id)
        .values(is_archived=True)
    )

    with pytest.raises(AppError) as excinfo:
        await crud_category.archive_category(db_session, category=general)
    assert excinfo.value.status_code == 409
    assert excinfo.value.code == "categories.last_active"

    with pytest.raises(AppError) as excinfo:
        await crud_category.update_category(
            db_session, category=general, changes={"is_archived": True}
        )
    assert excinfo.value.code == "categories.last_active"

    # Blog categories are unaffected.
    news = await crud_category.get_category(db_session, kind=CategoryKind.BLOG, slug="news")
    assert await crud_category.archive_category(db_session, category=news) is True


# --- crud -------------------------------------------------------------------------------------


async def test_crud_list_and_get(db_session):
    rows = await crud_category.list_categories(db_session, kind=CategoryKind.FORUM)
    assert [c.slug for c, _ in rows][:4] == SEEDED_FORUM
    assert all(count == 0 for _, count in rows)

    news = await crud_category.get_category(db_session, kind=CategoryKind.BLOG, slug="news")
    assert news is not None
    assert (await crud_category.get_category_by_id(db_session, category_id=news.id)) is news
    assert await crud_category.get_category_by_id(db_session, category_id=999999999) is None
    assert await crud_category.count_published_posts(db_session, category_id=news.id) == 0


async def test_crud_create_slug_from_greek_name(db_session):
    category = await crud_category.create_category(
        db_session, kind=CategoryKind.BLOG, name="Πλημμύρες"
    )
    assert category.slug == "plemmures"
    assert category.name_i18n == {}
