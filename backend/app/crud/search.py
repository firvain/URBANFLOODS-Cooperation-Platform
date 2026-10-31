"""Site search across blog posts and forum threads (read-only).

Matching, per content type: the generated ``fts`` vector against ``plainto_tsquery('english')``
(stems: "flooding" finds "floods"), OR a title substring (``ILIKE``, wildcards escaped), OR a
trigram typo match on the title: every query word of 3+ characters (at most ``MAX_FUZZY_WORDS``)
must satisfy ``word <<% title`` (``strict_word_similarity`` >= pg_trgm's
``strict_word_similarity_threshold``, default 0.5: "resilence" finds "Resilience"). Matching word
by word keeps a multi-word query from fuzzy-matching a title that holds only one of its words.
The substring and trigram tests both use the ``gin_trgm_ops`` title index.

Rank: ``ts_rank(fts, query)`` plus ``TITLE_BONUS`` for a title substring hit (so a title hit
always outranks a body-only hit), else ``FUZZY_WEIGHT * strict_word_similarity`` for a trigram-only
title hit (a guess, so it stays below exact body hits). Ties: newest published first.

``type="all"`` runs both branches as one ``UNION ALL`` of normalised ``(type, id, rank,
published_at)`` rows, ordered and paginated in SQL; the total is counted over the same union as a
subquery. Only the page's rows are then loaded, one query per type with author and category
joined, and ``ts_headline`` is computed for those rows only. Every branch goes through
:func:`app.crud.visibility.visible_filter`.

Replies and comments are not searched: they have no title to rank on and are short fragments
that only make sense in context; they surface through their thread or post.

Snippets: ``ts_headline`` marks matches with private-use sentinel characters (stripped from the
body first); the result is HTML-escaped and the sentinels become ``<mark>``/``</mark>``, so the
only markup in a snippet is ``mark``.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import (
    ColumnElement,
    Float,
    String,
    and_,
    case,
    cast,
    func,
    literal,
    literal_column,
    select,
    union_all,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, load_only

from app.crud.visibility import visible_filter
from app.db.models import Category, Post, Thread, User

SearchType = Literal["all", "posts", "threads"]
HitType = Literal["post", "thread"]

FTS_CONFIG = literal_column("'english'::regconfig")
TITLE_BONUS = 1.0
FUZZY_WEIGHT = 0.1
FUZZY_MIN_WORD_LENGTH = 3
MAX_FUZZY_WORDS = 8
MARK_START = ""
MARK_STOP = ""
HEADLINE_OPTIONS = (
    f'MaxFragments=2, MaxWords=18, MinWords=8, StartSel="{MARK_START}", StopSel="{MARK_STOP}"'
)

_MODELS: dict[HitType, Any] = {"post": Post, "thread": Thread}
_BRANCHES: dict[SearchType, tuple[HitType, ...]] = {
    "all": ("post", "thread"),
    "posts": ("post",),
    "threads": ("thread",),
}


@dataclass(frozen=True)
class SearchResult:
    """One hit, shaped like ``schemas.search.SearchHit``."""

    type: HitType
    id: int
    slug: str
    title: str
    snippet: str
    locale: str
    author: User | None
    category: Category
    published_at: datetime | None
    rank: float


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _fuzzy_words(q: str) -> list[str]:
    """The words of ``q`` the trigram fallback must all find (short words are ignored unless
    there is nothing else)."""
    words = re.findall(r"\w+", q)
    long_words = [word for word in words if len(word) >= FUZZY_MIN_WORD_LENGTH]
    return (long_words or words)[:MAX_FUZZY_WORDS]


def _fuzzy_title_hit(model: Any, q: str) -> ColumnElement[bool]:
    words = _fuzzy_words(q)
    if not words:
        return literal(False)
    return and_(*(literal(word, String).bool_op("<<%")(model.title) for word in words))


def _tsquery(q: str) -> ColumnElement[Any]:
    return func.plainto_tsquery(FTS_CONFIG, q)


def _branch(kind: HitType, *, q: str, user: User | None, locale: str | None) -> Any:
    """``SELECT type, id, rank, published_at`` of the ``kind`` rows matching ``q``."""
    model = _MODELS[kind]
    tsquery = _tsquery(q)
    title_hit = model.title.ilike(f"%{_escape_like(q)}%", escape="\\")
    fuzzy_hit = _fuzzy_title_hit(model, q)
    rank = cast(func.ts_rank(model.fts, tsquery), Float) + case(
        (title_hit, literal(TITLE_BONUS, Float)),
        (fuzzy_hit, cast(func.strict_word_similarity(q, model.title), Float) * FUZZY_WEIGHT),
        else_=literal(0.0, Float),
    )
    conditions: list[ColumnElement[bool]] = [
        visible_filter(model, user),
        model.fts.bool_op("@@")(tsquery) | title_hit | fuzzy_hit,
    ]
    if locale:
        conditions.append(model.locale == locale)
    return select(
        literal_column(f"'{kind}'", String).label("type"),
        model.id.label("id"),
        rank.label("rank"),
        model.published_at.label("published_at"),
    ).where(*conditions)


def _snippet(raw: str | None) -> str:
    escaped = html.escape(raw or "")
    return escaped.replace(MARK_START, "<mark>").replace(MARK_STOP, "</mark>")


async def _load(
    db: AsyncSession, kind: HitType, *, ids: list[int], q: str
) -> dict[int, tuple[Any, str]]:
    """``{id: (row, snippet)}`` for the page's ``kind`` rows, author and category joined."""
    if not ids:
        return {}
    model = _MODELS[kind]
    body = func.translate(model.body_text, MARK_START + MARK_STOP, "")
    headline = func.ts_headline(FTS_CONFIG, body, _tsquery(q), HEADLINE_OPTIONS)
    stmt = (
        select(model, headline)
        .where(model.id.in_(ids))
        .options(
            load_only(model.id, model.slug, model.title, model.locale, model.published_at),
            joinedload(model.author),
            joinedload(model.category),
        )
    )
    rows = (await db.execute(stmt)).all()
    return {row.id: (row, _snippet(snippet)) for row, snippet in rows}


async def search(
    db: AsyncSession,
    *,
    q: str,
    user: User | None,
    type_: SearchType = "all",
    locale: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[int, list[SearchResult]]:
    """``(total, hits)`` for ``q`` (already stripped, non-empty) visible to ``user``, best first."""
    branches = [_branch(kind, q=q, user=user, locale=locale) for kind in _BRANCHES[type_]]
    hits = (branches[0] if len(branches) == 1 else union_all(*branches)).subquery("hits")

    total = (await db.execute(select(func.count()).select_from(hits))).scalar_one()
    page_stmt = (
        select(hits.c.type, hits.c.id, hits.c.rank)
        .order_by(
            hits.c.rank.desc(),
            hits.c.published_at.desc().nulls_last(),
            hits.c.type,
            hits.c.id.desc(),
        )
        .offset(skip)
        .limit(limit)
    )
    page = (await db.execute(page_stmt)).all()

    loaded = {
        kind: await _load(db, kind, ids=[row.id for row in page if row.type == kind], q=q)
        for kind in _BRANCHES[type_]
    }
    results: list[SearchResult] = []
    for row in page:
        obj, snippet = loaded[row.type][row.id]
        results.append(
            SearchResult(
                type=row.type,
                id=obj.id,
                slug=obj.slug,
                title=obj.title,
                snippet=snippet,
                locale=obj.locale,
                author=obj.author,
                category=obj.category,
                published_at=obj.published_at,
                rank=float(row.rank),
            )
        )
    return total, results
