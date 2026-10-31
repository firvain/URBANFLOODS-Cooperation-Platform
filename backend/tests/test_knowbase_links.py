"""Increment 2e: KNOWBASE links on posts (validated through the proxy, titles cached) and the
public ``/knowbase/{kb_type}/{kb_id}/mentions/`` list. The KNOWBASE is mocked with respx.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy import select

from app.core.config import settings
from app.crud import knowbase_link as crud_links
from app.db.enums import ContentStatus, ContentType, KbType
from app.db.models import Category, KnowbaseLink, Post, User
from tests.factories import (
    create_category,
    create_knowbase_link,
    create_post,
    create_verified_user,
    login_as,
)

KB_BASE = "https://knowbase.test"
KB_API = f"{KB_BASE}/api/v1"
API = settings.API_V1_PREFIX
POSTS = f"{API}/posts/"
KNOWBASE = f"{API}/knowbase"

MEASURE_7 = {"id": 7, "title_en": "Retention basin", "title_local": "Λεκάνη ανάσχεσης"}
DOCUMENT_3 = {
    "id": 3,
    "name_of_document_en": "Flood Risk Act",
    "name_of_document_local": None,
}


@pytest.fixture(autouse=True)
def kb_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_BASE_URL", KB_BASE)


@pytest.fixture(autouse=True)
def upstream(kb_settings) -> Iterator[respx.MockRouter]:
    """Every request to the (test) KNOWBASE goes through this router; anything unmocked fails."""
    with respx.mock(base_url=KB_API, assert_all_called=False, assert_all_mocked=True) as router:
        yield router


async def _committed(db, cleanup_users, **kwargs) -> User:
    user = await create_verified_user(db, trusted_at=datetime.now(UTC), **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _category(db, cleanup_categories) -> Category:
    category = await create_category(db)
    cleanup_categories.add(category.id)
    await db.commit()
    return category


def _body(category: Category, links: list[dict], **overrides) -> dict:
    return {
        "title": "Basins and the law",
        "body_html": "<p>Body</p>",
        "category_id": category.id,
        "locale": "en",
        "tags": [],
        "knowbase_links": links,
        **overrides,
    }


async def _stored_links(db, post_id: int) -> list[KnowbaseLink]:
    stmt = (
        select(KnowbaseLink)
        .where(
            KnowbaseLink.content_type == ContentType.POST,
            KnowbaseLink.content_id == post_id,
        )
        .order_by(KnowbaseLink.sort_order)
    )
    return list((await db.scalars(stmt)).all())


def _assert_error(response, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code


# --- links on create / update ----------------------------------------------------------------


async def test_links_resolved_and_titles_cached(
    client, db_session, upstream, cleanup_users, cleanup_categories, cleanup_knowbase_links
):
    upstream.get("/measures/7").respond(json=MEASURE_7)
    upstream.get("/documents/3").respond(json=DOCUMENT_3)
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    response = await client.post(
        POSTS,
        json=_body(
            category,
            [
                {"kb_type": "measure", "kb_id": 7},
                {"kb_type": "document", "kb_id": 3},
                {"kb_type": "measure", "kb_id": 7},  # duplicate folded
            ],
        ),
    )

    assert response.status_code == 201, response.text
    post_id = response.json()["id"]
    cleanup_knowbase_links.add(post_id)
    assert response.json()["knowbase_links"] == [
        {
            "kb_type": "measure",
            "kb_id": 7,
            "title_en": "Retention basin",
            "title_local": "Λεκάνη ανάσχεσης",
            "url": "/knowbase/measures/7",
        },
        {
            "kb_type": "document",
            "kb_id": 3,
            "title_en": "Flood Risk Act",
            "title_local": None,
            "url": "/knowbase/documents/3",
        },
    ]
    stored = await _stored_links(db_session, post_id)
    assert [(link.kb_type, link.kb_id, link.sort_order) for link in stored] == [
        (KbType.MEASURE, 7, 0),
        (KbType.DOCUMENT, 3, 1),
    ]
    assert stored[0].cached_title_en == "Retention basin"

    # The detail serves the cached titles without asking the KNOWBASE again.
    upstream.reset()
    detail = await client.get(f"{POSTS}{response.json()['slug']}")
    assert detail.json()["knowbase_links"] == response.json()["knowbase_links"]


async def test_unknown_item_is_422(client, db_session, upstream, cleanup_users, cleanup_categories):
    upstream.get("/measures/7").respond(json=MEASURE_7)
    upstream.get("/measures/999").respond(404, json={"detail": "Not found"})
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    response = await client.post(
        POSTS,
        json=_body(
            category, [{"kb_type": "measure", "kb_id": 7}, {"kb_type": "measure", "kb_id": 999}]
        ),
    )

    assert response.status_code == 422, response.text
    assert response.json()["detail"]["fields"] == {"knowbase_links": "not_found"}
    # Nothing was created.
    count = await db_session.scalar(select(Post.id).where(Post.category_id == category.id))
    assert count is None


async def test_upstream_down_is_503(
    client, db_session, upstream, cleanup_users, cleanup_categories
):
    upstream.get("/measures/7").mock(side_effect=httpx.ConnectError("down"))
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    response = await client.post(POSTS, json=_body(category, [{"kb_type": "measure", "kb_id": 7}]))

    _assert_error(response, 503, "knowbase.unavailable")


async def test_more_than_ten_links_or_bad_type_rejected(
    client, db_session, cleanup_users, cleanup_categories
):
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)

    eleven = [{"kb_type": "measure", "kb_id": i} for i in range(1, 12)]
    response = await client.post(POSTS, json=_body(category, eleven))
    assert response.status_code == 422, response.text
    assert any(f.startswith("knowbase_links") for f in response.json()["detail"]["fields"])

    bad = await client.post(POSTS, json=_body(category, [{"kb_type": "video", "kb_id": 1}]))
    assert bad.status_code == 422
    zero = await client.post(POSTS, json=_body(category, [{"kb_type": "measure", "kb_id": 0}]))
    assert zero.status_code == 422


async def test_update_replaces_links(
    client, db_session, upstream, cleanup_users, cleanup_categories, cleanup_knowbase_links
):
    upstream.get("/measures/7").respond(json=MEASURE_7)
    upstream.get("/documents/3").respond(json=DOCUMENT_3)
    user = await _committed(db_session, cleanup_users)
    category = await _category(db_session, cleanup_categories)
    await login_as(client, user)
    created = (
        await client.post(POSTS, json=_body(category, [{"kb_type": "measure", "kb_id": 7}]))
    ).json()
    cleanup_knowbase_links.add(created["id"])

    response = await client.patch(
        f"{POSTS}{created['id']}", json={"knowbase_links": [{"kb_type": "document", "kb_id": 3}]}
    )

    assert response.status_code == 200, response.text
    assert [link["kb_id"] for link in response.json()["knowbase_links"]] == [3]
    stored = await _stored_links(db_session, created["id"])
    assert [(link.kb_type, link.kb_id) for link in stored] == [(KbType.DOCUMENT, 3)]

    cleared = await client.patch(f"{POSTS}{created['id']}", json={"knowbase_links": []})
    assert cleared.json()["knowbase_links"] == []
    assert await _stored_links(db_session, created["id"]) == []


async def test_list_links_in_sort_order(db_session):
    category = await create_category(db_session)
    post = await create_post(db_session, category_id=category.id)
    await create_knowbase_link(db_session, post_id=post.id, kb_type="document", kb_id=3, order=1)
    await create_knowbase_link(db_session, post_id=post.id, kb_type="measure", kb_id=7, order=0)

    links = await crud_links.list_links(
        db_session, content_type=ContentType.POST, content_id=post.id
    )

    assert [(link.kb_type, link.kb_id) for link in links] == [
        (KbType.MEASURE, 7),
        (KbType.DOCUMENT, 3),
    ]


# --- mentions ---------------------------------------------------------------------------------


async def test_mentions_list_visible_posts_linking_the_item(
    client, db_session, cleanup_users, cleanup_categories, cleanup_knowbase_links
):
    author = await _committed(db_session, cleanup_users)
    category = await create_category(db_session)
    cleanup_categories.add(category.id)
    # A KNOWBASE id no other test uses, so committed rows elsewhere cannot leak in.
    kb_id = 1_900_000_000 + category.id % 1_000_000
    published = await create_post(db_session, category_id=category.id, author_id=author.id)
    pending = await create_post(
        db_session, category_id=category.id, author_id=author.id, status=ContentStatus.PENDING
    )
    other_item = await create_post(db_session, category_id=category.id)
    for post in (published, pending):
        await create_knowbase_link(db_session, post_id=post.id, kb_type="measure", kb_id=kb_id)
    await create_knowbase_link(db_session, post_id=other_item.id, kb_type="document", kb_id=kb_id)
    cleanup_knowbase_links.update({published.id, pending.id, other_item.id})
    await db_session.commit()

    anon = await client.get(f"{KNOWBASE}/measure/{kb_id}/mentions/")
    assert anon.status_code == 200, anon.text
    assert anon.json()["total"] == 1
    assert [i["id"] for i in anon.json()["items"]] == [published.id]
    assert "body_html" not in anon.json()["items"][0]

    await login_as(client, author)
    mine = await client.get(f"{KNOWBASE}/measure/{kb_id}/mentions/")
    assert {i["id"] for i in mine.json()["items"]} == {published.id, pending.id}

    documents = await client.get(f"{KNOWBASE}/document/{kb_id}/mentions/")
    assert [i["id"] for i in documents.json()["items"]] == [other_item.id]
    assert (await client.get(f"{KNOWBASE}/video/{kb_id}/mentions/")).status_code == 422


async def test_mentions_empty_and_paginated(client):
    response = await client.get(f"{KNOWBASE}/measure/2147483000/mentions/", params={"limit": 5})
    assert response.status_code == 200
    assert response.json() == {"total": 0, "items": []}
    too_big = await client.get(f"{KNOWBASE}/measure/7/mentions/", params={"limit": 51})
    assert too_big.status_code == 422


async def test_count_mentions_follows_visibility(db_session):
    from app.crud import post as crud_post

    category = await create_category(db_session)
    author = await create_verified_user(db_session)
    kb_id = 1_800_000_000 + category.id % 1_000_000
    published = await create_post(db_session, category_id=category.id, author_id=author.id)
    pending = await create_post(
        db_session, category_id=category.id, author_id=author.id, status=ContentStatus.PENDING
    )
    for post in (published, pending):
        await create_knowbase_link(db_session, post_id=post.id, kb_type="document", kb_id=kb_id)

    anon = await crud_post.count_mentions(
        db_session, kb_type=KbType.DOCUMENT, kb_id=kb_id, user=None
    )
    as_author = await crud_post.count_mentions(
        db_session, kb_type=KbType.DOCUMENT, kb_id=kb_id, user=author
    )

    assert (anon, as_author) == (1, 2)
