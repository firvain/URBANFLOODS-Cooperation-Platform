"""Cloudflare Turnstile server-side verification (all network mocked with respx)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from urllib.parse import parse_qs

import httpx
import pytest
import respx

from app.core.config import settings
from app.services import turnstile
from app.services.turnstile import SITEVERIFY_URL, TurnstileError, verify_turnstile


@pytest.fixture
def enabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "TURNSTILE_ENABLED", True)
    monkeypatch.setattr(settings, "TURNSTILE_SECRET_KEY", "test-turnstile-secret")


@pytest.fixture
async def http() -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient() as client:
        yield client


def test_error_code() -> None:
    assert TurnstileError().code == "auth.captcha_failed"


@respx.mock
async def test_disabled_makes_no_request(http) -> None:
    assert settings.TURNSTILE_ENABLED is False
    route = respx.post(SITEVERIFY_URL).respond(json={"success": False})
    await verify_turnstile(None, client=http)
    await verify_turnstile("whatever")  # default client path: also no network
    assert not route.called


@respx.mock
async def test_success_returns_none_and_posts_form(enabled, http) -> None:
    route = respx.post(SITEVERIFY_URL).respond(json={"success": True, "error-codes": []})
    assert await verify_turnstile("tok-123", "203.0.113.7", client=http) is None
    assert route.call_count == 1
    form = parse_qs(route.calls.last.request.content.decode())
    assert form == {
        "secret": ["test-turnstile-secret"],
        "response": ["tok-123"],
        "remoteip": ["203.0.113.7"],
    }


@respx.mock
async def test_success_without_remote_ip(enabled, http) -> None:
    route = respx.post(SITEVERIFY_URL).respond(json={"success": True})
    await verify_turnstile("tok-123", client=http)
    form = parse_qs(route.calls.last.request.content.decode())
    assert "remoteip" not in form


@respx.mock
async def test_default_client_is_used_when_none_injected(enabled) -> None:
    route = respx.post(SITEVERIFY_URL).respond(json={"success": True})
    try:
        await verify_turnstile("tok-123")
        assert route.called
    finally:
        await turnstile.aclose_client()


@respx.mock
async def test_success_false_raises_and_logs_codes_not_token(enabled, http) -> None:
    import structlog

    respx.post(SITEVERIFY_URL).respond(
        json={"success": False, "error-codes": ["invalid-input-response"]}
    )
    with structlog.testing.capture_logs() as logs:
        with pytest.raises(TurnstileError) as exc_info:
            await verify_turnstile("secret-token-value", client=http)
    assert exc_info.value.code == "auth.captcha_failed"
    warnings = [e for e in logs if e["log_level"] == "warning"]
    assert warnings and warnings[0]["error_codes"] == ["invalid-input-response"]
    assert "secret-token-value" not in repr(logs)


@pytest.mark.parametrize("token", [None, ""])
@respx.mock
async def test_missing_token_raises_without_request(enabled, http, token) -> None:
    route = respx.post(SITEVERIFY_URL).respond(json={"success": True})
    with pytest.raises(TurnstileError):
        await verify_turnstile(token, client=http)
    assert not route.called


@respx.mock
async def test_server_error_raises(enabled, http) -> None:
    respx.post(SITEVERIFY_URL).respond(status_code=500)
    with pytest.raises(TurnstileError):
        await verify_turnstile("tok", client=http)


@respx.mock
async def test_non_json_body_raises(enabled, http) -> None:
    respx.post(SITEVERIFY_URL).respond(text="not json")
    with pytest.raises(TurnstileError):
        await verify_turnstile("tok", client=http)


@pytest.mark.parametrize(
    "exc", [httpx.TimeoutException("slow"), httpx.ConnectError("down")], ids=["timeout", "network"]
)
@respx.mock
async def test_timeout_or_network_error_raises(enabled, http, exc) -> None:
    respx.post(SITEVERIFY_URL).mock(side_effect=exc)
    with pytest.raises(TurnstileError):
        await verify_turnstile("tok", client=http)
