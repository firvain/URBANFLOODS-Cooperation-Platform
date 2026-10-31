"""Auth request/response schemas.

Field errors come back as ``detail.fields[<field>] = <code>`` (see ``app.core.exceptions``):
pydantic's error ``type`` for built-in checks, or the custom codes raised here.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal, Self, get_args

from pydantic import (
    AfterValidator,
    AliasPath,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
    computed_field,
    field_serializer,
    field_validator,
    model_validator,
)
from pydantic_core import PydanticCustomError

from app.api.v1.schemas.expertise import ExpertiseTagOut
from app.api.v1.schemas.upload import upload_url
from app.core.security import PASSWORD_MAX_LENGTH
from app.db.enums import DigestFrequency, OrganisationType, UserRole

# The 9 interface locales (same as the KNOWBASE frontend).
Locale = Literal["en", "el", "sq", "mk", "sr", "bs", "sl", "hr", "it"]
SUPPORTED_LOCALES: tuple[str, ...] = get_args(Locale)

# Any ISO 3166-1 alpha-2 shaped code is accepted (normalised to upper case).
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=120)]
TurnstileToken = Annotated[str | None, Field(default=None, max_length=2048)]
# Most expertise tags a profile may carry.
MAX_EXPERTISE = 8
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
    # Duplicates collapse; unknown or inactive ids are rejected in crud (``not_found``).
    expertise_ids: Annotated[list[int], Field(max_length=MAX_EXPERTISE)] = []
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
    expertise: list[ExpertiseTagOut]
    show_email: bool
    show_in_directory: bool
    # Read from ``user.avatar.storage_path`` (the relationship must be eagerly loaded); served as
    # the public URL.
    avatar_url: str | None = Field(
        default=None, validation_alias=AliasPath("avatar", "storage_path")
    )

    @field_serializer("avatar_url")
    def _avatar_url(self, storage_path: str | None) -> str | None:
        return upload_url(storage_path)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_trusted(self) -> bool:
        return self.trusted_at is not None


class LoginRequest(BaseModel):
    email: EmailStr
    password: Annotated[str, Field(min_length=1, max_length=LOGIN_PASSWORD_MAX_LENGTH)]


class UpdateMeRequest(OrganisationFieldsMixin):
    """Partial profile update. Only fields present in the body are applied (``model_fields_set``
    / ``exclude_unset``); an explicit ``null`` clears a nullable field. ``display_name``,
    ``locale``, the visibility flags and ``expertise_ids`` cannot be ``null``; ``expertise_ids``
    replaces the whole set (``[]`` clears it)."""

    display_name: DisplayName | None = None
    country: Country = None
    locale: Locale | None = None
    bio: Bio = None
    expertise_ids: Annotated[list[int], Field(max_length=MAX_EXPERTISE)] | None = None
    show_email: bool | None = None
    show_in_directory: bool | None = None

    @field_validator("display_name", "locale", "expertise_ids", "show_email", "show_in_directory")
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


# --- password and email changes ---------------------------------------------------------------

# The token from an emailed link (raw tokens are 43 characters).
LinkToken = Annotated[str, Field(min_length=1, max_length=512)]
PasswordField = Annotated[str, Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)]


class ForgotPasswordRequest(BaseModel):
    email: EmailStr
    turnstile_token: TurnstileToken = None


class ResetPasswordRequest(BaseModel):
    token: LinkToken
    # Only presence is checked here (as at registration); the policy runs in crud so the client
    # gets a specific code in ``fields.password``.
    password: Annotated[str, Field(min_length=1)]


class ChangePasswordRequest(BaseModel):
    current_password: PasswordField
    new_password: PasswordField


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    current_password: PasswordField


class ConfirmEmailRequest(BaseModel):
    token: LinkToken


# --- notification preferences, GDPR export and account deletion -------------------------------


class NotificationPreferences(BaseModel):
    """``GET /me/notifications`` response and ``PUT`` body (full replace: every field
    required)."""

    model_config = ConfigDict(from_attributes=True)

    reply_to_my_thread: bool
    comment_on_my_post: bool
    reply_to_my_reply: bool
    admin_digest: bool
    digest_frequency: DigestFrequency


class DeleteAccountRequest(BaseModel):
    current_password: PasswordField


class ExportOrganisation(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    short_name: str


class ExportUser(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    display_name: str
    organisation: ExportOrganisation | None
    organisation_other: str | None
    country: str | None
    locale: str
    bio: str | None
    role: UserRole
    is_verified: bool
    trusted_at: datetime | None
    created_at: datetime
    updated_at: datetime
    last_login_at: datetime | None
    expertise: list[ExpertiseTagOut]
    show_email: bool
    show_in_directory: bool


class ExportSession(BaseModel):
    """Every session of the account, including revoked and expired ones (never the token)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    user_agent: str | None
    revoked_at: datetime | None


class ExportAuditEntry(BaseModel):
    """An audit row by or about the account. The actor is left out on purpose (it may be an
    admin)."""

    model_config = ConfigDict(from_attributes=True)

    action: str
    target_type: str | None
    target_id: int | None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    created_at: datetime


class ExportContent(BaseModel):
    """The user's own content. Empty until posts (M2) and the forum (M3) exist."""

    posts: list[dict[str, Any]] = Field(default_factory=list)
    threads: list[dict[str, Any]] = Field(default_factory=list)
    replies: list[dict[str, Any]] = Field(default_factory=list)
    comments: list[dict[str, Any]] = Field(default_factory=list)


class AccountExport(BaseModel):
    """``GET /me/export``: everything stored about the signed-in user (GDPR art. 15/20)."""

    exported_at: datetime
    format_version: int
    licence_note: str
    user: ExportUser
    notification_preferences: NotificationPreferences | None
    sessions: list[ExportSession]
    audit_log: list[ExportAuditEntry]
    content: ExportContent
