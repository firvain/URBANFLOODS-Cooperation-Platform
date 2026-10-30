"""Increment 1m: the expertise vocabulary (seeded tags, ``GET /expertise/``), expertise and the
directory visibility flags on the user's own profile (``PATCH /auth/me``), the GDPR export and
anonymisation.

Users the app commits are removed by ``cleanup_users`` / ``cleanup_user_ids``; their
``user_expertise`` rows go with them (``ON DELETE CASCADE``).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import delete, select

from app.core.config import settings
from app.db.models import AuditLog, ExpertiseTag, User, user_expertise
from tests.factories import DEFAULT_PASSWORD, create_verified_user, login_as

API = settings.API_V1_PREFIX
EXPERTISE = f"{API}/expertise/"
ME = f"{API}/auth/me"
EXPORT = f"{API}/auth/me/export"

SEEDED_SLUGS = [
    "hydrology",
    "hydraulic-modelling",
    "flood-risk-mapping",
    "early-warning-systems",
    "civil-protection",
    "urban-planning",
    "nature-based-solutions",
    "green-blue-infrastructure",
    "water-supply-sewerage",
    "river-basin-management",
    "coastal-management",
    "climate-adaptation",
    "policy-governance",
    "gis-remote-sensing",
    "data-science-dss",
    "environmental-engineering",
    "community-engagement",
    "education-training",
    "agriculture-irrigation",
    "economics-insurance",
    "meteorology",
    "ecology-biodiversity",
]


# --- helpers ----------------------------------------------------------------------------------


async def _committed(db, cleanup_users, cleanup_user_ids, **kwargs) -> User:
    user = await create_verified_user(db, **kwargs)
    cleanup_users.add(user.email)
    cleanup_user_ids.add(user.id)
    await db.commit()
    return user


async def _tags(db) -> list[ExpertiseTag]:
    stmt = select(ExpertiseTag).where(ExpertiseTag.slug.in_(SEEDED_SLUGS))
    return list((await db.scalars(stmt.order_by(ExpertiseTag.sort_order))).all())


async def _tag_ids(db, *slugs: str) -> list[int]:
    by_slug = {tag.slug: tag.id for tag in await _tags(db)}
    return [by_slug[slug] for slug in slugs]


async def _stored_tag_ids(db, user_id: int) -> set[int]:
    stmt = select(user_expertise.c.tag_id).where(user_expertise.c.user_id == user_id)
    return set((await db.scalars(stmt)).all())


async def _reload_user(db, user_id: int) -> User:
    stmt = select(User).where(User.id == user_id).execution_options(populate_existing=True)
    return (await db.execute(stmt)).scalar_one()


async def _profile_audits(db, user_id: int) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "user",
            AuditLog.target_id == user_id,
            AuditLog.action == "auth.profile_updated",
        )
        .order_by(AuditLog.id)
        .execution_options(populate_existing=True)
    )
    return list((await db.scalars(stmt)).all())


def _assert_validation(response, field: str, code: str | None = None) -> None:
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "validation.failed"
    assert field in detail["fields"], detail
    if code is not None:
        assert detail["fields"][field] == code, detail


@pytest.fixture
async def cleanup_tags(database_url: str) -> AsyncIterator[set[str]]:
    """Slugs of expertise tags the test commits; deleted afterwards."""
    from app.db.session import AsyncSessionLocal

    slugs: set[str] = set()
    yield slugs
    if not slugs:
        return
    async with AsyncSessionLocal() as session, session.begin():
        await session.execute(delete(ExpertiseTag).where(ExpertiseTag.slug.in_(slugs)))


# --- seed and public list ---------------------------------------------------------------------


async def test_seeded_tags_in_order_and_active(db_session):
    tags = await _tags(db_session)

    assert [tag.slug for tag in tags] == SEEDED_SLUGS
    assert [tag.sort_order for tag in tags] == list(range(1, len(SEEDED_SLUGS) + 1))
    assert all(tag.is_active for tag in tags)
    labels = {tag.slug: tag.label for tag in tags}
    assert labels["hydrology"] == "Hydrology"
    assert labels["civil-protection"] == "Civil protection and emergency management"
    assert labels["ecology-biodiversity"] == "Ecology and biodiversity"


async def test_list_expertise_public(client, db_session):
    response = await client.get(EXPERTISE)

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"total", "items"}
    assert body["total"] == len(body["items"]) == len(SEEDED_SLUGS)
    assert [item["slug"] for item in body["items"]] == SEEDED_SLUGS
    first = body["items"][0]
    assert set(first) == {"id", "slug", "label", "sort_order"}
    assert first["label"] == "Hydrology"
    assert first["sort_order"] == 1


async def test_list_expertise_hides_inactive(client, db_session, cleanup_tags):
    db_session.add(ExpertiseTag(slug="zz-retired", label="Retired", sort_order=0, is_active=False))
    cleanup_tags.add("zz-retired")
    await db_session.commit()

    body = (await client.get(EXPERTISE)).json()

    assert "zz-retired" not in {item["slug"] for item in body["items"]}
    assert body["total"] == len(SEEDED_SLUGS)


# --- PATCH /auth/me ---------------------------------------------------------------------------


async def test_me_defaults(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)

    body = (await client.get(ME)).json()

    assert body["expertise"] == []
    assert body["show_email"] is False
    assert body["show_in_directory"] is True


async def test_patch_me_sets_expertise_in_sort_order(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    ids = await _tag_ids(db_session, "meteorology", "hydrology", "urban-planning")

    response = await client.patch(ME, json={"expertise_ids": ids})

    assert response.status_code == 200, response.text
    expertise = response.json()["expertise"]
    assert [tag["slug"] for tag in expertise] == ["hydrology", "urban-planning", "meteorology"]
    assert set(expertise[0]) == {"id", "slug", "label", "sort_order"}
    assert await _stored_tag_ids(db_session, user.id) == set(ids)
    (entry,) = await _profile_audits(db_session, user.id)
    assert entry.metadata_ == {"fields": ["expertise"]}

    # GET /me (session lookup) loads it too.
    me = (await client.get(ME)).json()
    assert [tag["slug"] for tag in me["expertise"]] == [tag["slug"] for tag in expertise]


async def test_patch_me_same_expertise_is_not_a_change(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    ids = await _tag_ids(db_session, "hydrology", "meteorology")
    await client.patch(ME, json={"expertise_ids": ids})

    response = await client.patch(ME, json={"expertise_ids": list(reversed(ids)) + ids[:1]})

    assert response.status_code == 200, response.text
    assert len(await _profile_audits(db_session, user.id)) == 1


async def test_patch_me_replaces_expertise_and_audits_with_other_fields(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    await client.patch(ME, json={"expertise_ids": await _tag_ids(db_session, "hydrology")})
    new_ids = await _tag_ids(db_session, "coastal-management", "gis-remote-sensing")

    response = await client.patch(
        ME, json={"expertise_ids": new_ids, "bio": "Coasts.", "show_email": True}
    )

    assert response.status_code == 200, response.text
    assert [tag["slug"] for tag in response.json()["expertise"]] == [
        "coastal-management",
        "gis-remote-sensing",
    ]
    assert await _stored_tag_ids(db_session, user.id) == set(new_ids)
    entries = await _profile_audits(db_session, user.id)
    assert entries[-1].metadata_ == {"fields": ["bio", "expertise", "show_email"]}


async def test_patch_me_too_many_expertise(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    ids = await _tag_ids(db_session, *SEEDED_SLUGS[:9])

    response = await client.patch(ME, json={"expertise_ids": ids})

    _assert_validation(response, "expertise_ids")
    assert await _stored_tag_ids(db_session, user.id) == set()


async def test_patch_me_eight_expertise_allowed(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    ids = await _tag_ids(db_session, *SEEDED_SLUGS[:8])

    response = await client.patch(ME, json={"expertise_ids": ids})

    assert response.status_code == 200, response.text
    assert len(response.json()["expertise"]) == 8


async def test_patch_me_unknown_expertise(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    ids = await _tag_ids(db_session, "hydrology")

    response = await client.patch(ME, json={"expertise_ids": [*ids, 987654]})

    _assert_validation(response, "expertise_ids", "not_found")
    assert await _stored_tag_ids(db_session, user.id) == set()


async def test_patch_me_inactive_expertise(
    client, db_session, cleanup_users, cleanup_user_ids, cleanup_tags
):
    retired = ExpertiseTag(slug="zz-inactive", label="Inactive", sort_order=99, is_active=False)
    db_session.add(retired)
    cleanup_tags.add("zz-inactive")
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)

    response = await client.patch(ME, json={"expertise_ids": [retired.id]})

    _assert_validation(response, "expertise_ids", "not_found")


async def test_patch_me_null_expertise_rejected(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)

    response = await client.patch(ME, json={"expertise_ids": None})

    _assert_validation(response, "expertise_ids")


async def test_patch_me_empty_list_clears(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    await client.patch(ME, json={"expertise_ids": await _tag_ids(db_session, "hydrology")})

    response = await client.patch(ME, json={"expertise_ids": []})

    assert response.status_code == 200, response.text
    assert response.json()["expertise"] == []
    assert await _stored_tag_ids(db_session, user.id) == set()
    entries = await _profile_audits(db_session, user.id)
    assert [entry.metadata_ for entry in entries] == [{"fields": ["expertise"]}] * 2


async def test_patch_me_omitted_expertise_is_kept(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    ids = await _tag_ids(db_session, "hydrology")
    await client.patch(ME, json={"expertise_ids": ids})

    response = await client.patch(ME, json={"bio": "Still a hydrologist."})

    assert response.status_code == 200, response.text
    assert [tag["slug"] for tag in response.json()["expertise"]] == ["hydrology"]
    assert await _stored_tag_ids(db_session, user.id) == set(ids)


async def test_patch_me_visibility_flags(client, db_session, cleanup_users, cleanup_user_ids):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)

    response = await client.patch(ME, json={"show_email": True, "show_in_directory": False})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["show_email"] is True
    assert body["show_in_directory"] is False
    stored = await _reload_user(db_session, user.id)
    assert stored.show_email is True
    assert stored.show_in_directory is False
    (entry,) = await _profile_audits(db_session, user.id)
    assert entry.metadata_ == {"fields": ["show_email", "show_in_directory"]}

    me = (await client.get(ME)).json()
    assert me["show_email"] is True
    assert me["show_in_directory"] is False


@pytest.mark.parametrize("field", ["show_email", "show_in_directory"])
async def test_patch_me_visibility_flag_not_nullable(
    client, db_session, cleanup_users, cleanup_user_ids, field
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)

    response = await client.patch(ME, json={field: None})

    _assert_validation(response, field)


async def test_patch_me_expertise_requires_auth(client):
    response = await client.patch(ME, json={"expertise_ids": []})

    assert response.status_code == 401


# --- GDPR -------------------------------------------------------------------------------------


async def test_export_includes_expertise_and_flags(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    ids = await _tag_ids(db_session, "policy-governance", "hydrology")
    await client.patch(ME, json={"expertise_ids": ids, "show_email": True})

    response = await client.get(EXPORT)

    assert response.status_code == 200, response.text
    exported = response.json()["user"]
    assert [tag["slug"] for tag in exported["expertise"]] == ["hydrology", "policy-governance"]
    assert exported["show_email"] is True
    assert exported["show_in_directory"] is True


async def test_delete_account_clears_expertise_and_flags(
    client, db_session, cleanup_users, cleanup_user_ids
):
    user = await _committed(db_session, cleanup_users, cleanup_user_ids)
    await login_as(client, user)
    await client.patch(
        ME,
        json={
            "expertise_ids": await _tag_ids(db_session, "hydrology", "meteorology"),
            "show_email": True,
        },
    )

    response = await client.request("DELETE", ME, json={"current_password": DEFAULT_PASSWORD})

    assert response.status_code == 204, response.text
    stored = await _reload_user(db_session, user.id)
    assert stored.show_email is False
    assert stored.show_in_directory is False
    assert await _stored_tag_ids(db_session, user.id) == set()
