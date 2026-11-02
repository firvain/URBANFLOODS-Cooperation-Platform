"""Increment 5b: FAIR exports - ``/export/posts.json``, ``/export/threads.json``,
``/export/posts.csv`` and ``/export/datapackage.json`` (CC BY 4.0).

Exports are public and global, so rows committed by other tests may appear in them: every
assertion looks only at the rows this test created (by id or slug). Published content only:
pending, hidden and deleted posts, threads, comments and replies never appear, and no email
address ever does.
"""

from __future__ import annotations

import csv
import io
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import export as crud_export
from app.crud.user import anonymise_user
from app.db.enums import CategoryKind, ContentStatus, ContentType
from app.db.models import Category, KnowbaseLink, Organisation, Post, Tag, Thread, User
from tests.factories import (
    create_category,
    create_comment,
    create_knowbase_link,
    create_organisation,
    create_post,
    create_reply,
    create_tag,
    create_thread,
    create_thread_knowbase_link,
    create_verified_user,
)

API = settings.API_V1_PREFIX
EXPORT = f"{API}/export"
POSTS_JSON = f"{EXPORT}/posts.json"
THREADS_JSON = f"{EXPORT}/threads.json"
POSTS_CSV = f"{EXPORT}/posts.csv"
DATAPACKAGE = f"{EXPORT}/datapackage.json"
FRONTEND = "https://cooperation.example.org"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
CSV_HEADER = [
    "id",
    "slug",
    "title",
    "locale",
    "category",
    "tags",
    "author",
    "organisation",
    "published_at",
    "url",
]
POST_FIELDS = {
    "id",
    "slug",
    "title",
    "locale",
    "category",
    "tags",
    "author",
    "published_at",
    "updated_at",
    "excerpt",
    "body_text",
    "body_html",
    "url",
    "knowbase_links",
    "event_at",
    "event_url",
    "comments",
    "license",
    "license_url",
}
THREAD_FIELDS = (POST_FIELDS - {"excerpt", "event_at", "event_url", "comments"}) | {"replies"}
EVENT_AT = datetime(2027, 3, 15, 9, 30, tzinfo=UTC)


# --- corpus -----------------------------------------------------------------------------------


@dataclass
class Corpus:
    db: AsyncSession
    organisation: Organisation
    author: User
    commenter: User
    gone: User  # anonymised
    emails: list[str]
    post: Post  # published, rich
    anon_post: Post  # published, anonymised author
    orphan_post: Post  # published, no author row (author_id NULL)
    formula_post: Post  # published, title starts with "="
    hidden_posts: list[Post]  # pending, hidden, deleted
    thread: Thread
    anon_thread: Thread
    hidden_threads: list[Thread]
    published_comment_ids: list[int]
    unpublished_comment_ids: list[int]
    published_reply_ids: list[int]
    unpublished_reply_ids: list[int]
    child_reply_id: int
    parent_reply_id: int
    blog_slug: str
    tag_names: list[str] = field(default_factory=list)


async def build_corpus(
    db: AsyncSession,
    *,
    users: set[str],
    user_ids: set[int],
    organisations: set[str],
    categories: set[int],
    tags: set[int],
    kb_posts: set[int],
) -> Corpus:
    """Published and unpublished posts, threads, comments and replies, all committed."""
    token = uuid.uuid4().hex[:8]
    organisation = await create_organisation(db, short_name="UFX", country="IT")
    organisations.add(organisation.name)
    author = await create_verified_user(
        db, display_name="Ada Author", organisation_id=organisation.id
    )
    commenter = await create_verified_user(db, display_name="Cy Commenter")
    gone = await create_verified_user(db, display_name="Gone Soon")
    emails = [author.email, commenter.email, gone.email]
    users.update(emails)
    user_ids.add(gone.id)

    blog = await create_category(db, kind=CategoryKind.BLOG, name="Case studies")
    forum = await create_category(db, kind=CategoryKind.FORUM, name="Design questions")
    categories.update({blog.id, forum.id})
    tag_b = await create_tag(db, name=f"b-swales {token}")
    tag_a = await create_tag(db, name=f"a-ponds {token}")
    tags.update({tag_a.id, tag_b.id})

    post = await create_post(
        db,
        category_id=blog.id,
        author_id=author.id,
        title=f"Retention ponds {token}",
        excerpt="Short summary of the case.",
        tags=[tag_b, tag_a],
        event_at=EVENT_AT,
        event_url="https://example.org/event",
        locale="it",
    )
    await create_knowbase_link(db, post_id=post.id, kb_type="measure", kb_id=7, title_en="Basin")
    kb_posts.add(post.id)
    anon_post = await create_post(
        db, category_id=blog.id, author_id=gone.id, title=f"Anon post {token}"
    )
    orphan_post = await create_post(
        db, category_id=blog.id, author_id=None, title=f"Orphan post {token}"
    )
    formula_post = await create_post(
        db, category_id=blog.id, author_id=author.id, title=f"=HYPERLINK({token})"
    )
    hidden_posts = [
        await create_post(db, category_id=blog.id, author_id=author.id, status=status)
        for status in (ContentStatus.PENDING, ContentStatus.HIDDEN, ContentStatus.DELETED)
    ]

    published_comments = [
        await create_comment(db, post_id=post.id, author_id=commenter.id, body="First comment"),
        await create_comment(db, post_id=post.id, author_id=gone.id, body="Second comment"),
    ]
    unpublished_comments = [
        await create_comment(db, post_id=post.id, author_id=commenter.id, status=status)
        for status in (ContentStatus.PENDING, ContentStatus.HIDDEN, ContentStatus.DELETED)
    ]
    # A published comment on a hidden post never appears either.
    await create_comment(db, post_id=hidden_posts[1].id, author_id=commenter.id)

    thread = await create_thread(
        db,
        category_id=forum.id,
        author_id=author.id,
        title=f"Sizing ponds {token}",
        tags=[tag_a],
    )
    await create_thread_knowbase_link(db, thread_id=thread.id, kb_type="document", kb_id=3)
    anon_thread = await create_thread(
        db, category_id=forum.id, author_id=gone.id, title=f"Anon thread {token}"
    )
    hidden_threads = [
        await create_thread(db, category_id=forum.id, author_id=author.id, status=status)
        for status in (ContentStatus.PENDING, ContentStatus.HIDDEN, ContentStatus.DELETED)
    ]
    parent = await create_reply(db, thread_id=thread.id, author_id=commenter.id, body="Parent")
    child = await create_reply(
        db, thread_id=thread.id, author_id=gone.id, parent_reply_id=parent.id, body="Child"
    )
    unpublished_replies = [
        await create_reply(db, thread_id=thread.id, author_id=commenter.id, status=status)
        for status in (ContentStatus.PENDING, ContentStatus.HIDDEN, ContentStatus.DELETED)
    ]
    await create_reply(db, thread_id=hidden_threads[1].id, author_id=commenter.id)

    await db.flush()
    await anonymise_user(db, user=gone)
    await db.commit()
    for row in (post, anon_post, orphan_post, formula_post, thread, anon_thread):
        await db.refresh(row, attribute_names=["updated_at", "published_at"])

    return Corpus(
        db=db,
        organisation=organisation,
        author=author,
        commenter=commenter,
        gone=gone,
        emails=emails,
        post=post,
        anon_post=anon_post,
        orphan_post=orphan_post,
        formula_post=formula_post,
        hidden_posts=hidden_posts,
        thread=thread,
        anon_thread=anon_thread,
        hidden_threads=hidden_threads,
        published_comment_ids=[c.id for c in published_comments],
        unpublished_comment_ids=[c.id for c in unpublished_comments],
        published_reply_ids=[parent.id, child.id],
        unpublished_reply_ids=[r.id for r in unpublished_replies],
        child_reply_id=child.id,
        parent_reply_id=parent.id,
        blog_slug=blog.slug,
        tag_names=sorted([tag_a.name, tag_b.name]),
    )


@pytest.fixture(autouse=True)
def frontend_url(monkeypatch) -> None:
    monkeypatch.setattr(settings, "FRONTEND_URL", FRONTEND)


@pytest.fixture
async def corpus(
    db_session,
    cleanup_users,
    cleanup_user_ids,
    cleanup_organisations,
    cleanup_categories,
    cleanup_tags,
    cleanup_knowbase_links,
    cleanup_forum_categories,
) -> Corpus:
    return await build_corpus(
        db_session,
        users=cleanup_users,
        user_ids=cleanup_user_ids,
        organisations=cleanup_organisations,
        categories=cleanup_categories,
        tags=cleanup_tags,
        kb_posts=cleanup_knowbase_links,
    )


def _by_id(items: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    return {item["id"]: item for item in items}


def _csv_rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


def _ok(response: Any) -> str:
    assert response.status_code == 200, response.text
    return response.text


def _assert_no_email(text: str, corpus: Corpus) -> None:
    for email in corpus.emails:
        assert email not in text
    assert "@invalid" not in text
    assert f"deleted-{corpus.gone.id}" not in text


async def _published_ids(db: AsyncSession, model: Any) -> list[int]:
    stmt = select(model.id).where(model.status == ContentStatus.PUBLISHED).order_by(model.id)
    return list((await db.scalars(stmt)).all())


# --- posts.json -------------------------------------------------------------------------------


async def test_posts_json_headers(client, corpus):
    response = await client.get(POSTS_JSON)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    today = datetime.now(UTC).date().isoformat()
    assert response.headers["content-disposition"] == (
        f'attachment; filename="urbanfloods-cooperation-posts-{today}.json"'
    )


async def test_posts_json_lists_published_posts_only(client, corpus):
    items = _by_id((await client.get(POSTS_JSON)).json())

    for post in (corpus.post, corpus.anon_post, corpus.orphan_post, corpus.formula_post):
        assert post.id in items
    for post in corpus.hidden_posts:
        assert post.id not in items


async def test_posts_json_item_fields(client, corpus):
    item = _by_id((await client.get(POSTS_JSON)).json())[corpus.post.id]

    assert set(item) == POST_FIELDS


async def test_posts_json_item_values(client, corpus):
    item = _by_id((await client.get(POSTS_JSON)).json())[corpus.post.id]
    post = corpus.post

    assert item["slug"] == post.slug
    assert item["title"] == post.title
    assert item["locale"] == "it"
    assert item["excerpt"] == "Short summary of the case."
    assert item["body_html"] == post.body_html
    assert item["body_text"] == post.body_text
    assert item["url"] == f"{FRONTEND}/blog/{post.slug}"
    assert item["category"] == {"slug": corpus.blog_slug, "name": "Case studies"}
    assert [tag["name"] for tag in item["tags"]] == corpus.tag_names
    assert datetime.fromisoformat(item["event_at"]) == EVENT_AT
    assert item["event_url"] == "https://example.org/event"
    assert datetime.fromisoformat(item["published_at"]) == post.published_at
    assert datetime.fromisoformat(item["updated_at"]) == post.updated_at
    assert item["knowbase_links"] == [{"kb_type": "measure", "kb_id": 7, "title": "Basin"}]


async def test_posts_json_licence(client, corpus):
    for item in (await client.get(POSTS_JSON)).json():
        assert item["license"] == "CC-BY-4.0"
        assert item["license_url"] == LICENSE_URL


async def test_posts_json_author_shape(client, corpus):
    item = _by_id((await client.get(POSTS_JSON)).json())[corpus.post.id]
    organisation = corpus.organisation

    assert item["author"] == {
        "id": corpus.author.id,
        "display_name": "Ada Author",
        "organisation": {
            "id": organisation.id,
            "name": organisation.name,
            "short_name": "UFX",
            "country": "IT",
        },
    }


async def test_posts_json_anonymised_author(client, corpus):
    items = _by_id((await client.get(POSTS_JSON)).json())

    deleted = {"id": None, "display_name": "Deleted user", "organisation": None}
    assert items[corpus.anon_post.id]["author"] == deleted
    assert items[corpus.orphan_post.id]["author"] == deleted


async def test_posts_json_published_comments_only(client, corpus):
    item = _by_id((await client.get(POSTS_JSON)).json())[corpus.post.id]

    comments = item["comments"]
    assert [c["id"] for c in comments] == corpus.published_comment_ids
    assert set(comments[0]) == {"id", "author", "body_text", "created_at"}
    assert comments[0]["body_text"] == "First comment"
    assert comments[0]["author"]["display_name"] == "Cy Commenter"
    assert comments[1]["author"] == {
        "id": None,
        "display_name": "Deleted user",
        "organisation": None,
    }


async def test_posts_json_contains_no_email(client, corpus):
    _assert_no_email(_ok(await client.get(POSTS_JSON)), corpus)


async def test_posts_json_is_chunked_in_id_order(client, corpus, monkeypatch):
    monkeypatch.setattr(crud_export, "CHUNK_SIZE", 2)

    items = (await client.get(POSTS_JSON)).json()

    ids = [item["id"] for item in items]
    assert ids == await _published_ids(corpus.db, Post)
    assert len(ids) >= 4
    # Children of every chunk are loaded, not only of the first.
    assert _by_id(items)[corpus.post.id]["comments"]


async def test_posts_json_etag_and_last_modified(client, corpus):
    response = await client.get(POSTS_JSON)

    etag = response.headers["etag"]
    assert etag.startswith('"') and etag.endswith('"')
    assert response.headers["last-modified"].endswith("GMT")
    again = await client.get(POSTS_JSON, headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.content == b""


async def test_posts_json_etag_changes_when_a_post_is_hidden(client, corpus):
    etag = (await client.get(POSTS_JSON)).headers["etag"]

    corpus.anon_post.status = ContentStatus.HIDDEN
    await corpus.db.commit()

    response = await client.get(POSTS_JSON, headers={"If-None-Match": etag})
    assert response.status_code == 200
    assert response.headers["etag"] != etag
    assert corpus.anon_post.id not in _by_id(response.json())


# --- validators: If-None-Match and what the ETag covers (7n) ----------------------------------

ALL_EXPORTS = [POSTS_JSON, POSTS_CSV, THREADS_JSON]


async def _etags(client, urls: list[str]) -> dict[str, str]:
    return {url: (await client.get(url)).headers["etag"] for url in urls}


@pytest.mark.parametrize(
    "header",
    ["{etag}", "W/{etag}", '"other", W/{etag}', 'W/"other",{etag}', "*"],
    ids=["strong", "weak", "weak-in-list", "strong-in-list", "star"],
)
async def test_if_none_match_weak_comparison(client, corpus, header):
    """nginx (``gzip_proxied any``) hands the client ``W/"…"``; it must still match."""
    etag = (await client.get(POSTS_JSON)).headers["etag"]

    response = await client.get(POSTS_JSON, headers={"If-None-Match": header.format(etag=etag)})

    assert response.status_code == 304
    assert response.headers["etag"] == etag


@pytest.mark.parametrize("header", ['"other"', 'W/"other"', "", "W/"])
async def test_if_none_match_other_tag_is_200(client, corpus, header):
    response = await client.get(POSTS_JSON, headers={"If-None-Match": header})

    assert response.status_code == 200


async def _assert_changed(client, before: dict[str, str], urls: list[str]) -> None:
    after = await _etags(client, list(before))
    for url in before:
        if url in urls:
            assert after[url] != before[url], url
        else:
            assert after[url] == before[url], url


async def test_etag_changes_when_the_author_is_renamed(client, corpus):
    before = await _etags(client, ALL_EXPORTS)

    corpus.author.display_name = "Ada Renamed"
    await corpus.db.commit()

    await _assert_changed(client, before, ALL_EXPORTS)


async def test_etag_changes_when_the_author_is_erased(client, corpus, cleanup_user_ids):
    cleanup_user_ids.add(corpus.author.id)  # the address is freed on erasure
    before = await _etags(client, ALL_EXPORTS)

    await anonymise_user(corpus.db, user=corpus.author)
    await corpus.db.commit()

    await _assert_changed(client, before, ALL_EXPORTS)


async def test_etag_changes_when_the_organisation_is_renamed(client, corpus, cleanup_organisations):
    before = await _etags(client, ALL_EXPORTS)

    corpus.organisation.name = f"Renamed organisation {uuid.uuid4().hex[:8]}"
    cleanup_organisations.add(corpus.organisation.name)  # cleaned up by name
    await corpus.db.commit()

    await _assert_changed(client, before, ALL_EXPORTS)


async def test_etag_changes_when_a_category_is_renamed(client, corpus):
    blog = await corpus.db.get(Category, corpus.post.category_id)
    forum = await corpus.db.get(Category, corpus.thread.category_id)
    before = await _etags(client, ALL_EXPORTS)

    blog.name = "Case studies, renamed"
    await corpus.db.commit()
    await _assert_changed(client, before, [POSTS_JSON, POSTS_CSV])

    before = await _etags(client, ALL_EXPORTS)
    forum.name = "Design questions, renamed"
    await corpus.db.commit()
    await _assert_changed(client, before, [THREADS_JSON])


async def test_etag_changes_when_a_tag_is_renamed(client, corpus):
    tag = (await corpus.db.scalars(select(Tag).where(Tag.name == corpus.tag_names[0]))).one()
    before = await _etags(client, ALL_EXPORTS)

    tag.name = f"{tag.name} renamed"
    await corpus.db.commit()

    await _assert_changed(client, before, ALL_EXPORTS)


async def test_etag_changes_when_a_knowbase_link_is_removed(client, corpus):
    before = await _etags(client, ALL_EXPORTS)

    await corpus.db.execute(
        delete(KnowbaseLink).where(
            KnowbaseLink.content_type == ContentType.POST,
            KnowbaseLink.content_id == corpus.post.id,
        )
    )
    await corpus.db.commit()

    await _assert_changed(client, before, [POSTS_JSON])


async def test_etag_ignores_a_non_author_rename(client, corpus, cleanup_users):
    """Only the authors of exported content are fingerprinted."""
    member = await create_verified_user(corpus.db, display_name="Quiet Member")
    cleanup_users.add(member.email)
    await corpus.db.commit()
    before = await _etags(client, ALL_EXPORTS)

    member.display_name = "Quiet Member, renamed"
    await corpus.db.commit()

    await _assert_changed(client, before, [])


async def test_etag_ignores_a_registration(client, corpus, cleanup_users):
    before = await _etags(client, ALL_EXPORTS)

    member = await create_verified_user(corpus.db, display_name="Newcomer")
    cleanup_users.add(member.email)
    await corpus.db.commit()

    await _assert_changed(client, before, [])


async def test_etag_changes_when_a_commenter_is_renamed(client, corpus, cleanup_users):
    """A comment's author is in the posts JSON (comments), not in the CSV or the threads."""
    commenter = await create_verified_user(corpus.db, display_name="Only Comments")
    cleanup_users.add(commenter.email)
    await create_comment(corpus.db, post_id=corpus.post.id, author_id=commenter.id, body="Hi")
    await corpus.db.commit()
    before = await _etags(client, ALL_EXPORTS)

    commenter.display_name = "Only Comments, renamed"
    await corpus.db.commit()

    await _assert_changed(client, before, [POSTS_JSON])


async def test_etag_rows_are_unambiguous(client, corpus):
    """Name ``A:<id>`` without an organisation and name ``A`` with organisation ``<id>`` once
    joined to the same text; each value is quoted now (7n review)."""
    org_id = corpus.organisation.id
    corpus.author.display_name = f"A:{org_id}"
    corpus.author.organisation_id = None
    await corpus.db.commit()
    first = await _etags(client, ALL_EXPORTS)

    corpus.author.display_name = "A"
    corpus.author.organisation_id = org_id
    await corpus.db.commit()

    await _assert_changed(client, first, ALL_EXPORTS)


async def test_etag_ignores_a_sign_in(client, corpus):
    """A login bumps ``users.updated_at``; nothing exported changes, so neither does the ETag."""
    before = await _etags(client, ALL_EXPORTS)

    corpus.author.last_login_at = datetime.now(UTC)
    await corpus.db.commit()

    await _assert_changed(client, before, [])


# --- threads.json -----------------------------------------------------------------------------


async def test_threads_json_headers(client, corpus):
    response = await client.get(THREADS_JSON)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    today = datetime.now(UTC).date().isoformat()
    assert response.headers["content-disposition"] == (
        f'attachment; filename="urbanfloods-cooperation-threads-{today}.json"'
    )
    assert "etag" in response.headers


async def test_threads_json_lists_published_threads_only(client, corpus):
    items = _by_id((await client.get(THREADS_JSON)).json())

    assert corpus.thread.id in items
    assert corpus.anon_thread.id in items
    for thread in corpus.hidden_threads:
        assert thread.id not in items


async def test_threads_json_item_fields_and_values(client, corpus):
    item = _by_id((await client.get(THREADS_JSON)).json())[corpus.thread.id]
    thread = corpus.thread

    assert set(item) == THREAD_FIELDS
    assert item["url"] == f"{FRONTEND}/forum/t/{thread.slug}"
    assert item["category"]["name"] == "Design questions"
    assert item["body_text"] == thread.body_text
    assert item["license"] == "CC-BY-4.0"
    assert item["license_url"] == LICENSE_URL
    assert item["knowbase_links"][0]["kb_type"] == "document"
    assert item["author"]["display_name"] == "Ada Author"


async def test_threads_json_published_replies_only(client, corpus):
    item = _by_id((await client.get(THREADS_JSON)).json())[corpus.thread.id]

    replies = item["replies"]
    assert [r["id"] for r in replies] == corpus.published_reply_ids
    assert set(replies[0]) == {"id", "parent_reply_id", "author", "body_text", "created_at"}
    assert replies[0]["parent_reply_id"] is None
    assert replies[1]["parent_reply_id"] == corpus.parent_reply_id
    assert replies[1]["author"]["display_name"] == "Deleted user"
    assert replies[1]["body_text"] == "Child"


async def test_threads_json_anonymised_author(client, corpus):
    item = _by_id((await client.get(THREADS_JSON)).json())[corpus.anon_thread.id]

    assert item["author"] == {"id": None, "display_name": "Deleted user", "organisation": None}


async def test_threads_json_contains_no_email(client, corpus):
    _assert_no_email(_ok(await client.get(THREADS_JSON)), corpus)


async def test_threads_json_is_chunked_in_id_order(client, corpus, monkeypatch):
    monkeypatch.setattr(crud_export, "CHUNK_SIZE", 2)

    items = (await client.get(THREADS_JSON)).json()

    assert [item["id"] for item in items] == await _published_ids(corpus.db, Thread)
    assert _by_id(items)[corpus.thread.id]["replies"]


# --- posts.csv --------------------------------------------------------------------------------


async def test_posts_csv_headers(client, corpus):
    response = await client.get(POSTS_CSV)

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    today = datetime.now(UTC).date().isoformat()
    assert response.headers["content-disposition"] == (
        f'attachment; filename="urbanfloods-cooperation-posts-{today}.csv"'
    )


async def test_posts_csv_header_row(client, corpus):
    rows = _csv_rows((await client.get(POSTS_CSV)).text)

    assert rows[0] == CSV_HEADER


async def test_posts_csv_row_values(client, corpus):
    rows = {row[0]: row for row in _csv_rows((await client.get(POSTS_CSV)).text)[1:]}
    post = corpus.post

    row = rows[str(post.id)]
    assert row[1] == post.slug
    assert row[2] == post.title
    assert row[3] == "it"
    assert row[4] == "Case studies"
    assert row[5] == ";".join(corpus.tag_names)
    assert row[6] == "Ada Author"
    assert row[7] == corpus.organisation.name
    assert datetime.fromisoformat(row[8]) == post.published_at
    assert row[9] == f"{FRONTEND}/blog/{post.slug}"


async def test_posts_csv_published_only_and_anonymised(client, corpus):
    text = (await client.get(POSTS_CSV)).text
    rows = {row[0]: row for row in _csv_rows(text)[1:]}

    for post in corpus.hidden_posts:
        assert str(post.id) not in rows
    assert rows[str(corpus.anon_post.id)][6] == "Deleted user"
    assert rows[str(corpus.anon_post.id)][7] == ""
    _assert_no_email(text, corpus)


async def test_posts_csv_neutralises_formula_cells(client, corpus):
    rows = {row[0]: row for row in _csv_rows((await client.get(POSTS_CSV)).text)[1:]}

    assert rows[str(corpus.formula_post.id)][2] == f"'{corpus.formula_post.title}"


async def test_posts_csv_is_chunked_in_id_order(client, corpus, monkeypatch):
    monkeypatch.setattr(crud_export, "CHUNK_SIZE", 2)

    rows = _csv_rows((await client.get(POSTS_CSV)).text)

    assert rows[0] == CSV_HEADER
    assert [int(row[0]) for row in rows[1:]] == await _published_ids(corpus.db, Post)


async def test_posts_csv_has_no_bodies(client, corpus):
    text = _ok(await client.get(POSTS_CSV))

    assert corpus.post.body_text not in text
    assert "<p>" not in text


# --- datapackage.json -------------------------------------------------------------------------


async def test_datapackage_headers(client):
    response = await client.get(DATAPACKAGE)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


async def test_datapackage_descriptor(client):
    package = (await client.get(DATAPACKAGE)).json()

    for key in ("name", "title", "description", "licenses", "created", "sources", "resources"):
        assert package[key], key
    assert re.fullmatch(r"[a-z0-9._-]+", package["name"])
    assert package["licenses"] == [
        {"name": "CC-BY-4.0", "path": LICENSE_URL, "title": "Creative Commons Attribution 4.0"}
    ]
    created = datetime.fromisoformat(package["created"].replace("Z", "+00:00"))
    assert created.tzinfo is not None
    assert abs(datetime.now(UTC) - created) < timedelta(minutes=5)
    assert any("Interreg IPA ADRION" in source["title"] for source in package["sources"])
    assert all(contributor["title"] for contributor in package["contributors"])
    assert package["homepage"] == FRONTEND


async def test_datapackage_resources(client):
    resources = (await client.get(DATAPACKAGE)).json()["resources"]

    paths = {resource["name"]: resource["path"] for resource in resources}
    assert paths == {
        "posts-json": f"{FRONTEND}{POSTS_JSON}",
        "threads-json": f"{FRONTEND}{THREADS_JSON}",
        "posts-csv": f"{FRONTEND}{POSTS_CSV}",
    }
    for resource in resources:
        assert re.fullmatch(r"[a-z0-9._-]+", resource["name"])
        assert resource["path"].startswith("https://")
        assert resource["format"] in {"json", "csv"}
        assert resource["mediatype"] in {"application/json", "text/csv"}
        assert resource["licenses"][0]["name"] == "CC-BY-4.0"


async def test_datapackage_csv_schema_matches_csv_header(client, corpus):
    resources = (await client.get(DATAPACKAGE)).json()["resources"]
    csv_resource = next(r for r in resources if r["format"] == "csv")
    header = _csv_rows((await client.get(POSTS_CSV)).text)[0]

    fields = csv_resource["schema"]["fields"]
    assert [f["name"] for f in fields] == header
    types = {f["name"]: f["type"] for f in fields}
    assert types["id"] == "integer"
    assert types["published_at"] == "datetime"
    assert csv_resource["schema"]["primaryKey"] == ["id"]
    assert csv_resource["encoding"] == "utf-8"
    assert csv_resource["dialect"]["header"] is True


async def test_datapackage_is_valid_json_without_email(client):
    text = _ok(await client.get(DATAPACKAGE))

    json.loads(text)
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
