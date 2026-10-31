"""Increment 5b: Atom feeds (``/feeds/posts.atom``, ``/feeds/threads.atom``), ``/sitemap.xml``
and ``/robots.txt``, all mounted without the API prefix.

feedparser is not a dependency, so the XML is parsed with ``xml.etree`` and checked against
Atom 1.0 (RFC 4287) and the sitemaps.org schema by hand. Published content only; no email.
"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta

import pytest

from app.core.config import settings
from app.db.enums import CategoryKind, ContentStatus
from tests.factories import create_category, create_post
from tests.test_export import FRONTEND, LICENSE_URL, Corpus, _ok, build_corpus

ATOM = "http://www.w3.org/2005/Atom"
SITEMAP = "http://www.sitemaps.org/schemas/sitemap/0.9"
NS = {"a": ATOM, "s": SITEMAP}
POSTS_FEED = "/feeds/posts.atom"
THREADS_FEED = "/feeds/threads.atom"
STATIC_PATHS = [
    "/",
    "/blog",
    "/forum",
    "/network",
    "/about",
    "/terms",
    "/privacy",
    "/accessibility",
    "/open-data",
]


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


def _parse(text: str) -> ET.Element:
    return ET.fromstring(text.encode("utf-8"))


def _entries(feed: ET.Element) -> dict[str, ET.Element]:
    """Entries keyed by their alternate link."""
    result = {}
    for entry in feed.findall("a:entry", NS):
        link = entry.find("a:link[@rel='alternate']", NS)
        assert link is not None
        result[link.get("href")] = entry
    return result


def _text(element: ET.Element, path: str) -> str:
    found = element.find(path, NS)
    assert found is not None, path
    return found.text or ""


# --- posts feed -------------------------------------------------------------------------------


async def test_posts_feed_headers(client, corpus):
    response = await client.get(POSTS_FEED)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/atom+xml; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=900"


async def test_posts_feed_is_atom(client, corpus):
    response = await client.get(POSTS_FEED)
    assert response.text.startswith('<?xml version="1.0" encoding="utf-8"?>')
    feed = _parse(response.text)

    assert feed.tag == f"{{{ATOM}}}feed"
    assert _text(feed, "a:id")
    assert "Blog" in _text(feed, "a:title")
    assert datetime.fromisoformat(_text(feed, "a:updated")).tzinfo is not None
    self_link = feed.find("a:link[@rel='self']", NS)
    assert self_link is not None
    assert self_link.get("href") == f"{FRONTEND}{POSTS_FEED}"
    assert self_link.get("type") == "application/atom+xml"
    alternate = feed.find("a:link[@rel='alternate']", NS)
    assert alternate is not None and alternate.get("href") == f"{FRONTEND}/blog"
    assert _text(feed, "a:author/a:name")


async def test_posts_feed_rights(client, corpus):
    feed = _parse((await client.get(POSTS_FEED)).text)

    rights = _text(feed, "a:rights")
    assert "CC BY 4.0" in rights
    assert LICENSE_URL in rights


async def test_posts_feed_entry(client, corpus):
    feed = _parse((await client.get(POSTS_FEED)).text)
    post = corpus.post

    entry = _entries(feed)[f"{FRONTEND}/blog/{post.slug}"]
    entry_id = _text(entry, "a:id")
    assert entry_id.startswith("tag:cooperation.example.org,")
    assert entry_id.endswith(f":post:{post.id}")
    assert _text(entry, "a:title") == post.title
    assert _text(entry, "a:author/a:name") == "Ada Author"
    assert datetime.fromisoformat(_text(entry, "a:updated")) == post.updated_at
    assert datetime.fromisoformat(_text(entry, "a:published")) == post.published_at
    summary = entry.find("a:summary", NS)
    assert summary is not None and summary.get("type") == "text"
    assert summary.text == "Short summary of the case."
    content = entry.find("a:content", NS)
    assert content is not None and content.get("type") == "html"
    assert content.text == post.body_html
    categories = [c.get("term") for c in entry.findall("a:category", NS)]
    assert corpus.blog_slug in categories


async def test_posts_feed_published_only(client, corpus):
    response = await client.get(POSTS_FEED)
    entries = _entries(_parse(response.text))

    assert f"{FRONTEND}/blog/{corpus.anon_post.slug}" in entries
    for post in corpus.hidden_posts:
        assert f"{FRONTEND}/blog/{post.slug}" not in entries
        assert post.slug not in response.text


async def test_posts_feed_anonymised_author_and_no_email(client, corpus):
    response = await client.get(POSTS_FEED)
    entries = _entries(_parse(response.text))

    entry = entries[f"{FRONTEND}/blog/{corpus.anon_post.slug}"]
    assert _text(entry, "a:author/a:name") == "Deleted user"
    orphan = entries[f"{FRONTEND}/blog/{corpus.orphan_post.slug}"]
    assert _text(orphan, "a:author/a:name") == "Deleted user"
    for email in corpus.emails:
        assert email not in response.text
    assert "@invalid" not in response.text
    assert entry.find("a:author/a:email", NS) is None


async def test_posts_feed_summary_falls_back_to_body_text(client, corpus):
    entries = _entries(_parse((await client.get(POSTS_FEED)).text))

    entry = entries[f"{FRONTEND}/blog/{corpus.anon_post.slug}"]
    assert _text(entry, "a:summary") == corpus.anon_post.body_text


async def test_posts_feed_newest_twenty(client, db_session, cleanup_categories) -> None:
    category = await create_category(db_session, kind=CategoryKind.BLOG)
    cleanup_categories.add(category.id)
    start = datetime.now(UTC) + timedelta(days=3650)
    slugs = []
    for index in range(21):
        post = await create_post(
            db_session,
            category_id=category.id,
            slug=f"future-{uuid.uuid4().hex[:10]}-{index}",
        )
        post.published_at = start + timedelta(minutes=index)
        slugs.append(post.slug)
    await db_session.commit()

    entries = _parse((await client.get(POSTS_FEED)).text).findall("a:entry", NS)

    assert len(entries) == 20
    hrefs = [e.find("a:link[@rel='alternate']", NS).get("href") for e in entries]
    assert hrefs == [f"{FRONTEND}/blog/{slug}" for slug in reversed(slugs[1:])]


async def test_feed_strips_xml_invalid_characters(client, corpus):
    corpus.anon_post.title = "Bad\x0bchar\x1ftitle"
    await corpus.db.commit()

    response = await client.get(POSTS_FEED)
    entries = _entries(_parse(response.text))

    entry = entries[f"{FRONTEND}/blog/{corpus.anon_post.slug}"]
    assert _text(entry, "a:title") == "Badchartitle"


async def test_feed_escapes_markup_in_titles(client, corpus):
    corpus.anon_post.title = 'Ponds & <swales> "now"'
    await corpus.db.commit()

    entries = _entries(_parse((await client.get(POSTS_FEED)).text))

    entry = entries[f"{FRONTEND}/blog/{corpus.anon_post.slug}"]
    assert _text(entry, "a:title") == 'Ponds & <swales> "now"'


async def test_feed_sets_xml_base_for_relative_images(client, corpus):
    feed = _parse((await client.get(POSTS_FEED)).text)

    assert feed.get("{http://www.w3.org/XML/1998/namespace}base") == f"{FRONTEND}/"


# --- threads feed -----------------------------------------------------------------------------


async def test_threads_feed_headers(client, corpus):
    response = await client.get(THREADS_FEED)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/atom+xml; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=900"


async def test_threads_feed_entries(client, corpus):
    response = await client.get(THREADS_FEED)
    feed = _parse(response.text)

    assert "Forum" in _text(feed, "a:title")
    self_link = feed.find("a:link[@rel='self']", NS)
    assert self_link is not None and self_link.get("href") == f"{FRONTEND}{THREADS_FEED}"
    assert "CC BY 4.0" in _text(feed, "a:rights")
    entries = _entries(feed)
    entry = entries[f"{FRONTEND}/forum/t/{corpus.thread.slug}"]
    assert _text(entry, "a:id").endswith(f":thread:{corpus.thread.id}")
    assert _text(entry, "a:title") == corpus.thread.title
    assert _text(entry, "a:summary") == corpus.thread.body_text
    content = entry.find("a:content", NS)
    assert content is not None and content.get("type") == "html"
    assert content.text == corpus.thread.body_html


async def test_threads_feed_published_only(client, corpus):
    response = await client.get(THREADS_FEED)
    entries = _entries(_parse(response.text))

    assert f"{FRONTEND}/forum/t/{corpus.anon_thread.slug}" in entries
    for thread in corpus.hidden_threads:
        assert f"{FRONTEND}/forum/t/{thread.slug}" not in entries
    for email in corpus.emails:
        assert email not in response.text


async def test_feeds_are_not_under_the_api_prefix(client):
    response = await client.get(f"{settings.API_V1_PREFIX}{POSTS_FEED}")

    assert response.status_code == 404


# --- sitemap and robots -----------------------------------------------------------------------


async def test_sitemap_headers(client, corpus):
    response = await client.get("/sitemap.xml")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/xml; charset=utf-8"
    assert response.headers["cache-control"] == "public, max-age=3600"


async def test_sitemap_static_pages(client, corpus):
    urlset = _parse((await client.get("/sitemap.xml")).text)

    assert urlset.tag == f"{{{SITEMAP}}}urlset"
    locs = [_text(url, "s:loc") for url in urlset.findall("s:url", NS)]
    for path in STATIC_PATHS:
        expected = f"{FRONTEND}/" if path == "/" else f"{FRONTEND}{path}"
        assert expected in locs
    # Browsing the KNOWBASE happens on its own site (user decision 2026-10-31): no library page.
    assert not any(loc.startswith(f"{FRONTEND}/knowbase") for loc in locs)
    # The partners are a section of /about (user decision 2026-10-31); /partners only redirects.
    assert f"{FRONTEND}/partners" not in locs


async def test_sitemap_content_urls_with_lastmod(client, corpus):
    urlset = _parse((await client.get("/sitemap.xml")).text)
    urls = {_text(url, "s:loc"): url for url in urlset.findall("s:url", NS)}

    post_url = urls[f"{FRONTEND}/blog/{corpus.post.slug}"]
    assert datetime.fromisoformat(_text(post_url, "s:lastmod")) == corpus.post.updated_at
    thread_url = urls[f"{FRONTEND}/forum/t/{corpus.thread.slug}"]
    assert datetime.fromisoformat(_text(thread_url, "s:lastmod")) == corpus.thread.updated_at


async def test_sitemap_excludes_unpublished(client, corpus):
    text = _ok(await client.get("/sitemap.xml"))

    for post in corpus.hidden_posts:
        assert post.slug not in text
    for thread in corpus.hidden_threads:
        assert thread.slug not in text


async def test_sitemap_lists_each_url_once(client, corpus):
    urlset = _parse((await client.get("/sitemap.xml")).text)
    locs = [_text(url, "s:loc") for url in urlset.findall("s:url", NS)]

    assert len(locs) == len(set(locs))


async def test_robots_txt(client):
    response = await client.get("/robots.txt")

    assert response.status_code == 200
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    lines = response.text.splitlines()
    assert "User-agent: *" in lines
    assert "Allow: /" in lines
    assert f"Sitemap: {FRONTEND}/sitemap.xml" in lines


async def test_unpublished_post_status_change_drops_it_from_feed_and_sitemap(client, corpus):
    corpus.post.status = ContentStatus.HIDDEN
    await corpus.db.commit()

    feed_text = _ok(await client.get(POSTS_FEED))
    sitemap_text = _ok(await client.get("/sitemap.xml"))

    assert corpus.post.slug not in feed_text
    assert corpus.post.slug not in sitemap_text
