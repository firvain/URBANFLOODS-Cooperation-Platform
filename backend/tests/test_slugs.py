"""Slug service: transliterating slugify and collision-free unique slugs (sync and async)."""

from __future__ import annotations

import re

import pytest

from app.services.slugs import MAX_SLUG_LENGTH, slugify_title, unique_slug, unique_slug_async

SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


# --- slugify_title ---------------------------------------------------------------------------


def test_slugify_ascii() -> None:
    assert slugify_title("Urban Flood Resilience") == "urban-flood-resilience"


def test_slugify_greek() -> None:
    slug = slugify_title("Πλημμύρες στην Κοζάνη")
    assert slug == "plemmures-sten-kozane"
    assert SLUG_RE.match(slug)


def test_slugify_cyrillic() -> None:
    slug = slugify_title("Поплаве у Новом Саду")
    assert slug == "poplave-u-novom-sadu"
    assert SLUG_RE.match(slug)


def test_slugify_punctuation_and_accents() -> None:
    assert slugify_title("  Hello, World! (2026) — Façade & Co.  ") == "hello-world-2026-facade-co"


def test_slugify_length_cap_on_word_boundary() -> None:
    slug = slugify_title("the quick brown fox jumps over", max_length=12)
    assert slug == "the-quick"
    long_slug = slugify_title("flood " * 40)
    assert len(long_slug) <= 80
    assert SLUG_RE.match(long_slug)
    assert all(part == "flood" for part in long_slug.split("-"))


@pytest.mark.parametrize("title", ["", "   ", "🌊🌊", "!!!", "—"])
def test_slugify_empty_falls_back_to_item(title: str) -> None:
    assert slugify_title(title) == "item"


# --- unique_slug -----------------------------------------------------------------------------


def test_unique_slug_returns_base_when_free() -> None:
    assert unique_slug("floods", lambda s: False) == "floods"


def test_unique_slug_sequence() -> None:
    taken = {"floods", "floods-2", "floods-3"}
    calls: list[str] = []

    def exists(slug: str) -> bool:
        calls.append(slug)
        return slug in taken

    assert unique_slug("floods", exists) == "floods-4"
    assert calls == ["floods", "floods-2", "floods-3", "floods-4"]


def test_unique_slug_random_suffix_after_max_attempts() -> None:
    calls: list[str] = []

    def exists(slug: str) -> bool:
        calls.append(slug)
        return re.fullmatch(r"floods(-\d+)?", slug) is not None

    slug = unique_slug("floods", exists, max_attempts=5)
    assert re.fullmatch(r"floods-[a-z0-9]{6}", slug)
    assert calls[:5] == ["floods", "floods-2", "floods-3", "floods-4", "floods-5"]
    assert calls[-1] == slug


def test_unique_slug_gives_up_when_everything_taken() -> None:
    with pytest.raises(RuntimeError):
        unique_slug("floods", lambda s: True, max_attempts=3)


def test_unique_slug_length_capped_with_long_base() -> None:
    base = "-".join(["word"] * 100)  # 499 chars
    assert len(unique_slug(base, lambda s: False)) <= MAX_SLUG_LENGTH == 220

    taken: set[str] = set()

    def exists(slug: str) -> bool:
        assert len(slug) <= MAX_SLUG_LENGTH
        return slug in taken

    first = unique_slug(base, exists)
    taken.add(first)
    second = unique_slug(base, exists)
    assert second.endswith("-2")
    assert len(second) <= MAX_SLUG_LENGTH
    assert not first.endswith("-")
    assert SLUG_RE.match(second)

    suffixed = unique_slug(
        base, lambda s: re.search(r"-\d+$", s) is not None or s == first, max_attempts=2
    )
    assert len(suffixed) <= MAX_SLUG_LENGTH
    assert SLUG_RE.match(suffixed)


def test_unique_slug_empty_base_uses_item() -> None:
    assert unique_slug("", lambda s: False) == "item"


# --- unique_slug_async -----------------------------------------------------------------------


async def test_unique_slug_async_with_async_exists() -> None:
    taken = {"post", "post-2"}

    async def exists(slug: str) -> bool:
        return slug in taken

    assert await unique_slug_async("post", exists) == "post-3"


async def test_unique_slug_async_accepts_sync_exists() -> None:
    assert await unique_slug_async("post", lambda s: s == "post") == "post-2"


async def test_unique_slug_async_random_suffix() -> None:
    async def exists(slug: str) -> bool:
        return re.fullmatch(r"post(-\d+)?", slug) is not None

    slug = await unique_slug_async("post", exists, max_attempts=3)
    assert re.fullmatch(r"post-[a-z0-9]{6}", slug)


def test_unique_slug_rejects_async_exists() -> None:
    async def exists(slug: str) -> bool:
        return False

    with pytest.raises(TypeError):
        unique_slug("post", exists)  # type: ignore[arg-type]
