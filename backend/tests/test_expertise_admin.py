"""Increment 5n: admin management of the expertise vocabulary (``GET ?include_inactive``,
``POST /expertise/``, ``PATCH /expertise/{id}``), and deactivated tags staying on members.

Tags the app commits are removed by ``cleanup_expertise`` (by id); users by ``cleanup_users`` /
``cleanup_user_ids``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.models import AuditLog, ExpertiseTag, User
from tests.factories import create_admin, create_verified_user, login_as

API = settings.API_V1_PREFIX
EXPERTISE = f"{API}/expertise/"
ME = f"{API}/auth/me"
OUT_FIELDS = {"id", "slug", "label", "sort_order", "is_active"}


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture
async def cleanup_expertise(database_url: str) -> AsyncIterator[set[int]]:
    """Ids of expertise tags the test commits; deleted afterwards."""
    from app.db.session import AsyncSessionLocal

    ids: set[int] = set()
    yield ids
    if not ids:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(ExpertiseTag).where(ExpertiseTag.id.in_(ids)))


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _admin_client(client, db, cleanup_users) -> User:
    admin = await _committed(db, cleanup_users, factory=create_admin)
    await login_as(client, admin)
    return admin


async def _committed_tag(db, cleanup_expertise, **kwargs) -> ExpertiseTag:
    values = {"slug": "zz-admin-tag", "label": "Admin tag", "sort_order": 500, **kwargs}
    tag = ExpertiseTag(**values)
    db.add(tag)
    await db.flush()
    cleanup_expertise.add(tag.id)
    await db.commit()
    return tag


async def _audit(db, tag_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "expertise_tag",
            AuditLog.target_id == tag_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


def _assert_validation(response, field: str) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert field in detail["fields"], detail


# --- list -------------------------------------------------------------------------------------


async def test_list_includes_is_active(client):
    body = (await client.get(EXPERTISE)).json()

    assert set(body["items"][0]) == OUT_FIELDS
    assert all(item["is_active"] for item in body["items"])


async def test_include_inactive_honoured_for_admins_only(
    client, db_session, cleanup_users, cleanup_expertise
):
    await _committed_tag(db_session, cleanup_expertise, slug="zz-retired", is_active=False)
    url = f"{EXPERTISE}?include_inactive=true"

    anon = (await client.get(url)).json()
    assert "zz-retired" not in {item["slug"] for item in anon["items"]}

    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    listed = (await client.get(url)).json()
    assert "zz-retired" not in {item["slug"] for item in listed["items"]}

    await _admin_client(client, db_session, cleanup_users)
    without_flag = (await client.get(EXPERTISE)).json()
    assert "zz-retired" not in {item["slug"] for item in without_flag["items"]}
    with_flag = (await client.get(url)).json()
    retired = [item for item in with_flag["items"] if item["slug"] == "zz-retired"]
    assert len(retired) == 1
    assert retired[0]["is_active"] is False
    assert with_flag["total"] == len(with_flag["items"]) == without_flag["total"] + 1


# --- create -----------------------------------------------------------------------------------


async def test_create_requires_admin(client, db_session, cleanup_users, cleanup_expertise):
    body = {"label": "Flood Insurance & Finance"}

    _assert_error(await client.post(EXPERTISE, json=body), 401, "auth.not_authenticated")

    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    _assert_error(await client.post(EXPERTISE, json=body), 403, "auth.forbidden")

    admin = await _admin_client(client, db_session, cleanup_users)
    response = await client.post(EXPERTISE, json=body)
    assert response.status_code == 201, response.text
    created = response.json()
    cleanup_expertise.add(created["id"])
    assert set(created) == OUT_FIELDS
    assert created["slug"] == "flood-insurance-finance"
    assert created["label"] == "Flood Insurance & Finance"
    assert created["sort_order"] == 0
    assert created["is_active"] is True

    rows = await _audit(db_session, created["id"], "expertise.created")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_ == {"slug": "flood-insurance-finance", "label": created["label"]}

    # The new tag is offered to members straight away.
    listed = (await client.get(EXPERTISE)).json()
    assert created["id"] in {item["id"] for item in listed["items"]}


async def test_create_with_explicit_slug_and_sort_order(
    client, db_session, cleanup_users, cleanup_expertise
):
    await _admin_client(client, db_session, cleanup_users)

    response = await client.post(
        EXPERTISE, json={"label": "  Drones  ", "slug": "zz-drones-5n", "sort_order": 99}
    )

    assert response.status_code == 201, response.text
    body = response.json()
    cleanup_expertise.add(body["id"])
    assert body["label"] == "Drones"
    assert body["slug"] == "zz-drones-5n"
    assert body["sort_order"] == 99


async def test_create_duplicate_slug_conflicts(client, db_session, cleanup_users):
    await _admin_client(client, db_session, cleanup_users)

    # "hydrology" is seeded; derived and explicit slugs both clash.
    _assert_error(
        await client.post(EXPERTISE, json={"label": "Hydrology"}), 409, "expertise.slug_taken"
    )
    _assert_error(
        await client.post(EXPERTISE, json={"label": "Water science", "slug": "hydrology"}),
        409,
        "expertise.slug_taken",
    )


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ({}, "label"),
        ({"label": "x"}, "label"),
        ({"label": "  x  "}, "label"),
        ({"label": "a" * 81}, "label"),
        ({"label": "Valid label", "slug": "Bad Slug"}, "slug"),
        ({"label": "Valid label", "slug": "-bad"}, "slug"),
        ({"label": "Valid label", "slug": "a" * 65}, "slug"),
        ({"label": "Valid label", "sort_order": -1}, "sort_order"),
    ],
)
async def test_create_validation(client, db_session, cleanup_users, body, field):
    await _admin_client(client, db_session, cleanup_users)

    _assert_validation(await client.post(EXPERTISE, json=body), field)


# --- update -----------------------------------------------------------------------------------


async def test_patch_requires_admin(client, db_session, cleanup_users, cleanup_expertise):
    tag = await _committed_tag(db_session, cleanup_expertise)
    url = f"{EXPERTISE}{tag.id}"

    _assert_error(await client.patch(url, json={"label": "Hacked"}), 401, "auth.not_authenticated")
    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    _assert_error(await client.patch(url, json={"label": "Hacked"}), 403, "auth.forbidden")


async def test_patch_updates_and_audits_changed_fields(
    client, db_session, cleanup_users, cleanup_expertise
):
    tag = await _committed_tag(db_session, cleanup_expertise)
    admin = await _admin_client(client, db_session, cleanup_users)
    url = f"{EXPERTISE}{tag.id}"

    response = await client.patch(
        url, json={"label": "Renamed tag", "slug": "zz-renamed-tag", "sort_order": tag.sort_order}
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["label"] == "Renamed tag"
    assert body["slug"] == "zz-renamed-tag"
    rows = await _audit(db_session, tag.id, "expertise.updated")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    assert rows[0].metadata_ == {"fields": ["label", "slug"]}

    # A no-op PATCH writes no audit row.
    await client.patch(url, json={"label": "Renamed tag"})
    assert len(await _audit(db_session, tag.id, "expertise.updated")) == 1


async def test_patch_deactivate_and_reactivate(
    client, db_session, cleanup_users, cleanup_expertise
):
    tag = await _committed_tag(db_session, cleanup_expertise)
    await _admin_client(client, db_session, cleanup_users)
    url = f"{EXPERTISE}{tag.id}"

    response = await client.patch(url, json={"is_active": False})
    assert response.status_code == 200, response.text
    assert response.json()["is_active"] is False
    listed = (await client.get(EXPERTISE)).json()
    assert tag.id not in {item["id"] for item in listed["items"]}
    rows = await _audit(db_session, tag.id, "expertise.updated")
    assert rows[-1].metadata_ == {"fields": ["is_active"]}

    response = await client.patch(url, json={"is_active": True})
    assert response.json()["is_active"] is True
    listed = (await client.get(EXPERTISE)).json()
    assert tag.id in {item["id"] for item in listed["items"]}


async def test_patch_slug_taken_validation_and_404(
    client, db_session, cleanup_users, cleanup_expertise
):
    tag = await _committed_tag(db_session, cleanup_expertise)
    await _admin_client(client, db_session, cleanup_users)
    url = f"{EXPERTISE}{tag.id}"

    _assert_error(await client.patch(url, json={"slug": "hydrology"}), 409, "expertise.slug_taken")
    _assert_validation(await client.patch(url, json={"label": None}), "label")
    _assert_validation(await client.patch(url, json={"slug": None}), "slug")
    _assert_validation(await client.patch(url, json={"is_active": None}), "is_active")
    _assert_validation(await client.patch(url, json={"label": "x"}), "label")
    _assert_error(
        await client.patch(f"{EXPERTISE}999999999", json={"label": "Whatever"}),
        404,
        "expertise.not_found",
    )


# --- deactivated tags and members -------------------------------------------------------------


async def test_member_keeps_a_deactivated_tag_but_cannot_newly_pick_one(
    client, db_session, cleanup_users, cleanup_user_ids, cleanup_expertise
):
    kept = await _committed_tag(db_session, cleanup_expertise, slug="zz-kept", label="Kept")
    other = await _committed_tag(db_session, cleanup_expertise, slug="zz-other", label="Other")
    kept_id, other_id = kept.id, other.id
    member = await _committed(db_session, cleanup_users)
    cleanup_user_ids.add(member.id)
    await login_as(client, member)
    response = await client.patch(ME, json={"expertise_ids": [kept_id]})
    assert response.status_code == 200, response.text

    for tag_id in (kept_id, other_id):
        db_tag = await db_session.get(ExpertiseTag, tag_id)
        db_tag.is_active = False
    await db_session.commit()

    # The member still shows the deactivated tag ...
    me = (await client.get(ME)).json()
    assert [(t["id"], t["is_active"]) for t in me["expertise"]] == [(kept_id, False)]

    # ... and saving the profile unchanged keeps it rather than failing.
    response = await client.patch(ME, json={"expertise_ids": [kept_id]})
    assert response.status_code == 200, response.text
    assert [t["id"] for t in response.json()["expertise"]] == [kept_id]

    # A deactivated tag the member does not hold cannot be picked.
    response = await client.patch(ME, json={"expertise_ids": [kept_id, other_id]})
    _assert_validation(response, "expertise_ids")

    # Dropping it is allowed; it cannot then be picked again.
    response = await client.patch(ME, json={"expertise_ids": []})
    assert response.json()["expertise"] == []
    _assert_validation(await client.patch(ME, json={"expertise_ids": [kept_id]}), "expertise_ids")
