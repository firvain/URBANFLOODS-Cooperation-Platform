"""Auth request/response schemas.

Field errors come back as ``detail.fields[<field>] = <code>`` (see ``app.core.exceptions``):
pydantic's error ``type`` for built-in checks, or the custom codes raised here.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal, Self, get_args

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.core.security import PASSWORD_MAX_LENGTH
from app.db.enums import OrganisationType, UserRole

# The 9 interface locales (same as the KNOWBASE frontend).
Locale = Literal["en", "el", "sq", "mk", "sr", "bs", "sl", "hr", "it"]
SUPPORTED_LOCALES: tuple[str, ...] = get_args(Locale)

# Any ISO 3166-1 alpha-2 shaped code is accepted (normalised to upper case).
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
TurnstileToken = Annotated[str | None, Field(default=None, max_length=2048)]
LOGIN_PASSWORD_MAX_LENGTH = PASSWORD_MAX_LENGTH


def normalise_country(value: object) -> object:
    """Strip and upper-case; blank becomes None; anything else must look like ISO alpha-2."""
    if isinstance(value, str):
        value = value.strip().upper() or None
        if value is not None and not _COUNTRY_RE.match(value):
            raise PydanticCustomError("invalid_country", "Use an ISO 3166-1 alpha-2 code")
    return value


def blank_to_none(value: str | None) -> str | None:
    return value or None


Country = Annotated[str | None, BeforeValidator(normalise_country)]
OrganisationOther = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=200),
    AfterValidator(blank_to_none),
]
Bio = Annotated[
    str | None,
    StringConstraints(strip_whitespace=True, max_length=2000),
    AfterValidator(blank_to_none),
]


class OrganisationFieldsMixin(BaseModel):
    """``organisation_id`` (a listed organisation) or ``organisation_other`` (free text), never
    both."""

    organisation_id: int | None = None
    organisation_other: OrganisationOther = None

    @model_validator(mode="after")
    def _one_organisation(self) -> Self:
        if self.organisation_id is not None and self.organisation_other is not None:
            raise PydanticCustomError(
                "organisation_conflict",
                "Give either organisation_id or organisation_other, not both",
            )
        return self


class RegisterRequest(OrganisationFieldsMixin):
    email: EmailStr
    # Only presence is checked here; the policy (length, blocklist) runs in crud so the client
    # gets a specific code in ``fields.password``.
    password: Annotated[str, Field(min_length=1)]
    display_name: DisplayName
    country: Country = None
    locale: Locale = "en"
    accept_terms: bool
    turnstile_token: TurnstileToken = None

    @field_validator("accept_terms")
    @classmethod
    def _terms_accepted(cls, value: bool) -> bool:
        if value is not True:
            raise PydanticCustomError("must_accept", "The terms must be accepted")
        return value


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


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=LOGIN_PASSWORD_MAX_LENGTH)]


class UpdateMeRequest(OrganisationFieldsMixin):
    """Partial profile update. Only fields present in the body are applied (``model_fields_set``
    / ``exclude_unset``); an explicit ``null`` clears a nullable field. ``display_name`` and
    ``locale`` cannot be cleared."""

    display_name: DisplayName | None = None
    country: Country = None
    locale: Locale | None = None
    bio: Bio = None

    @field_validator("display_name", "locale")
    @classmethod
    def _not_null(cls, value: object) -> object:
        # Field validators run only for values present in the body, never for the defaults.
        if value is None:
            raise PydanticCustomError("null_not_allowed", "This field cannot be cleared")
        return value


class SessionInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None
    is_current: bool


class SessionList(BaseModel):
    total: int
    items: list[SessionInfo]
