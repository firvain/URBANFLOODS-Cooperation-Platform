"""KNOWBASE proxy: service (cache, stale-on-error, status, link resolution) and ``/knowbase/*``
endpoints. Upstream is always mocked with respx; the live KNOWBASE is never called."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
import respx

from app.core.config import settings
from app.services import knowbase as kb_module
from app.services.knowbase import (
    KnowbaseClient,
    KnowbaseError,
    KnowbaseNotFound,
    KnowbaseUnavailable,
)

KB_BASE = "https://knowbase.test"
KB_API = f"{KB_BASE}/api/v1"
KB_PUBLIC = "https://kb-public.test"
PREFIX = "/api/v1/knowbase"

DOCUMENT = {
    "id": 7,
    "name_of_document_en": "Flood Risk Act",
    "name_of_document_local": "Νόμος για τις πλημμύρες",
    "country": "GR",
    "level": {"id": 1, "code": "NAT", "label": "National"},
    "subject": {"id": 2, "code": "LAW", "label": "Law"},
    "no": 4414,
    "official_gazzette_ref": None,
    "extended_description_en": "Text",
    "extended_description_local": None,
    "web_links": "https://example.org",
    "keywords": "flood, risk",
    "comments": None,
    "keyword_labels": [{"id": 1, "label": "Planning"}],
    "all_keywords": ["Planning", "flood"],
    "future_upstream_field": {"kept": True},
}

MEASURE = {
    "id": 3,
    "measure_code": 101,
    "title_en": "Retention basin",
    "title_local": "Λεκάνη ανάσχεσης",
    "photo_filename": "s 01.jpg",
    "category": {"id": 1, "code": "STR", "label_en": "Structural", "label_local": None},
    "levels_of_application": [],
    "scales": [],
    "keywords": [],
    "description_en": "Basin",
    "all_keywords": [],
}


class Clock:
    """A controllable time source for the TTL caches."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture(autouse=True)
def kb_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_BASE_URL", KB_BASE)
    monkeypatch.setattr(settings, "KNOWBASE_PUBLIC_URL", KB_PUBLIC)


@pytest.fixture
def clock(monkeypatch) -> Clock:
    fake = Clock()
    monkeypatch.setattr(kb_module, "_clock", fake)
    return fake


@pytest.fixture(autouse=True)
def upstream(kb_settings) -> Iterator[respx.MockRouter]:
    """Every request to the (test) KNOWBASE goes through this router; anything unmocked fails."""
    with respx.mock(base_url=KB_API, assert_all_called=False, assert_all_mocked=True) as router:
        yield router


@pytest.fixture
async def kb(clock) -> AsyncIterator[KnowbaseClient]:
    client = KnowbaseClient()
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def api(clock, client: httpx.AsyncClient) -> httpx.AsyncClient:
    """The app client; the lifespan's KnowbaseClient was built after ``clock`` was patched."""
    return client


def _params(route: respx.Route) -> list[tuple[str, str]]:
    return sorted(route.calls.last.request.url.params.multi_items())


# --- list pass-through and validation ---------------------------------------------------------


async def test_documents_list_forwards_params_exactly(api, upstream) -> None:
    body = {"total": 1, "items": [DOCUMENT]}
    route = upstream.get("/documents/").respond(json=body)

    r = await api.get(
        f"{PREFIX}/documents/",
        params=[
            ("q", "flood"),
            ("country", "GR"),
            ("level_id", "1"),
            ("subject_id", "2"),
            ("keyword_ids", "1"),
            ("keyword_ids", "3"),
            ("keyword_search", "plan"),
            ("skip", "20"),
            ("limit", "20"),
        ],
    )

    assert r.status_code == 200, r.text
    assert r.json() == body
    assert r.headers["X-Knowbase-Cache"] == "miss"
    request = route.calls.last.request
    assert request.url.path == "/api/v1/documents/"
    assert request.method == "GET"
    assert request.headers["User-Agent"] == "urbanfloods-cooperation-platform/0.1"
    assert _params(route) == sorted(
        [
            ("q", "flood"),
            ("country", "GR"),
            ("level_id", "1"),
            ("subject_id", "2"),
            ("keyword_ids", "1"),
            ("keyword_ids", "3"),
            ("keyword_search", "plan"),
            ("skip", "20"),
            ("limit", "20"),
        ]
    )


async def test_documents_list_defaults_forwarded(api, upstream) -> None:
    route = upstream.get("/documents/").respond(json={"total": 0, "items": []})
    r = await api.get(f"{PREFIX}/documents/")
    assert r.status_code == 200
    assert _params(route) == [("limit", "100"), ("skip", "0")]


async def test_measures_list_forwards_repeated_ids(api, upstream) -> None:
    route = upstream.get("/measures/").respond(json={"total": 0, "items": []})
    r = await api.get(
        f"{PREFIX}/measures/",
        params=[
            ("category_id", "3"),
            ("level_of_application_ids", "1"),
            ("level_of_application_ids", "2"),
            ("scale_ids", "4"),
            ("keyword_ids", "9"),
            ("keyword_ids", "12"),
            ("q", "basin"),
        ],
    )
    assert r.status_code == 200, r.text
    assert _params(route) == sorted(
        [
            ("category_id", "3"),
            ("level_of_application_ids", "1"),
            ("level_of_application_ids", "2"),
            ("scale_ids", "4"),
            ("keyword_ids", "9"),
            ("keyword_ids", "12"),
            ("q", "basin"),
            ("skip", "0"),
            ("limit", "100"),
        ]
    )


@pytest.mark.parametrize("path", ["documents/", "measures/"])
async def test_limit_above_200_is_rejected(api, upstream, path) -> None:
    route = upstream.get(f"/{path}").respond(json={"total": 0, "items": []})
    r = await api.get(f"{PREFIX}/{path}", params={"limit": 201})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "validation.failed"
    assert r.json()["detail"]["fields"] == {"query.limit": "less_than_equal"}
    assert not route.called

    ok = await api.get(f"{PREFIX}/{path}", params={"limit": 200})
    assert ok.status_code == 200


@pytest.mark.parametrize(
    "params",
    [
        {"foo": "bar"},
        {"q": "x"},  # shorter than upstream's min_length 2
        {"skip": "-1"},
        {"category_id": "1"},  # a measures filter is unknown on documents
    ],
)
async def test_invalid_or_unknown_params_are_rejected(api, upstream, params) -> None:
    route = upstream.get("/documents/").respond(json={"total": 0, "items": []})
    r = await api.get(f"{PREFIX}/documents/", params=params)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "validation.failed"
    assert not route.called


# --- cache ------------------------------------------------------------------------------------


async def test_second_identical_call_is_a_cache_hit(api, upstream) -> None:
    route = upstream.get("/documents/").respond(json={"total": 0, "items": []})
    first = await api.get(f"{PREFIX}/documents/", params={"country": "GR"})
    second = await api.get(f"{PREFIX}/documents/", params={"country": "GR"})
    assert first.headers["X-Knowbase-Cache"] == "miss"
    assert second.headers["X-Knowbase-Cache"] == "hit"
    assert second.json() == first.json()
    assert route.call_count == 1

    other = await api.get(f"{PREFIX}/documents/", params={"country": "IT"})
    assert other.headers["X-Knowbase-Cache"] == "miss"
    assert route.call_count == 2


async def test_detail_is_cached_separately_from_list(api, upstream) -> None:
    list_route = upstream.get("/documents/").respond(json={"total": 1, "items": [DOCUMENT]})
    detail_route = upstream.get("/documents/7").respond(json=DOCUMENT)

    await api.get(f"{PREFIX}/documents/")
    first = await api.get(f"{PREFIX}/documents/7")
    second = await api.get(f"{PREFIX}/documents/7")

    assert first.status_code == 200
    assert first.json() == DOCUMENT  # unknown upstream fields pass through
    assert first.headers["X-Knowbase-Cache"] == "miss"
    assert second.headers["X-Knowbase-Cache"] == "hit"
    assert list_route.call_count == 1
    assert detail_route.call_count == 1
    status = (await api.get(f"{PREFIX}/status")).json()
    assert status["cache"]["lists"] == 1
    assert status["cache"]["details"] == 1


async def test_list_ttl_expiry_refetches(monkeypatch, clock, upstream) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_CACHE_TTL_LIST", 10)
    route = upstream.get("/levels/").respond(json=[{"id": 1}])
    client = KnowbaseClient()
    try:
        assert (await client.get_levels()).cache == "miss"
        clock.advance(9)
        assert (await client.get_levels()).cache == "hit"
        clock.advance(2)
        assert (await client.get_levels()).cache == "miss"
        assert route.call_count == 2
    finally:
        await client.aclose()


async def test_detail_ttl_is_separate(monkeypatch, clock, upstream) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_CACHE_TTL_LIST", 10)
    monkeypatch.setattr(settings, "KNOWBASE_CACHE_TTL_DETAIL", 100)
    route = upstream.get("/measures/3").respond(json=MEASURE)
    client = KnowbaseClient()
    try:
        await client.get_measure(3)
        clock.advance(50)
        assert (await client.get_measure(3)).cache == "hit"
        clock.advance(51)
        assert (await client.get_measure(3)).cache == "miss"
        assert route.call_count == 2
    finally:
        await client.aclose()


async def test_concurrent_identical_calls_hit_upstream_once(kb, upstream) -> None:
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        return httpx.Response(200, json=[{"id": 1}])

    route = upstream.get("/subjects/").mock(side_effect=slow)
    results = await asyncio.gather(*(kb.get_subjects() for _ in range(5)))
    assert route.call_count == 1
    assert sorted(r.cache for r in results) == ["hit", "hit", "hit", "hit", "miss"]


# --- stale-on-error and upstream errors -------------------------------------------------------


async def test_concurrent_waiters_share_an_upstream_failure(kb, upstream) -> None:
    async def slow_timeout(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.02)
        raise httpx.ReadTimeout("slow")

    route = upstream.get("/subjects/").mock(side_effect=slow_timeout)
    results = await asyncio.gather(*(kb.get_subjects() for _ in range(4)), return_exceptions=True)
    assert all(isinstance(r, KnowbaseUnavailable) for r in results)
    assert route.call_count == 1  # queued callers do not each wait out a timeout

    route.mock(side_effect=None, return_value=httpx.Response(200, json=[]))
    assert (await kb.get_subjects()).cache == "miss"  # a later call retries


async def test_timeout_with_warm_cache_serves_stale(api, upstream, clock) -> None:
    route = upstream.get("/documents/").mock(
        side_effect=[
            httpx.Response(200, json={"total": 1, "items": [DOCUMENT]}),
            httpx.TimeoutException("slow"),
        ]
    )
    warm = await api.get(f"{PREFIX}/documents/")
    assert warm.headers["X-Knowbase-Cache"] == "miss"

    clock.advance(settings.KNOWBASE_CACHE_TTL_LIST + 1)
    stale = await api.get(f"{PREFIX}/documents/")

    assert stale.status_code == 200
    assert stale.headers["X-Knowbase-Cache"] == "stale"
    assert stale.json() == warm.json()
    assert route.call_count == 2


async def test_5xx_with_warm_cache_serves_stale(kb, upstream, clock) -> None:
    upstream.get("/measures/3").mock(
        side_effect=[httpx.Response(200, json=MEASURE), httpx.Response(502)]
    )
    await kb.get_measure(3)
    clock.advance(settings.KNOWBASE_CACHE_TTL_DETAIL + 1)
    result = await kb.get_measure(3)
    assert result.cache == "stale"
    assert result.data["id"] == 3


async def test_500_with_cold_cache_is_unavailable(api, upstream) -> None:
    upstream.get("/documents/").respond(status_code=500)
    r = await api.get(f"{PREFIX}/documents/")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "knowbase.unavailable"


@pytest.mark.parametrize(
    "effect",
    [httpx.ConnectError("down"), httpx.ReadTimeout("slow")],
    ids=["connect", "timeout"],
)
async def test_network_error_with_cold_cache_is_unavailable(kb, upstream, effect) -> None:
    upstream.get("/keyword-labels/").mock(side_effect=effect)
    with pytest.raises(KnowbaseUnavailable):
        await kb.get_keyword_labels()


async def test_invalid_json_is_treated_as_unavailable(api, upstream) -> None:
    upstream.get("/levels/").respond(200, text="<html>maintenance</html>")
    r = await api.get(f"{PREFIX}/levels/")
    assert r.status_code == 503
    assert r.json()["detail"]["code"] == "knowbase.unavailable"


@pytest.mark.parametrize("kind", ["documents", "measures"])
async def test_upstream_404_is_not_found(api, upstream, kind) -> None:
    upstream.get(f"/{kind}/999").respond(404, json={"detail": "Document not found"})
    r = await api.get(f"{PREFIX}/{kind}/999")
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "knowbase.not_found"


async def test_upstream_other_4xx_is_upstream_error(api, upstream, kb) -> None:
    upstream.get("/documents/").respond(422, json={"detail": []})
    r = await api.get(f"{PREFIX}/documents/")
    assert r.status_code == 502
    assert r.json()["detail"]["code"] == "knowbase.upstream_error"

    with pytest.raises(KnowbaseError) as exc_info:
        await kb.list_documents({})
    assert exc_info.value.status == 422


async def test_404_is_not_served_from_stale(kb, upstream, clock) -> None:
    upstream.get("/documents/7").mock(
        side_effect=[httpx.Response(200, json=DOCUMENT), httpx.Response(404)]
    )
    await kb.get_document(7)
    clock.advance(settings.KNOWBASE_CACHE_TTL_DETAIL + 1)
    with pytest.raises(KnowbaseNotFound):
        await kb.get_document(7)


async def test_stale_store_is_bounded_lru(monkeypatch, clock, upstream) -> None:
    monkeypatch.setattr(kb_module, "DETAIL_MAXSIZE", 2)
    for doc_id in (1, 2, 3):
        upstream.get(f"/documents/{doc_id}").respond(json={"id": doc_id})
    client = KnowbaseClient()
    try:
        for doc_id in (1, 2, 3):
            await client.get_document(doc_id)
        assert client.status()["cache"]["stale"] == 2
    finally:
        await client.aclose()


# --- lookups and reference lists --------------------------------------------------------------


@pytest.mark.parametrize("path", ["levels/", "subjects/", "keyword-labels/"])
async def test_reference_lists_pass_through(api, upstream, path) -> None:
    body = [{"id": 1, "code": "X", "label": "Y"}]
    route = upstream.get(f"/{path}").respond(json=body)
    r = await api.get(f"{PREFIX}/{path}")
    assert r.status_code == 200
    assert r.json() == body
    assert route.called


@pytest.mark.parametrize(
    ("name", "param"),
    [
        ("countries", ("subject_id", "2")),
        ("levels", ("country", "GR")),
        ("subjects", ("level_id", "1")),
        ("keywords", ("subject_id", "2")),
    ],
)
async def test_document_lookups_pass_through(api, upstream, name, param) -> None:
    body = [{"value": "GR", "count": 3}]
    route = upstream.get(f"/lookups/{name}").respond(json=body)
    r = await api.get(f"{PREFIX}/lookups/{name}", params=[param])
    assert r.status_code == 200, r.text
    assert r.json() == body
    assert r.headers["X-Knowbase-Cache"] == "miss"
    assert _params(route) == [param]
    again = await api.get(f"{PREFIX}/lookups/{name}", params=[param])
    assert again.headers["X-Knowbase-Cache"] == "hit"


@pytest.mark.parametrize("name", ["categories", "levels-of-application", "scales", "keywords"])
async def test_measure_lookups_pass_through(api, upstream, name) -> None:
    body = [{"id": 1, "label_en": "Z"}]
    route = upstream.get(f"/measures/lookups/{name}").respond(json=body)
    r = await api.get(f"{PREFIX}/measures/lookups/{name}")
    assert r.status_code == 200, r.text
    assert r.json() == body
    assert route.called


async def test_lookup_cross_filters_forwarded(api, upstream) -> None:
    route = upstream.get("/lookups/countries").respond(json=[])
    r = await api.get(
        f"{PREFIX}/lookups/countries",
        params=[("level_id", "1"), ("subject_id", "2"), ("keyword_ids", "4"), ("keyword_ids", "5")],
    )
    assert r.status_code == 200
    assert _params(route) == [
        ("keyword_ids", "4"),
        ("keyword_ids", "5"),
        ("level_id", "1"),
        ("subject_id", "2"),
    ]


async def test_lookup_rejects_its_own_dimension_as_filter(api, upstream) -> None:
    route = upstream.get("/lookups/countries").respond(json=[])
    r = await api.get(f"{PREFIX}/lookups/countries", params={"country": "GR"})
    assert r.status_code == 422
    assert r.json()["detail"]["fields"] == {"query.country": "extra_forbidden"}
    assert not route.called


@pytest.mark.parametrize(
    "url",
    [
        f"{PREFIX}/lookups/secrets",
        f"{PREFIX}/lookups/categories",
        f"{PREFIX}/measures/lookups/countries",
        f"{PREFIX}/lookups/Countries",
    ],
)
async def test_unknown_lookup_is_404(api, upstream, url) -> None:
    r = await api.get(url)
    assert r.status_code == 404
    assert r.json()["detail"]["code"] == "knowbase.unknown_lookup"
    assert not upstream.calls


@pytest.mark.parametrize(
    "url",
    [
        f"{PREFIX}/measures/lookups/..%2F..%2Fadmin",
        f"{PREFIX}/lookups/countries/extra",
        f"{PREFIX}/health",
    ],
)
async def test_paths_outside_the_allow_list_never_reach_upstream(api, upstream, url) -> None:
    r = await api.get(url)
    assert r.status_code == 404
    assert not upstream.calls


async def test_lookups_cached_for_a_day(monkeypatch, clock, upstream) -> None:
    monkeypatch.setattr(settings, "KNOWBASE_CACHE_TTL_LIST", 10)
    route = upstream.get("/measures/lookups/scales").respond(json=[])
    client = KnowbaseClient()
    try:
        await client.get_measure_lookup("scales", {})
        clock.advance(86399)
        assert (await client.get_measure_lookup("scales", {})).cache == "hit"
        clock.advance(2)
        assert (await client.get_measure_lookup("scales", {})).cache == "miss"
        assert route.call_count == 2
    finally:
        await client.aclose()


# --- measures photo_url -----------------------------------------------------------------------


async def test_measures_get_absolute_photo_url(api, upstream) -> None:
    no_photo = {**MEASURE, "id": 4, "photo_filename": None}
    upstream.get("/measures/").respond(json={"total": 2, "items": [MEASURE, no_photo]})
    upstream.get("/measures/3").respond(json=MEASURE)

    for _ in range(2):  # the cached upstream value is not mutated
        listing = await api.get(f"{PREFIX}/measures/")
        items = listing.json()["items"]
        assert items[0]["photo_url"] == f"{KB_PUBLIC}/static/measures/photos/s%2001.jpg"
        assert items[1]["photo_url"] is None
        assert items[0]["measure_code"] == 101
        assert listing.json()["total"] == 2

    detail = await api.get(f"{PREFIX}/measures/3")
    assert detail.json()["photo_url"] == f"{KB_PUBLIC}/static/measures/photos/s%2001.jpg"
    assert detail.json()["category"]["code"] == "STR"
    assert "photo_url" not in MEASURE


async def test_documents_get_no_photo_url(api, upstream) -> None:
    upstream.get("/documents/7").respond(json=DOCUMENT)
    r = await api.get(f"{PREFIX}/documents/7")
    assert "photo_url" not in r.json()


# --- status and clear_cache -------------------------------------------------------------------


async def test_status_initially_reachable_without_request(api, upstream) -> None:
    r = await api.get(f"{PREFIX}/status")
    assert r.status_code == 200
    body = r.json()
    assert body == {
        "reachable": True,
        "last_success_at": None,
        "last_error_at": None,
        "last_error": None,
        "cache": {"lists": 0, "details": 0, "lookups": 0, "stale": 0},
    }
    assert not upstream.calls


async def test_status_reflects_last_error_then_recovery(kb, upstream) -> None:
    upstream.get("/levels/").mock(
        side_effect=[httpx.ConnectTimeout("slow"), httpx.Response(200, json=[])]
    )
    with pytest.raises(KnowbaseUnavailable):
        await kb.get_levels()
    status = kb.status()
    assert status["reachable"] is False
    assert status["last_error"] == "timeout"
    assert status["last_error_at"] is not None
    assert status["last_success_at"] is None

    await kb.get_levels()
    status = kb.status()
    assert status["reachable"] is True
    assert status["last_success_at"] >= status["last_error_at"]
    assert status["last_error"] == "timeout"  # kept for diagnostics
    assert status["cache"]["lists"] == 1
    assert status["cache"]["stale"] == 1


async def test_status_records_http_5xx(api, upstream) -> None:
    upstream.get("/subjects/").respond(503)
    await api.get(f"{PREFIX}/subjects/")
    body = (await api.get(f"{PREFIX}/status")).json()
    assert body["reachable"] is False
    assert body["last_error"] == "http_503"


async def test_clear_cache_empties_everything(kb, upstream) -> None:
    route = upstream.get("/levels/").respond(json=[])
    upstream.get("/documents/7").respond(json=DOCUMENT)
    upstream.get("/lookups/countries").respond(json=[])
    await kb.get_levels()
    await kb.get_document(7)
    await kb.get_document_lookup("countries", {})
    assert kb.status()["cache"] == {"lists": 1, "details": 1, "lookups": 1, "stale": 3}

    kb.clear_cache()

    assert kb.status()["cache"] == {"lists": 0, "details": 0, "lookups": 0, "stale": 0}
    assert (await kb.get_levels()).cache == "miss"
    assert route.call_count == 2


# --- resolve_links ----------------------------------------------------------------------------


async def test_resolve_links_returns_titles_and_none_for_missing(kb, upstream) -> None:
    upstream.get("/documents/7").respond(json=DOCUMENT)
    upstream.get("/measures/3").respond(json=MEASURE)
    upstream.get("/measures/404").respond(404, json={"detail": "Measure not found"})

    result = await kb.resolve_links(
        [("document", 7), ("measure", 3), ("measure", 404), ("document", 7)]
    )

    assert result == {
        ("document", 7): {
            "title_en": "Flood Risk Act",
            "title_local": "Νόμος για τις πλημμύρες",
        },
        ("measure", 3): {"title_en": "Retention basin", "title_local": "Λεκάνη ανάσχεσης"},
        ("measure", 404): None,
    }
    assert len(upstream.calls) == 3  # duplicates fetched once


async def test_resolve_links_uses_detail_cache(kb, upstream) -> None:
    route = upstream.get("/documents/7").respond(json=DOCUMENT)
    await kb.get_document(7)
    await kb.resolve_links([("document", 7)])
    assert route.call_count == 1


async def test_resolve_links_limits_concurrency_to_5(kb, upstream) -> None:
    in_flight = 0
    peak = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        measure_id = int(request.url.path.rsplit("/", 1)[1])
        return httpx.Response(200, json={**MEASURE, "id": measure_id})

    for measure_id in range(1, 13):
        upstream.get(f"/measures/{measure_id}").mock(side_effect=slow)

    result = await kb.resolve_links([("measure", i) for i in range(1, 13)])

    assert len(result) == 12
    assert all(value is not None for value in result.values())
    assert peak == 5


async def test_resolve_links_rejects_unknown_type(kb) -> None:
    with pytest.raises(ValueError):
        await kb.resolve_links([("post", 1)])


async def test_resolve_links_propagates_unavailable(kb, upstream) -> None:
    upstream.get("/documents/7").mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(KnowbaseUnavailable):
        await kb.resolve_links([("document", 7)])


# --- lifespan and wiring ----------------------------------------------------------------------


async def test_lifespan_creates_and_closes_the_client(recwarn) -> None:
    from asgi_lifespan import LifespanManager

    from app.main import app

    async with LifespanManager(app):
        client: Any = app.state.knowbase
        assert isinstance(client, KnowbaseClient)
        assert client.is_closed is False
    assert client.is_closed is True
    assert not [w for w in recwarn if issubclass(w.category, ResourceWarning)]


async def test_get_knowbase_dependency_returns_app_client(api) -> None:
    from starlette.requests import Request

    from app.core.deps import get_knowbase
    from app.main import app

    request = Request({"type": "http", "app": app})
    assert get_knowbase(request) is app.state.knowbase


async def test_routes_are_public_get_only(api, upstream) -> None:
    upstream.get("/levels/").respond(json=[])
    r = await api.post(f"{PREFIX}/levels/")
    assert r.status_code == 405
    assert not upstream.calls
