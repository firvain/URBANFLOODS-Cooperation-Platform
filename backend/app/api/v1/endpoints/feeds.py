"""Atom 1.0 feeds of the newest published posts and threads, the sitemap and robots.txt.
Mounted without the API prefix (like the probes). Public, published content only.

XML is built with ``xml.etree`` (which escapes text and attributes); characters XML 1.0 does
not allow are dropped first. Elements are unqualified under a default ``xmlns`` on the root,
so no global namespace registration is needed. Absolute URLs use ``FRONTEND_URL``: the site is
same-origin, so the frontend's host serves these paths too (its nginx proxies them).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from datetime import UTC, datetime
from urllib.parse import urlsplit

from fastapi import APIRouter, Response

from app.api.v1.schemas.export import author_name, frontend_url, post_url, thread_url
from app.core.config import settings
from app.core.deps import DbTx
from app.crud import export as crud_export
from app.db.enums import ContentType
from app.db.models import Post, Thread
from app.services.sanitize import excerpt

router = APIRouter()

SITE_NAME = "URBANFLOODS Cooperation Platform"
ATOM_NS = "http://www.w3.org/2005/Atom"
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XML_BASE = "{http://www.w3.org/XML/1998/namespace}base"
XML_DECLARATION = '<?xml version="1.0" encoding="utf-8"?>\n'
ATOM_MEDIA_TYPE = "application/atom+xml; charset=utf-8"
XML_MEDIA_TYPE = "application/xml; charset=utf-8"
FEED_CACHE = "public, max-age=900"
SITEMAP_CACHE = "public, max-age=3600"
# Year in the ``tag:`` URIs (RFC 4151): when the platform's host name was first used.
TAG_YEAR = "2026"
STATIC_PATHS = (
    "/",
    "/blog",
    "/forum",
    "/network",
    "/about",
    "/terms",
    "/privacy",
    "/accessibility",
    "/open-data",
    # "Measures at a glance" (7c), the platform's one KNOWBASE list page.
    "/knowbase/measures",
)
ROBOTS_DISALLOW = ("/account", "/admin")

_INVALID_XML_CHARS = re.compile("[^\t\n\r -퟿-�\U00010000-\U0010ffff]")


def _clean(text: str | None) -> str:
    return _INVALID_XML_CHARS.sub("", text or "")


def _sub(parent: ET.Element, tag: str, text: str | None = None, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, tag, {key: _clean(value) for key, value in attrs.items()})
    if text is not None:
        element.text = _clean(text)
    return element


def _serialise(root: ET.Element) -> bytes:
    return (XML_DECLARATION + ET.tostring(root, encoding="unicode")).encode("utf-8")


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _tag_uri(specific: str) -> str:
    host = urlsplit(settings.FRONTEND_URL).hostname or "localhost"
    return f"tag:{host},{TAG_YEAR}:{specific}"


def _rights() -> str:
    return (
        f"Contributions are © their authors and licensed under CC BY 4.0: "
        f"{settings.CONTENT_LICENSE_URL}"
    )


# --- Atom -------------------------------------------------------------------------------------


def _feed(
    *, kind: str, title: str, alternate: str, self_path: str, updated: datetime
) -> ET.Element:
    feed = ET.Element("feed", {"xmlns": ATOM_NS, XML_BASE: frontend_url("/")})
    _sub(feed, "id", _tag_uri(f"feed:{kind}"))
    _sub(feed, "title", f"{SITE_NAME}: {title}", type="text")
    _sub(feed, "updated", _rfc3339(updated))
    _sub(feed, "link", rel="self", type="application/atom+xml", href=frontend_url(self_path))
    _sub(feed, "link", rel="alternate", type="text/html", href=alternate)
    _sub(feed, "rights", _rights(), type="text")
    author = _sub(feed, "author")
    _sub(author, "name", SITE_NAME)
    return feed


def _entry(
    feed: ET.Element,
    *,
    content: Post | Thread,
    kind: ContentType,
    url: str,
    summary: str,
) -> None:
    entry = _sub(feed, "entry")
    _sub(entry, "id", _tag_uri(f"{kind.value}:{content.id}"))
    _sub(entry, "title", content.title, type="text")
    _sub(entry, "link", rel="alternate", type="text/html", href=url)
    if content.published_at is not None:
        _sub(entry, "published", _rfc3339(content.published_at))
    _sub(entry, "updated", _rfc3339(content.updated_at))
    author = _sub(entry, "author")
    _sub(author, "name", author_name(content.author))
    _sub(entry, "category", term=content.category.slug, label=content.category.name)
    for tag in content.tags:
        _sub(entry, "category", term=tag.slug, label=tag.name)
    _sub(entry, "summary", summary, type="text")
    _sub(entry, "content", content.body_html, type="html")


def _feed_updated(items: Sequence[Post | Thread]) -> datetime:
    return max((item.updated_at for item in items), default=datetime.now(UTC))


def _atom(body: bytes) -> Response:
    return Response(content=body, media_type=ATOM_MEDIA_TYPE, headers={"Cache-Control": FEED_CACHE})


ATOM_RESPONSES = {200: {"description": "Atom 1.0 feed", "content": {"application/atom+xml": {}}}}


@router.get("/feeds/posts.atom", response_class=Response, responses=ATOM_RESPONSES)
async def posts_feed(db: DbTx) -> Response:
    """The 20 newest published blog posts."""
    posts = await crud_export.latest_posts(db)
    feed = _feed(
        kind="posts",
        title="Blog",
        alternate=frontend_url("/blog"),
        self_path="/feeds/posts.atom",
        updated=_feed_updated(posts),
    )
    for post in posts:
        _entry(
            feed,
            content=post,
            kind=ContentType.POST,
            url=post_url(post.slug),
            summary=post.excerpt or excerpt(post.body_text),
        )
    return _atom(_serialise(feed))


@router.get("/feeds/threads.atom", response_class=Response, responses=ATOM_RESPONSES)
async def threads_feed(db: DbTx) -> Response:
    """The 20 newest published forum threads."""
    threads = await crud_export.latest_threads(db)
    feed = _feed(
        kind="threads",
        title="Forum",
        alternate=frontend_url("/forum"),
        self_path="/feeds/threads.atom",
        updated=_feed_updated(threads),
    )
    for thread in threads:
        _entry(
            feed,
            content=thread,
            kind=ContentType.THREAD,
            url=thread_url(thread.slug),
            summary=excerpt(thread.body_text),
        )
    return _atom(_serialise(feed))


# --- sitemap and robots -----------------------------------------------------------------------


@router.get(
    "/sitemap.xml",
    response_class=Response,
    responses={200: {"description": "Sitemap", "content": {"application/xml": {}}}},
)
async def sitemap(db: DbTx) -> Response:
    """Static pages, then every published post and thread with its ``lastmod``."""
    urlset = ET.Element("urlset", {"xmlns": SITEMAP_NS})
    for path in STATIC_PATHS:
        url = _sub(urlset, "url")
        _sub(url, "loc", frontend_url(path))
    for entry in await crud_export.sitemap_entries(db):
        url = _sub(urlset, "url")
        loc = post_url(entry.slug) if entry.kind == ContentType.POST else thread_url(entry.slug)
        _sub(url, "loc", loc)
        _sub(url, "lastmod", _rfc3339(entry.lastmod))
    return Response(
        content=_serialise(urlset),
        media_type=XML_MEDIA_TYPE,
        headers={"Cache-Control": SITEMAP_CACHE},
    )


@router.get(
    "/robots.txt",
    response_class=Response,
    responses={200: {"description": "robots.txt", "content": {"text/plain": {}}}},
)
async def robots() -> Response:
    """Crawl everything public (account and admin pages excluded); points at the sitemap."""
    lines = ["User-agent: *", "Allow: /"]
    lines += [f"Disallow: {path}" for path in ROBOTS_DISALLOW]
    lines += ["", f"Sitemap: {frontend_url('/sitemap.xml')}"]
    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain",
        headers={"Cache-Control": SITEMAP_CACHE},
    )
