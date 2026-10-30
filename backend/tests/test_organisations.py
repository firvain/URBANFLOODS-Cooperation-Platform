"""Increment 1h: public organisations list/detail (feeds ``/partners``) and admin create/update.

Rows the app commits are removed by ``cleanup_users`` / ``cleanup_organisations``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.crud import organisation as crud_organisation
from app.db.enums import OrganisationType
from app.db.models import AuditLog, Organisation, User
from tests.factories import (
    create_admin,
    create_organisation,
    create_user,
    create_verified_user,
    login_as,
    unique_email,
)

API = settings.API_V1_PREFIX
ORGS = f"{API}/organisations/"
SEEDED_PARTNERS = 22


# --- helpers ----------------------------------------------------------------------------------


async def _committed(db, cleanup_users, factory=create_verified_user, **kwargs) -> User:
    user = await factory(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _uowm_id(db) -> int:
    return await db.scalar(select(Organisation.id).where(Organisation.short_name == "UOWM"))


async def _audit(db, organisation_id: int, action: str) -> list[AuditLog]:
    stmt = (
        select(AuditLog)
        .where(
            AuditLog.target_type == "organisation",
            AuditLog.target_id == organisation_id,
            AuditLog.action == action,
        )
        .order_by(AuditLog.id)
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


def _new_org_body(**overrides) -> dict:
    body = {
        "name": f"New Organisation {unique_email('o')[:20]}",
        "short_name": "NEWORG",
        "country": "it",
        "type": "other",
        "website": "https://example.org/",
    }
    body.update(overrides)
    return body


async def _admin_client(client, db, cleanup_users) -> User:
    admin = await _committed(db, cleanup_users, factory=create_admin)
    await login_as(client, admin)
    return admin


# --- public list ------------------------------------------------------------------------------


async def test_list_returns_seeded_partners_first(client):
    response = await client.get(ORGS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= SEEDED_PARTNERS
    items = body["items"]
    partners = items[:SEEDED_PARTNERS]
    assert all(item["is_partner"] for item in partners)
    assert [item["sort_order"] for item in partners] == list(range(1, SEEDED_PARTNERS + 1))
    # LP/PP before AP.
    types = [item["type"] for item in partners]
    assert types == ["PP"] * 11 + ["AP"] * 11
    first = partners[0]
    assert first["short_name"] == "UOWM"
    assert first["country"] == "GR"
    assert first["website"] == "https://www.uowm.gr/en/"
    assert first["member_count"] == 0
    assert set(first) == {
        "id",
        "name",
        "short_name",
        "country",
        "type",
        "website",
        "is_partner",
        "sort_order",
        "member_count",
    }
    assert all(item["member_count"] == 0 for item in partners)


async def test_non_partner_listed_after_partners(client, db_session, cleanup_organisations):
    org = await create_organisation(db_session, type=OrganisationType.PP, sort_order=0)
    cleanup_organisations.add(org.name)
    await db_session.commit()

    items = (await client.get(ORGS)).json()["items"]

    ids = [item["id"] for item in items]
    assert ids.index(org.id) >= SEEDED_PARTNERS
    assert not next(item for item in items if item["id"] == org.id)["is_partner"]


async def test_member_count_counts_only_verified_active_users(client, db_session, cleanup_users):
    uowm_id = await _uowm_id(db_session)
    await _committed(db_session, cleanup_users, organisation_id=uowm_id)
    await _committed(db_session, cleanup_users, organisation_id=uowm_id)
    # Not counted: unverified, banned, deleted.
    await _committed(db_session, cleanup_users, factory=create_user, organisation_id=uowm_id)
    await _committed(db_session, cleanup_users, organisation_id=uowm_id, is_active=False)
    deleted = await create_verified_user(db_session, organisation_id=uowm_id)
    cleanup_users.add(deleted.email)
    deleted.deleted_at = datetime.now(UTC)
    await db_session.commit()

    items = (await client.get(ORGS)).json()["items"]
    uowm = next(item for item in items if item["id"] == uowm_id)
    assert uowm["member_count"] == 2
    others = [item for item in items if item["id"] != uowm_id and item["is_partner"]]
    assert all(item["member_count"] == 0 for item in others)

    detail = (await client.get(f"{ORGS}{uowm_id}")).json()
    assert detail["member_count"] == 2


async def test_list_partners_only(client, db_session, cleanup_organisations):
    org = await create_organisation(db_session)
    cleanup_organisations.add(org.name)
    await db_session.commit()

    body = (await client.get(ORGS, params={"partners_only": "true"})).json()

    assert body["total"] == SEEDED_PARTNERS
    assert len(body["items"]) == SEEDED_PARTNERS
    assert all(item["is_partner"] for item in body["items"])

    everything = (await client.get(ORGS)).json()
    assert org.id in [item["id"] for item in everything["items"]]


async def test_list_search_matches_short_name_and_name(client):
    body = (await client.get(ORGS, params={"q": "UOWM"})).json()

    short_names = [item["short_name"] for item in body["items"]]
    assert short_names[0] == "UOWM"
    # TEMENUS has "UOWM" in its full name.
    assert "TEMENUS" in short_names
    assert body["total"] == len(short_names)

    body = (await client.get(ORGS, params={"q": "macerata"})).json()
    assert [item["short_name"] for item in body["items"]] == ["MC"]


async def test_list_search_escapes_like_wildcards(client):
    body = (await client.get(ORGS, params={"q": "%%"})).json()
    assert body == {"total": 0, "items": []}


async def test_list_pagination(client):
    body = (await client.get(ORGS, params={"partners_only": "true", "skip": 20, "limit": 5})).json()
    assert body["total"] == SEEDED_PARTNERS
    assert [item["sort_order"] for item in body["items"]] == [21, 22]


@pytest.mark.parametrize(
    ("params", "field"),
    [
        ({"q": "a"}, "query.q"),
        ({"q": "x" * 101}, "query.q"),
        ({"limit": 0}, "query.limit"),
        ({"limit": 201}, "query.limit"),
        ({"skip": -1}, "query.skip"),
    ],
)
async def test_list_query_validation(client, params, field):
    _assert_validation(await client.get(ORGS, params=params), field)


# --- public detail ----------------------------------------------------------------------------


async def test_get_organisation(client, db_session):
    uowm_id = await _uowm_id(db_session)

    response = await client.get(f"{ORGS}{uowm_id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == uowm_id
    assert body["short_name"] == "UOWM"
    assert body["name"] == "University of Western Macedonia"
    assert body["type"] == "PP"
    assert body["member_count"] == 0


async def test_get_organisation_not_found(client):
    _assert_error(await client.get(f"{ORGS}999999"), 404, "organisations.not_found")


# --- admin create -----------------------------------------------------------------------------


async def test_create_requires_login(client):
    response = await client.post(ORGS, json=_new_org_body())
    _assert_error(response, 401, "auth.not_authenticated")


async def test_create_forbidden_for_member(client, db_session, cleanup_users):
    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)

    _assert_error(await client.post(ORGS, json=_new_org_body()), 403, "auth.forbidden")


async def test_create_by_admin(client, db_session, cleanup_users, cleanup_organisations):
    admin = await _admin_client(client, db_session, cleanup_users)
    body = _new_org_body()
    cleanup_organisations.add(body["name"])

    response = await client.post(ORGS, json=body)

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == body["name"]
    assert created["short_name"] == "NEWORG"
    assert created["country"] == "IT"
    assert created["type"] == "other"
    assert created["website"] == "https://example.org/"
    assert created["is_partner"] is False
    assert created["sort_order"] == 0
    assert created["member_count"] == 0

    org = await db_session.get(Organisation, created["id"])
    assert org is not None and org.name == body["name"]
    rows = await _audit(db_session, created["id"], "organisation.created")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id

    fetched = await client.get(f"{ORGS}{created['id']}")
    assert fetched.json()["name"] == body["name"]


async def test_create_duplicate_name(client, db_session, cleanup_users):
    await _admin_client(client, db_session, cleanup_users)

    response = await client.post(ORGS, json=_new_org_body(name="University of Western Macedonia"))

    _assert_error(response, 409, "organisations.name_taken")


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"website": "javascript:alert(1)"}, "website"),
        ({"website": "ftp://example.org"}, "website"),
        ({"website": "https://"}, "website"),
        ({"name": "x"}, "name"),
        ({"name": "x" * 201}, "name"),
        ({"short_name": ""}, "short_name"),
        ({"short_name": "x" * 65}, "short_name"),
        ({"country": "GRC"}, "country"),
        ({"country": None}, "country"),
        ({"type": "XX"}, "type"),
    ],
)
async def test_create_validation(client, db_session, cleanup_users, overrides, field):
    await _admin_client(client, db_session, cleanup_users)
    _assert_validation(await client.post(ORGS, json=_new_org_body(**overrides)), field)


async def test_create_without_website(client, db_session, cleanup_users, cleanup_organisations):
    await _admin_client(client, db_session, cleanup_users)
    body = _new_org_body(website=None, is_partner=True, type="AP", sort_order=50)
    cleanup_organisations.add(body["name"])

    response = await client.post(ORGS, json=body)

    assert response.status_code == 201, response.text
    created = response.json()
    assert created["website"] is None
    assert created["is_partner"] is True
    assert created["type"] == "AP"
    assert created["sort_order"] == 50


# --- admin update -----------------------------------------------------------------------------


async def test_update_requires_admin(client, db_session, cleanup_users, cleanup_organisations):
    org = await create_organisation(db_session)
    cleanup_organisations.add(org.name)
    await db_session.commit()
    url = f"{ORGS}{org.id}"

    _assert_error(await client.patch(url, json={"short_name": "X"}), 401, "auth.not_authenticated")

    member = await _committed(db_session, cleanup_users)
    await login_as(client, member)
    _assert_error(await client.patch(url, json={"short_name": "X"}), 403, "auth.forbidden")


async def test_update_by_admin(client, db_session, cleanup_users, cleanup_organisations):
    org = await create_organisation(db_session, website="https://old.example.org")
    cleanup_organisations.add(org.name)
    await db_session.commit()
    admin = await _admin_client(client, db_session, cleanup_users)

    response = await client.patch(
        f"{ORGS}{org.id}",
        json={"short_name": "UPD", "website": None, "sort_order": 7, "name": org.name},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["short_name"] == "UPD"
    assert body["website"] is None
    assert body["sort_order"] == 7
    assert body["name"] == org.name
    rows = await _audit(db_session, org.id, "organisation.updated")
    assert len(rows) == 1
    assert rows[0].actor_id == admin.id
    # Only the names of fields that actually changed.
    assert rows[0].metadata_ == {"fields": ["short_name", "sort_order", "website"]}


async def test_update_without_changes_writes_no_audit(
    client, db_session, cleanup_users, cleanup_organisations
):
    org = await create_organisation(db_session, short_name="SAME")
    cleanup_organisations.add(org.name)
    await db_session.commit()
    await _admin_client(client, db_session, cleanup_users)

    response = await client.patch(f"{ORGS}{org.id}", json={"short_name": "SAME"})

    assert response.status_code == 200, response.text
    assert await _audit(db_session, org.id, "organisation.updated") == []


async def test_update_rename_to_taken_name(
    client, db_session, cleanup_users, cleanup_organisations
):
    org = await create_organisation(db_session)
    cleanup_organisations.add(org.name)
    await db_session.commit()
    await _admin_client(client, db_session, cleanup_users)

    response = await client.patch(
        f"{ORGS}{org.id}", json={"name": "University of Western Macedonia"}
    )

    _assert_error(response, 409, "organisations.name_taken")


async def test_update_not_found(client, db_session, cleanup_users):
    await _admin_client(client, db_session, cleanup_users)
    response = await client.patch(f"{ORGS}999999", json={"short_name": "X"})
    _assert_error(response, 404, "organisations.not_found")


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        ({"website": "javascript:alert(1)"}, "website"),
        ({"name": None}, "name"),
        ({"short_name": None}, "short_name"),
        ({"country": None}, "country"),
        ({"type": None}, "type"),
        ({"is_partner": None}, "is_partner"),
        ({"sort_order": None}, "sort_order"),
    ],
)
async def test_update_validation(
    client, db_session, cleanup_users, cleanup_organisations, payload, field
):
    org = await create_organisation(db_session)
    cleanup_organisations.add(org.name)
    await db_session.commit()
    await _admin_client(client, db_session, cleanup_users)

    _assert_validation(await client.patch(f"{ORGS}{org.id}", json=payload), field)


# --- crud -------------------------------------------------------------------------------------


async def test_crud_list_returns_rows_with_member_counts(db_session):
    total, rows = await crud_organisation.list_organisations(
        db_session, partners_only=True, q=None, skip=0, limit=100
    )
    assert total == SEEDED_PARTNERS
    organisation, member_count = rows[0]
    assert isinstance(organisation, Organisation)
    assert organisation.short_name == "UOWM"
    assert member_count == 0
