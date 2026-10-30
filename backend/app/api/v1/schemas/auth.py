"""Auth request/response schemas.

Field errors come back as ``detail.fields[<field>] = <code>`` (see ``app.core.exceptions``):
pydantic's error ``type`` for built-in checks, or the custom codes raised here.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, get_args

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.db.enums import OrganisationType, UserRole

# The 9 interface locales (same as the KNOWBASE frontend).
Locale = Literal["en", "el", "sq", "mk", "sr", "bs", "sl", "hr", "it"]
SUPPORTED_LOCALES: tuple[str, ...] = get_args(Locale)

# Any ISO 3166-1 alpha-2 shaped code is accepted (normalised to upper case).
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
TurnstileToken = Annotated[str | None, Field(default=None, max_length=2048)]


class RegisterRequest(BaseModel):
    email: EmailStr
    # Only presence is checked here; the policy (length, blocklist) runs in crud so the client
    # gets a specific code in ``fields.password``.
    password: Annotated[str, Field(min_length=1)]
    display_name: DisplayName
    organisation_id: int | None = None
    organisation_other: Annotated[
        str | None, StringConstraints(strip_whitespace=True, max_length=200)
    ] = None
    country: str | None = None
    locale: Locale = "en"
    accept_terms: bool
    turnstile_token: TurnstileToken = None

    @field_validator("organisation_other")
    @classmethod
    def _blank_other_is_none(cls, value: str | None) -> str | None:
        return value or None

    @field_validator("country", mode="before")
    @classmethod
    def _normalise_country(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().upper() or None
            if value is not None and not _COUNTRY_RE.match(value):
                raise PydanticCustomError("invalid_country", "Use an ISO 3166-1 alpha-2 code")
        return value

    @field_validator("accept_terms")
    @classmethod
    def _terms_accepted(cls, value: bool) -> bool:
        if value is not True:
            raise PydanticCustomError("must_accept", "The terms must be accepted")
        return value

    @model_validator(mode="after")
    def _one_organisation(self) -> RegisterRequest:
        if self.organisation_id is not None and self.organisation_other is not None:
            raise PydanticCustomError(
                "organisation_conflict",
                "Give either organisation_id or organisation_other, not both",
            )
        return self


class RegisterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    is_verified: bool


class VerifyEmailRequest(BaseModel):
    token: Annotated[str, Field(min_length=1, max_length=512)]


class ResendVerificationRequest(BaseModel):
    email: EmailStr
    turnstile_token: TurnstileToken = None


class MessageResponse(BaseModel):
    code: str
    message: str


class OrganisationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    short_name: str
    name: str
    country: str
    type: OrganisationType


class UserMe(BaseModel):
    """The signed-in user's own account."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    organisation: OrganisationSummary | None
    organisation_other: str | None
    country: str | None
    locale: str
    bio: str | None
    role: UserRole
    is_verified: bool
    trusted_at: datetime | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_trusted(self) -> bool:
        return self.trusted_at is not None
