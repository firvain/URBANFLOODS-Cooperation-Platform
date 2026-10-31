"""Schemas for ``/notifications`` (the one-click unsubscribe)."""

from typing import Literal

from pydantic import BaseModel


class UnsubscribeResult(BaseModel):
    """The same answer for every valid token, whether or not anything changed (an unknown or
    deleted account is not revealed)."""

    status: Literal["unsubscribed"]
