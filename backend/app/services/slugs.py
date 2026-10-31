"""URL slugs: transliterating ``slugify_title`` and collision-free ``unique_slug``.

Titles in any script (Greek, Cyrillic, accented Latin) are transliterated to ASCII. Uniqueness is
checked through a caller-supplied ``exists`` predicate, so this module never touches the database.
"""

from __future__ import annotations

import inspect
import secrets
import string
from collections.abc import Awaitable, Callable, Iterator

from slugify import slugify

FALLBACK_SLUG = "item"
MAX_SLUG_LENGTH = 220
TITLE_SLUG_LENGTH = 80
RANDOM_SUFFIX_LENGTH = 6
RANDOM_TRIES = 10

_SUFFIX_ALPHABET = string.ascii_lowercase + string.digits


def slugify_title(title: str, *, max_length: int = TITLE_SLUG_LENGTH) -> str:
    """ASCII slug of ``title``, cut on a word boundary to ``max_length``; ``"item"`` if empty."""
    slug = slugify(title, lowercase=True, max_length=max_length, word_boundary=True)
    return slug or FALLBACK_SLUG


def _truncate(base: str, limit: int) -> str:
    """``base`` cut to ``limit`` characters, on a ``-`` boundary when one is available."""
    if len(base) <= limit:
        return base
    cut = base[:limit]
    if base[limit] != "-" and "-" in cut:
        cut = cut.rsplit("-", 1)[0]
    return cut.strip("-") or base[:limit]


def _with_suffix(base: str, suffix: str) -> str:
    return f"{_truncate(base, MAX_SLUG_LENGTH - len(suffix) - 1)}-{suffix}"


def _candidates(base: str, max_attempts: int) -> Iterator[str]:
    """``base``, ``base-2`` … ``base-<max_attempts>``, then a few random 6-character suffixes."""
    base = base.strip("-") or FALLBACK_SLUG
    yield _truncate(base, MAX_SLUG_LENGTH)
    for n in range(2, max_attempts + 1):
        yield _with_suffix(base, str(n))
    for _ in range(RANDOM_TRIES):
        suffix = "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(RANDOM_SUFFIX_LENGTH))
        yield _with_suffix(base, suffix)


def _exhausted(base: str) -> RuntimeError:
    return RuntimeError(f"could not find a free slug for {base!r}")


def unique_slug(base: str, exists: Callable[[str], bool], *, max_attempts: int = 50) -> str:
    """First slug derived from ``base`` for which ``exists`` is false (see :func:`_candidates`).
    Never longer than 220 characters.

    :raises RuntimeError: when every candidate is taken.
    """
    for candidate in _candidates(base, max_attempts):
        taken = exists(candidate)
        if inspect.isawaitable(taken):
            if inspect.iscoroutine(taken):
                taken.close()
            raise TypeError("exists is async: use unique_slug_async")
        if not taken:
            return candidate
    raise _exhausted(base)


async def unique_slug_async(
    base: str,
    exists: Callable[[str], Awaitable[bool]] | Callable[[str], bool],
    *,
    max_attempts: int = 50,
) -> str:
    """:func:`unique_slug` for an ``exists`` predicate that may be async (e.g. a DB query)."""
    for candidate in _candidates(base, max_attempts):
        taken = exists(candidate)
        if inspect.isawaitable(taken):
            taken = await taken
        if not taken:
            return candidate
    raise _exhausted(base)
