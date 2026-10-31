"""Read-only proxy to the KNOWBASE public REST API, with TTL caches and stale-on-error.

The KNOWBASE is a separate, delivered application: this module only ever sends ``GET`` requests
to an allow-list of its public routes. One ``KnowbaseClient`` lives on ``app.state.knowbase``
(created and closed in the app lifespan).

Caching: one ``TTLCache`` per class (lists/search, details, lookups). Every successful response
is also copied into a per-class "stale" store (LRU, no TTL, same maxsize) that is consulted only
when the upstream fails (timeout, connection error, 5xx, invalid JSON). A per-key
``asyncio.Lock`` makes concurrent misses for the same key share one upstream request.

State is in memory, so it assumes a single worker process (see docs/PLAN.md).
"""

from __future__ import annotations

import asyncio
import time
import weakref
from collections import OrderedDict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import quote

import httpx
import structlog
from cachetools import TTLCache

from app.core.config import settings

USER_AGENT = "urbanfloods-cooperation-platform/0.1"

LIST_MAXSIZE = 512
DETAIL_MAXSIZE = 2048
LOOKUP_MAXSIZE = 64
LOOKUP_TTL_SECONDS = 86400
RESOLVE_CONCURRENCY = 5
# Failures remembered per key so callers queued behind a failing fetch do not each retry it.
FAILURE_MAXSIZE = 1024
FAILURE_TTL_SECONDS = 60

# Allow-listed lookups and the cross filters each one accepts upstream (a lookup never filters by
# its own dimension).
DOCUMENT_LOOKUPS: dict[str, frozenset[str]] = {
    "countries": frozenset({"level_id", "subject_id", "keyword_ids"}),
    "levels": frozenset({"country", "subject_id", "keyword_ids"}),
    "subjects": frozenset({"country", "level_id", "keyword_ids"}),
    "keywords": frozenset({"country", "level_id", "subject_id"}),
}
MEASURE_LOOKUPS: dict[str, frozenset[str]] = {
    "categories": frozenset({"level_of_application_ids", "scale_ids", "keyword_ids"}),
    "levels-of-application": frozenset({"category_id", "scale_ids", "keyword_ids"}),
    "scales": frozenset({"category_id", "level_of_application_ids", "keyword_ids"}),
    "keywords": frozenset({"category_id", "level_of_application_ids", "scale_ids"}),
}

KbType = Literal["document", "measure"]
CacheStatus = Literal["hit", "miss", "stale"]
# A query value: a scalar, or a tuple for a repeated parameter (``keyword_ids=1&keyword_ids=3``).
QueryValue = str | int | tuple[str | int, ...]
CacheKey = tuple[str, tuple[tuple[str, QueryValue], ...]]

log = structlog.get_logger(__name__)


def _clock() -> float:
    """Time source for the TTL caches (patched in tests)."""
    return time.monotonic()


class KnowbaseNotFound(Exception):
    """The upstream answered 404."""


class KnowbaseError(Exception):
    """The upstream answered another 4xx (a request the proxy should not have sent)."""

    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(f"KNOWBASE answered HTTP {status}")


class KnowbaseUnavailable(Exception):
    """The upstream is down (timeout, network error, 5xx, bad body) and nothing is cached."""


class _CacheClass(StrEnum):
    LISTS = "lists"
    DETAILS = "details"
    LOOKUPS = "lookups"


class _UpstreamDown(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True, slots=True)
class KnowbaseResult:
    """Upstream JSON (never mutate it: it is the cached object) and where it came from."""

    data: Any
    cache: CacheStatus


class _StaleStore:
    """Last good value per key, without expiry; least recently stored is evicted first."""

    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self._data: OrderedDict[CacheKey, Any] = OrderedDict()

    def get(self, key: CacheKey) -> Any | None:
        return self._data.get(key)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def put(self, key: CacheKey, value: Any) -> None:
        self._data[key] = value
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)


def _query_items(params: Mapping[str, Any] | None) -> tuple[tuple[str, QueryValue], ...]:
    """Normalised query: ``None`` dropped, lists made tuples, sorted by name (the cache key)."""
    items: list[tuple[str, QueryValue]] = []
    for name, value in (params or {}).items():
        if value is None:
            continue
        if isinstance(value, list | tuple):
            if not value:
                continue
            items.append((name, tuple(value)))
        else:
            items.append((name, value))
    return tuple(sorted(items, key=lambda item: item[0]))


def _httpx_params(query: tuple[tuple[str, QueryValue], ...]) -> list[tuple[str, str | int]]:
    """Expand tuples into repeated parameters, as the upstream (FastAPI) expects."""
    pairs: list[tuple[str, str | int]] = []
    for name, value in query:
        if isinstance(value, tuple):
            pairs.extend((name, item) for item in value)
        else:
            pairs.append((name, value))
    return pairs


def _utcnow() -> datetime:
    return datetime.now(UTC)


def measure_photo_url(photo_filename: str | None) -> str | None:
    """Absolute public URL of a measure photo, or None."""
    if not photo_filename:
        return None
    base = settings.KNOWBASE_PUBLIC_URL.rstrip("/")
    return f"{base}/static/measures/photos/{quote(photo_filename)}"


def with_photo_url(measure: Any) -> Any:
    """A shallow copy of a measure dict with ``photo_url`` added (cached value left intact)."""
    if not isinstance(measure, dict):
        return measure
    return {**measure, "photo_url": measure_photo_url(measure.get("photo_filename"))}


def _titles(kb_type: KbType, item: Any) -> dict[str, str | None] | None:
    if not isinstance(item, dict):
        return None
    if kb_type == "document":
        return {
            "title_en": item.get("name_of_document_en"),
            "title_local": item.get("name_of_document_local"),
        }
    return {"title_en": item.get("title_en"), "title_local": item.get("title_local")}


class KnowbaseClient:
    """Allow-listed, cached ``GET`` access to the KNOWBASE API."""

    def __init__(self, *, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._http = httpx.AsyncClient(
            base_url=f"{settings.KNOWBASE_BASE_URL.rstrip('/')}/api/v1",
            timeout=settings.KNOWBASE_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT},
            transport=transport,
        )
        # The lambda looks ``_clock`` up on every call, so tests can patch it.
        timer = lambda: _clock()  # noqa: E731
        self._caches: dict[_CacheClass, TTLCache[CacheKey, Any]] = {
            _CacheClass.LISTS: TTLCache(LIST_MAXSIZE, settings.KNOWBASE_CACHE_TTL_LIST, timer),
            _CacheClass.DETAILS: TTLCache(
                DETAIL_MAXSIZE, settings.KNOWBASE_CACHE_TTL_DETAIL, timer
            ),
            _CacheClass.LOOKUPS: TTLCache(LOOKUP_MAXSIZE, LOOKUP_TTL_SECONDS, timer),
        }
        self._stale: dict[_CacheClass, _StaleStore] = {
            _CacheClass.LISTS: _StaleStore(LIST_MAXSIZE),
            _CacheClass.DETAILS: _StaleStore(DETAIL_MAXSIZE),
            _CacheClass.LOOKUPS: _StaleStore(LOOKUP_MAXSIZE),
        }
        # Count of finished upstream fetches; each key's last failure is stored with its number
        # so that callers queued behind it share it instead of retrying (see ``_get``).
        self._completed = 0
        self._failures: TTLCache[CacheKey, tuple[int, str]] = TTLCache(
            FAILURE_MAXSIZE, FAILURE_TTL_SECONDS, timer
        )
        # Held only while a fetch is in progress; dropped automatically afterwards.
        self._locks: weakref.WeakValueDictionary[CacheKey, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )
        self._last_success_at: datetime | None = None
        self._last_error_at: datetime | None = None
        self._last_error: str | None = None

    # --- lifecycle ----------------------------------------------------------------------------

    @property
    def is_closed(self) -> bool:
        return self._http.is_closed

    async def aclose(self) -> None:
        await self._http.aclose()

    # --- allow-listed routes ------------------------------------------------------------------

    async def list_documents(self, params: Mapping[str, Any]) -> KnowbaseResult:
        return await self._get("documents/", params, _CacheClass.LISTS)

    async def get_document(self, document_id: int) -> KnowbaseResult:
        return await self._get(f"documents/{int(document_id)}", None, _CacheClass.DETAILS)

    async def list_measures(self, params: Mapping[str, Any]) -> KnowbaseResult:
        return await self._get("measures/", params, _CacheClass.LISTS)

    async def get_measure(self, measure_id: int) -> KnowbaseResult:
        return await self._get(f"measures/{int(measure_id)}", None, _CacheClass.DETAILS)

    async def get_levels(self) -> KnowbaseResult:
        return await self._get("levels/", None, _CacheClass.LISTS)

    async def get_subjects(self) -> KnowbaseResult:
        return await self._get("subjects/", None, _CacheClass.LISTS)

    async def get_keyword_labels(self) -> KnowbaseResult:
        return await self._get("keyword-labels/", None, _CacheClass.LISTS)

    async def get_document_lookup(self, name: str, params: Mapping[str, Any]) -> KnowbaseResult:
        if name not in DOCUMENT_LOOKUPS:
            raise ValueError(f"unknown document lookup {name!r}")
        return await self._get(f"lookups/{name}", params, _CacheClass.LOOKUPS)

    async def get_measure_lookup(self, name: str, params: Mapping[str, Any]) -> KnowbaseResult:
        if name not in MEASURE_LOOKUPS:
            raise ValueError(f"unknown measure lookup {name!r}")
        return await self._get(f"measures/lookups/{name}", params, _CacheClass.LOOKUPS)

    # --- link titles --------------------------------------------------------------------------

    async def resolve_links(
        self, items: Iterable[tuple[str, int]]
    ) -> dict[tuple[str, int], dict[str, str | None] | None]:
        """Titles of KNOWBASE items (for ``knowbase_links``), ``None`` for items that do not
        exist. Uses the detail cache; at most ``RESOLVE_CONCURRENCY`` requests at a time.
        ``KnowbaseUnavailable``/``KnowbaseError`` propagate: "down" is not "missing"."""
        unique: list[tuple[str, int]] = []
        for kb_type, kb_id in items:
            if kb_type not in ("document", "measure"):
                raise ValueError(f"unknown KNOWBASE type {kb_type!r}")
            key = (kb_type, int(kb_id))
            if key not in unique:
                unique.append(key)

        semaphore = asyncio.Semaphore(RESOLVE_CONCURRENCY)

        async def resolve(kb_type: KbType, kb_id: int) -> dict[str, str | None] | None:
            async with semaphore:
                try:
                    if kb_type == "document":
                        result = await self.get_document(kb_id)
                    else:
                        result = await self.get_measure(kb_id)
                except KnowbaseNotFound:
                    return None
            return _titles(kb_type, result.data)

        titles = await asyncio.gather(
            *(resolve(kb_type, kb_id) for kb_type, kb_id in unique)  # type: ignore[arg-type]
        )
        return dict(zip(unique, titles, strict=True))

    # --- status and admin ---------------------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """Health from the last calls (no request). ``reachable`` is false only while the most
        recent upstream call failed."""
        reachable = self._last_error_at is None or (
            self._last_success_at is not None and self._last_success_at >= self._last_error_at
        )
        counts: dict[str, int] = {}
        for cache_class, cache in self._caches.items():
            cache.expire()
            counts[cache_class.value] = len(cache)
        counts["stale"] = sum(len(store) for store in self._stale.values())
        return {
            "reachable": reachable,
            "last_success_at": self._last_success_at,
            "last_error_at": self._last_error_at,
            "last_error": self._last_error,
            "cache": counts,
        }

    def clear_cache(self) -> None:
        """Empty every cache, stale copies included."""
        for cache in self._caches.values():
            cache.clear()
        for store in self._stale.values():
            store.clear()
        self._failures.clear()

    # --- core ---------------------------------------------------------------------------------

    def _lock(self, key: CacheKey) -> asyncio.Lock:
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def _get(
        self, path: str, params: Mapping[str, Any] | None, cache_class: _CacheClass
    ) -> KnowbaseResult:
        query = _query_items(params)
        key: CacheKey = (path, query)
        cache = self._caches[cache_class]

        value = cache.get(key)
        if value is not None:
            return KnowbaseResult(value, "hit")

        ticket = self._completed
        lock = self._lock(key)
        async with lock:
            value = cache.get(key)
            if value is not None:
                return KnowbaseResult(value, "hit")
            failure = self._failures.get(key)
            if failure is not None and failure[0] > ticket:
                # The fetch we queued behind just failed: share its outcome.
                return self._fallback(key, cache_class, failure[1])
            try:
                value = await self._fetch(path, query)
            except _UpstreamDown as exc:
                self._completed += 1
                self._failures[key] = (self._completed, exc.reason)
                self._record_error(exc.reason)
                log.warning("knowbase.upstream_failed", path=path, reason=exc.reason)
                return self._fallback(key, cache_class, exc.reason)
            self._completed += 1
            self._failures.pop(key, None)
            cache[key] = value
            self._stale[cache_class].put(key, value)
            return KnowbaseResult(value, "miss")

    def _fallback(self, key: CacheKey, cache_class: _CacheClass, reason: str) -> KnowbaseResult:
        """The last good value for ``key`` flagged stale, or ``KnowbaseUnavailable``."""
        stale = self._stale[cache_class].get(key)
        if stale is None:
            raise KnowbaseUnavailable(reason)
        return KnowbaseResult(stale, "stale")

    async def _fetch(self, path: str, query: tuple[tuple[str, QueryValue], ...]) -> Any:
        """One upstream GET. Returns parsed JSON; raises ``_UpstreamDown``, ``KnowbaseNotFound``
        or ``KnowbaseError``."""
        try:
            response = await self._http.get(path, params=_httpx_params(query))
        except httpx.TimeoutException as exc:
            raise _UpstreamDown("timeout") from exc
        except httpx.HTTPError as exc:
            raise _UpstreamDown("connection_error") from exc

        if response.status_code >= 500:
            raise _UpstreamDown(f"http_{response.status_code}")
        if response.status_code == 404:
            self._record_success()
            raise KnowbaseNotFound(path)
        if response.status_code >= 400 or response.status_code < 200:
            self._record_success()
            log.warning("knowbase.upstream_rejected", path=path, status=response.status_code)
            raise KnowbaseError(response.status_code)
        try:
            value = response.json()
        except ValueError as exc:
            raise _UpstreamDown("invalid_json") from exc
        if value is None:
            raise _UpstreamDown("invalid_json")
        self._record_success()
        return value

    def _record_success(self) -> None:
        self._last_success_at = _utcnow()

    def _record_error(self, reason: str) -> None:
        self._last_error_at = _utcnow()
        self._last_error = reason
