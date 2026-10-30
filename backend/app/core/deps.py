"""FastAPI dependencies shared by endpoints.

``DbTx`` gives an endpoint one transaction for the whole request: committed when the endpoint
returns, rolled back if it raises. ``scope="function"`` makes the commit happen before the
response is sent, so a client never sees a success for a write that then failed to commit.

Auth dependencies (``get_current_user``, ``require_user``, ...) arrive in increment 1e.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import AsyncSessionLocal

CLIENT_IP_HEADER = "CF-Connecting-IP"


async def get_db_tx() -> AsyncIterator[AsyncSession]:
    """Yield a session inside ``session.begin()``: commit on success, rollback on exception."""
    async with AsyncSessionLocal() as session, session.begin():
        yield session


DbTx = Annotated[AsyncSession, Depends(get_db_tx, scope="function")]


def client_ip(request: Request) -> str | None:
    """The client's IP: Cloudflare's header behind the proxy, else the socket peer.

    Used only transiently (Turnstile, rate limits). Never stored.
    """
    if settings.TRUST_PROXY_HEADERS:
        forwarded = request.headers.get(CLIENT_IP_HEADER)
        if forwarded:
            return forwarded.strip()
    return request.client.host if request.client else None
