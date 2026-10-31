"""HTML sanitisation (nh3) for rich-text bodies, plain-text extraction, excerpts and URL checks.

Every user-supplied HTML body passes through :func:`sanitize_html` before storage. The allow-list
is tuned to what the Tiptap editor (StarterKit + Link + Image + Table) emits; anything else is
stripped. ``h1`` is downgraded to ``h2`` because a post's title is the page's ``h1``.

Images are kept only when their ``src`` is an absolute http(s) URL or a path under our own
``/static/uploads/``; any other image is dropped entirely rather than left without a source.
"""

from __future__ import annotations

import html as html_lib
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

import nh3

ELLIPSIS = "…"
EXCERPT_LENGTH = 500
MAX_URL_LENGTH = 2048
LINK_REL = "nofollow noopener noreferrer"
UPLOADS_PREFIX = "/static/uploads/"

ALLOWED_TAGS = frozenset(
    {
        "p", "br", "h1", "h2", "h3", "h4", "ul", "ol", "li", "blockquote", "pre", "code",
        "strong", "em", "u", "s", "a", "img", "hr", "table", "thead", "tbody", "tr", "th", "td",
        "sup", "sub",
    }
)  # fmt: skip
# ``rel`` is not listed: nh3 always sets it to LINK_REL on links (it requires ``rel`` to be absent
# from the allow-list when ``link_rel`` is used), so any user-supplied value is replaced.
ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "title", "width", "height"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
    "code": {"class"},
    "pre": {"class"},
}
URL_SCHEMES = frozenset({"http", "https", "mailto"})
# Tags removed together with their content (must be disjoint from ALLOWED_TAGS).
DROP_CONTENT_TAGS = frozenset(
    {
        "script", "style", "iframe", "object", "embed", "noscript", "template", "textarea",
        "select", "svg", "math", "title",
    }
)  # fmt: skip
BLOCK_TAGS = (
    "address|article|aside|blockquote|br|dd|details|div|dl|dt|figcaption|figure|footer|h[1-6]|"
    "header|hr|li|main|nav|ol|p|pre|section|summary|table|tbody|td|tfoot|th|thead|tr|ul"
)

_LANGUAGE_CLASS = re.compile(r"^language-[a-z0-9-]+$")
# nh3's serialiser always double-quotes attribute values and escapes ``"`` and ``>`` inside them.
_IMG_TAG = re.compile(r"<img\b[^>]*>")
_IMG_HAS_SRC = re.compile(r'\ssrc="[^"]+"')
_H1_TAG = re.compile(r"<(/?)h1>")
_BLOCK_BOUNDARY = re.compile(rf"<(/?)({BLOCK_TAGS})\b", re.IGNORECASE)
_UNSAFE_URL_CHARS = re.compile(r"[\s\x00-\x1f\x7f\\]")


def _is_allowed_img_src(src: str) -> bool:
    if src.startswith(UPLOADS_PREFIX):
        return ".." not in src and "\\" not in src
    scheme = urlsplit(src).scheme.lower()
    return scheme in {"http", "https"} and src.lower().startswith(f"{scheme}://")


def _attribute_filter(tag: str, attr: str, value: str) -> str | None:
    if attr == "class":
        return value if tag in {"code", "pre"} and _LANGUAGE_CLASS.match(value) else None
    if tag == "a" and attr == "target":
        return value if value == "_blank" else None
    if tag == "img" and attr == "src":
        return value if _is_allowed_img_src(value) else None
    return value


def _drop_img_without_src(match: re.Match[str]) -> str:
    tag = match.group(0)
    return tag if _IMG_HAS_SRC.search(tag) else ""


def sanitize_html(html: str) -> str:
    """Clean a rich-text body for storage. Returns ``""`` when nothing visible remains."""
    if not html or not html.strip():
        return ""
    cleaned = nh3.clean(
        html,
        tags=set(ALLOWED_TAGS),
        clean_content_tags=set(DROP_CONTENT_TAGS),
        attributes=ALLOWED_ATTRIBUTES,
        attribute_filter=_attribute_filter,
        url_schemes=set(URL_SCHEMES),
        link_rel=LINK_REL,
        strip_comments=True,
    )
    cleaned = _IMG_TAG.sub(_drop_img_without_src, cleaned)
    cleaned = _H1_TAG.sub(r"<\1h2>", cleaned).strip()
    if not html_to_text(cleaned) and "<img" not in cleaned:
        return ""
    return cleaned


def html_to_text(html: str) -> str:
    """Plain text of an HTML fragment for full-text search and excerpts: tags stripped (script
    and style content dropped), entities decoded, whitespace collapsed to single spaces, and a
    space kept between block elements so their words do not run together."""
    if not html:
        return ""
    spaced = _BLOCK_BOUNDARY.sub(r" <\1\2", html)
    stripped = nh3.clean(spaced, tags=set(), clean_content_tags=set(DROP_CONTENT_TAGS))
    return " ".join(html_lib.unescape(stripped).split())


def plain_text(value: str | None, max_chars: int) -> str | None:
    """A short plain-text field (never HTML; rendered as text everywhere) ready to store: line
    breaks normalised to ``\\n``, other control characters (except tabs) dropped, surrounding
    whitespace stripped, cut to ``max_chars``. ``None`` when nothing is left."""
    if value is None:
        return None
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = "".join(ch for ch in value if ch in "\n\t" or unicodedata.category(ch) != "Cc").strip()
    return value[:max_chars].rstrip() or None


def excerpt(text: str, max_chars: int = EXCERPT_LENGTH) -> str:
    """``text`` as one line, cut on a word boundary to at most ``max_chars`` characters including
    a trailing ellipsis when shortened. A single over-long word is cut hard."""
    text = " ".join(text.split())
    if len(text) <= max_chars:
        return text
    limit = max_chars - len(ELLIPSIS)
    cut = text[:limit]
    if text[limit] != " " and " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip() + ELLIPSIS


def validate_external_url(url: str) -> str:
    """Validate an outbound link (``event_url``, ``web_links``): absolute http(s) with a host, at
    most 2048 characters, no credentials. Returns it with scheme and host lowercased.

    :raises ValueError: when the URL is not acceptable.
    """
    url = url.strip()
    if not url:
        raise ValueError("URL is empty")
    if len(url) > MAX_URL_LENGTH:
        raise ValueError("URL is too long")
    if _UNSAFE_URL_CHARS.search(url):
        raise ValueError("URL contains whitespace or control characters")
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ValueError("URL must use http or https")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise ValueError("URL must not contain credentials")
    if not parts.hostname:
        raise ValueError("URL must have a host")
    _ = parts.port  # raises ValueError for an invalid port
    return urlunsplit((scheme, parts.netloc.lower(), parts.path, parts.query, parts.fragment))
