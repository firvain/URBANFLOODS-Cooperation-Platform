"""Increment 1m: the members directory (``GET /members/``, ``/members/{id}``) and suggested
collaborators (``GET /members/suggested``). Since 2026-10-31 all three need a verified account;
the list and detail tests run signed in as a verified ``signed_in`` viewer.

Each test tags its users' display names with a unique token and filters on it (``q``) where it
counts rows, so committed users of other tests can never leak in. Rows the app commits are
removed by ``cleanup_users`` / ``cleanup_organisations``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import insert, select

from app.core.config import settings
from app.db.models import ExpertiseTag, User, user_expertise
from tests.factories import create_organisation, create_user, create_verified_user, login_as

API = settings.API_V1_PREFIX
MEMBERS = f"{API}/members/"
SUGGESTED = f"{API}/members/suggested"
MEMBER_KEYS = {
    "id",
    "display_name",
    "organisation",
    "organisation_other",
    "country",
    "bio_excerpt",
    "expertise",
    "email",
    "created_at",
}


# --- helpers ----------------------------------------------------------------------------------


@pytest.fixture
async def signed_in(client, db_session, cleanup_users) -> User:
    """A committed verified viewer, logged in on ``client``. Its name never contains a test
    token and it has no organisation, so it never matches the tests' filters."""
    viewer = await create_verified_user(db_session, display_name="Directory Viewer")
    cleanup_users.add(viewer.email)
    await db_session.commit()
    await login_as(client, viewer)
    return viewer


def _token() -> str:
    return f"tok{uuid.uuid4().hex[:10]}"


async def _tag_ids(db, *slugs: str) -> list[int]:
    rows = await db.execute(select(ExpertiseTag.slug, ExpertiseTag.id))
    by_slug = dict(rows.all())
    return [by_slug[slug] for slug in slugs]


async def _member(
    db, cleanup_users, *, tags: tuple[str, ...] = (), factory=create_verified_user, **kwargs
) -> User:
    """A committed (verified, by default) user with the given expertise slugs."""
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    tag_ids = await _tag_ids(db, *tags)
    if tag_ids:
        await db.execute(
            insert(user_expertise), [{"user_id": user.id, "tag_id": tag} for tag in tag_ids]
        )
    await db.commit()
    return user


async def _list(client, **params):
    response = await client.get(MEMBERS, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body) -> list[int]:
    return [item["id"] for item in body["items"]]


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


# --- access -----------------------------------------------------------------------------------


async def test_list_requires_login(client):
    _assert_error(await client.get(MEMBERS), 401, "auth.not_authenticated")


async def test_detail_requires_login(client, db_session, cleanup_users):
    user = await _member(db_session, cleanup_users)

    _assert_error(await client.get(f"{MEMBERS}{user.id}"), 401, "auth.not_authenticated")


async def test_list_and_detail_require_verification(client, db_session, cleanup_users):
    member = await _member(db_session, cleanup_users)
    unverified = await _member(db_session, cleanup_users, factory=create_user)
    await login_as(client, unverified)

    _assert_error(await client.get(MEMBERS), 403, "auth.email_not_verified")
    _assert_error(await client.get(f"{MEMBERS}{member.id}"), 403, "auth.email_not_verified")


# --- list -------------------------------------------------------------------------------------


@pytest.mark.usefixtures("signed_in")
async def test_verified_member_can_list(client, db_session, cleanup_users):
    token = _token()
    user = await _member(
        db_session,
        cleanup_users,
        display_name=f"Ana {token}",
        country="GR",
        bio="Flood modeller.",
        tags=("meteorology", "hydrology"),
    )

    body = await _list(client, q=token)

    assert set(body) == {"total", "items"}
    assert body["total"] == 1
    (item,) = body["items"]
    assert set(item) == MEMBER_KEYS
    assert item["id"] == user.id
    assert item["display_name"] == f"Ana {token}"
    assert item["country"] == "GR"
    assert item["organisation"] is None
    assert item["bio_excerpt"] == "Flood modeller."
    assert [tag["slug"] for tag in item["expertise"]] == ["hydrology", "meteorology"]
    assert item["email"] is None


@pytest.mark.usefixtures("signed_in")
async def test_only_verified_active_visible_listed(client, db_session, cleanup_users):
    token = _token()
    visible = await _member(db_session, cleanup_users, display_name=f"Visible {token}")
    await _member(
        db_session, cleanup_users, factory=create_user, display_name=f"Unverified {token}"
    )
    await _member(db_session, cleanup_users, display_name=f"Banned {token}", is_active=False)
    await _member(
        db_session,
        cleanup_users,
        display_name=f"Deleted {token}",
        deleted_at=datetime.now(UTC),
    )
    await _member(
        db_session, cleanup_users, display_name=f"Hidden {token}", show_in_directory=False
    )

    body = await _list(client, q=token)

    assert body["total"] == 1
    assert _ids(body) == [visible.id]


@pytest.mark.usefixtures("signed_in")
async def test_email_only_when_show_email(client, db_session, cleanup_users):
    token = _token()
    shown = await _member(db_session, cleanup_users, display_name=f"Shown {token}", show_email=True)
    hidden = await _member(db_session, cleanup_users, display_name=f"Private {token}")

    items = {item["id"]: item for item in (await _list(client, q=token))["items"]}

    assert items[shown.id]["email"] == shown.email
    assert items[hidden.id]["email"] is None


@pytest.mark.usefixtures("signed_in")
async def test_never_exposes_private_fields(client, db_session, cleanup_users):
    token = _token()
    await _member(
        db_session,
        cleanup_users,
        display_name=f"Trusted {token}",
        trusted_at=datetime.now(UTC),
        last_login_at=datetime.now(UTC),
    )

    (item,) = (await _list(client, q=token))["items"]

    assert not {"role", "is_trusted", "trusted_at", "last_login_at", "locale"} & set(item)


@pytest.mark.usefixtures("signed_in")
async def test_order_newest_first(client, db_session, cleanup_users):
    token = _token()
    now = datetime.now(UTC)
    older = await _member(
        db_session, cleanup_users, display_name=f"Old {token}", created_at=now - timedelta(days=2)
    )
    newer = await _member(
        db_session, cleanup_users, display_name=f"New {token}", created_at=now - timedelta(days=1)
    )

    assert _ids(await _list(client, q=token)) == [newer.id, older.id]


@pytest.mark.usefixtures("signed_in")
async def test_filter_q_matches_name_and_organisation(
    client, db_session, cleanup_users, cleanup_organisations
):
    token = _token()
    org = await create_organisation(db_session, name=f"Delta Water Board {token}")
    cleanup_organisations.add(org.name)
    by_name = await _member(db_session, cleanup_users, display_name=f"Name {token}")
    by_org = await _member(
        db_session, cleanup_users, display_name="Org Person", organisation_id=org.id
    )
    by_other = await _member(
        db_session,
        cleanup_users,
        display_name="Other Person",
        organisation_other=f"Town hall {token}",
    )
    await _member(db_session, cleanup_users, display_name="Unrelated Person")

    body = await _list(client, q=token.upper())

    assert body["total"] == 3
    assert set(_ids(body)) == {by_name.id, by_org.id, by_other.id}
    org_item = next(item for item in body["items"] if item["id"] == by_org.id)
    assert org_item["organisation"]["name"] == org.name
    assert set(org_item["organisation"]) == {"id", "short_name", "name", "country", "type"}


@pytest.mark.usefixtures("signed_in")
async def test_filter_q_escapes_wildcards(client, db_session, cleanup_users):
    token = _token()
    await _member(db_session, cleanup_users, display_name=f"Plain {token}")

    assert (await _list(client, q=f"{token}%"))["total"] == 0


@pytest.mark.usefixtures("signed_in")
async def test_filter_q_length(client):
    assert (await client.get(MEMBERS, params={"q": "a"})).status_code == 422
    assert (await client.get(MEMBERS, params={"q": "a" * 101})).status_code == 422


@pytest.mark.usefixtures("signed_in")
async def test_filter_expertise_any_match(client, db_session, cleanup_users):
    token = _token()
    hydro = await _member(db_session, cleanup_users, display_name=f"H {token}", tags=("hydrology",))
    both = await _member(
        db_session,
        cleanup_users,
        display_name=f"B {token}",
        tags=("hydrology", "urban-planning"),
    )
    planner = await _member(
        db_session, cleanup_users, display_name=f"P {token}", tags=("urban-planning",)
    )
    await _member(db_session, cleanup_users, display_name=f"G {token}", tags=("meteorology",))
    await _member(db_session, cleanup_users, display_name=f"N {token}")
    hydrology, urban = await _tag_ids(db_session, "hydrology", "urban-planning")

    one = await _list(client, q=token, expertise_ids=[hydrology])
    assert set(_ids(one)) == {hydro.id, both.id}
    assert one["total"] == 2

    any_of = await _list(client, q=token, expertise_ids=[hydrology, urban])
    assert set(_ids(any_of)) == {hydro.id, both.id, planner.id}
    assert any_of["total"] == 3  # ``both`` counted once
    # The full expertise list is returned, not just the matching tags.
    both_item = next(item for item in any_of["items"] if item["id"] == both.id)
    assert [tag["slug"] for tag in both_item["expertise"]] == ["hydrology", "urban-planning"]


@pytest.mark.usefixtures("signed_in")
async def test_filter_country_and_organisation(
    client, db_session, cleanup_users, cleanup_organisations
):
    token = _token()
    org = await create_organisation(db_session)
    cleanup_organisations.add(org.name)
    greek = await _member(db_session, cleanup_users, display_name=f"G {token}", country="GR")
    italian = await _member(
        db_session,
        cleanup_users,
        display_name=f"I {token}",
        country="IT",
        organisation_id=org.id,
    )

    assert _ids(await _list(client, q=token, country="gr")) == [greek.id]
    assert _ids(await _list(client, q=token, country="IT")) == [italian.id]
    assert _ids(await _list(client, organisation_id=org.id)) == [italian.id]
    assert (await client.get(MEMBERS, params={"country": "GRC"})).status_code == 422


@pytest.mark.usefixtures("signed_in")
async def test_pagination(client, db_session, cleanup_users):
    token = _token()
    now = datetime.now(UTC)
    users = [
        await _member(
            db_session,
            cleanup_users,
            display_name=f"P{index} {token}",
            created_at=now - timedelta(minutes=index),
        )
        for index in range(5)
    ]

    page = await _list(client, q=token, skip=1, limit=2)

    assert page["total"] == 5
    assert _ids(page) == [users[1].id, users[2].id]
    assert (await client.get(MEMBERS, params={"limit": 101})).status_code == 422
    assert (await client.get(MEMBERS, params={"limit": 0})).status_code == 422


@pytest.mark.usefixtures("signed_in")
async def test_default_limit_is_24(client, db_session, cleanup_users):
    token = _token()
    for index in range(25):
        await _member(db_session, cleanup_users, display_name=f"D{index} {token}")

    body = await _list(client, q=token)

    assert body["total"] == 25
    assert len(body["items"]) == 24


@pytest.mark.usefixtures("signed_in")
async def test_bio_excerpt_truncated(client, db_session, cleanup_users):
    token = _token()
    bio = "Flood  risk\n" + "x" * 400
    await _member(db_session, cleanup_users, display_name=f"Long {token}", bio=bio)

    (item,) = (await _list(client, q=token))["items"]

    excerpt = item["bio_excerpt"]
    assert len(excerpt) <= 200
    assert excerpt.startswith("Flood risk x")
    assert excerpt.endswith("…")
    assert "bio" not in item


# --- detail -----------------------------------------------------------------------------------


@pytest.mark.usefixtures("signed_in")
async def test_detail(client, db_session, cleanup_users):
    bio = "Line one.\n" + "y" * 300
    user = await _member(db_session, cleanup_users, bio=bio, show_email=True, tags=("hydrology",))

    response = await client.get(f"{MEMBERS}{user.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == MEMBER_KEYS | {"bio"}
    assert body["bio"] == bio
    assert len(body["bio_excerpt"]) <= 200
    assert body["email"] == user.email
    assert [tag["slug"] for tag in body["expertise"]] == ["hydrology"]


@pytest.mark.usefixtures("signed_in")
async def test_detail_not_found_for_hidden_users(client, db_session, cleanup_users):
    hidden = [
        await _member(db_session, cleanup_users, factory=create_user),
        await _member(db_session, cleanup_users, is_active=False),
        await _member(db_session, cleanup_users, deleted_at=datetime.now(UTC)),
        await _member(db_session, cleanup_users, show_in_directory=False),
    ]

    for user in hidden:
        _assert_error(await client.get(f"{MEMBERS}{user.id}"), 404, "members.not_found")
    _assert_error(await client.get(f"{MEMBERS}987654321"), 404, "members.not_found")


# --- suggested --------------------------------------------------------------------------------


async def test_suggested_requires_login(client):
    _assert_error(await client.get(SUGGESTED), 401, "auth.not_authenticated")


async def test_suggested_requires_verification(client, db_session, cleanup_users):
    user = await _member(db_session, cleanup_users, factory=create_user)
    await login_as(client, user)

    _assert_error(await client.get(SUGGESTED), 403, "auth.email_not_verified")


async def test_suggested_ranks_by_shared_expertise(client, db_session, cleanup_users):
    now = datetime.now(UTC) + timedelta(days=1)  # newer than anything else in the database
    me = await _member(
        db_session, cleanup_users, tags=("hydrology", "urban-planning", "meteorology")
    )
    one_old = await _member(
        db_session, cleanup_users, tags=("hydrology",), created_at=now - timedelta(hours=3)
    )
    three = await _member(
        db_session,
        cleanup_users,
        tags=("hydrology", "urban-planning", "meteorology", "coastal-management"),
        created_at=now - timedelta(hours=5),
    )
    two = await _member(
        db_session,
        cleanup_users,
        tags=("urban-planning", "meteorology"),
        created_at=now - timedelta(hours=4),
    )
    one_new = await _member(
        db_session, cleanup_users, tags=("meteorology",), created_at=now - timedelta(hours=2)
    )
    # Hidden from the directory: never suggested even with shared tags.
    await _member(
        db_session, cleanup_users, tags=("hydrology", "urban-planning"), show_in_directory=False
    )
    await login_as(client, me)

    response = await client.get(SUGGESTED)

    assert response.status_code == 200, response.text
    body = response.json()
    items = body["items"]
    assert me.id not in _ids(body)
    assert _ids(body)[:4] == [three.id, two.id, one_new.id, one_old.id]
    assert [item["shared_expertise"] for item in items[:4]] == [3, 2, 1, 1]
    assert set(items[0]) == MEMBER_KEYS | {"shared_expertise"}
    assert body["total"] == len(items) <= 6


async def test_suggested_fills_with_newest_and_limits_to_six(client, db_session, cleanup_users):
    now = datetime.now(UTC) + timedelta(days=1)  # newer than anything else in the database
    me = await _member(db_session, cleanup_users, tags=("coastal-management",))
    match = await _member(
        db_session,
        cleanup_users,
        tags=("coastal-management",),
        created_at=now - timedelta(days=10),
    )
    others = [
        await _member(
            db_session,
            cleanup_users,
            tags=("ecology-biodiversity",),
            created_at=now - timedelta(hours=index),
        )
        for index in range(7)
    ]
    await login_as(client, me)

    body = (await client.get(SUGGESTED)).json()

    assert body["total"] == 6
    assert _ids(body) == [match.id] + [user.id for user in others[:5]]
    assert [item["shared_expertise"] for item in body["items"]] == [1, 0, 0, 0, 0, 0]


async def test_suggested_without_own_expertise_lists_newest(client, db_session, cleanup_users):
    now = datetime.now(UTC) + timedelta(days=1)
    me = await _member(db_session, cleanup_users, created_at=now)
    newest = [
        await _member(
            db_session,
            cleanup_users,
            tags=("hydrology",),
            created_at=now - timedelta(hours=index + 1),
        )
        for index in range(3)
    ]
    await login_as(client, me)

    body = (await client.get(SUGGESTED)).json()

    assert _ids(body)[:3] == [user.id for user in newest]
    assert me.id not in _ids(body)
    assert all(item["shared_expertise"] == 0 for item in body["items"])
