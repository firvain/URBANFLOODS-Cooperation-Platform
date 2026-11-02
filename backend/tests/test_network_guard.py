"""The test suite never reaches the internet (7n): every outgoing call must be mocked.

On 2026-11-02 an unmocked test sent five requests to the live KNOWBASE. ``conftest.py`` now
refuses any socket connection to a public address; loopback, private (Docker) and Unix-socket
connections stay allowed for the test database and testcontainers.
"""

from __future__ import annotations

import socket

import httpx
import pytest

from tests.conftest import NetworkAccessBlocked, network_blocked_attempts


def test_public_tcp_connection_is_refused() -> None:
    with pytest.raises(NetworkAccessBlocked), socket.socket() as sock:
        sock.connect(("93.184.215.14", 443))  # a public address; never reached
    network_blocked_attempts.clear()


def test_public_hostname_is_refused() -> None:
    with pytest.raises(NetworkAccessBlocked), socket.socket() as sock:
        sock.connect(("knowbase.urbanfloods.app", 443))
    network_blocked_attempts.clear()


async def test_unmocked_httpx_call_is_refused() -> None:
    # httpx/anyio may wrap the error (an exception group), so check the recorded attempt too.
    with pytest.raises(BaseException) as raised:
        async with httpx.AsyncClient() as client:
            await client.get("https://knowbase.urbanfloods.app/api/v1/measures/")
    assert "NetworkAccessBlocked" in repr(raised.value) or network_blocked_attempts
    assert any(attempt.endswith(":443") for attempt in network_blocked_attempts)
    network_blocked_attempts.clear()


def test_loopback_is_allowed() -> None:
    with socket.socket() as sock:
        # Nothing listens on port 1: the OS refuses it, the guard does not.
        with pytest.raises(ConnectionRefusedError):
            sock.connect(("127.0.0.1", 1))
    assert not network_blocked_attempts
