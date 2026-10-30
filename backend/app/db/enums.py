"""Python enums backing the Postgres ENUM types.

Each class maps to a snake_case PG type (see ``app.db.models``). Values, not member names, are
stored in the database; the migration creates the types with exactly these values, in this order.
"""

from enum import StrEnum


class UserRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"
    SUPERADMIN = "superadmin"


class TokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"
    CHANGE_EMAIL = "change_email"


class OrganisationType(StrEnum):
    PP = "PP"
    AP = "AP"
    OTHER = "other"


class DigestFrequency(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
