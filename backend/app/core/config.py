"""Application configuration using pydantic-settings.

Settings are read only here; never read ``os.environ`` elsewhere.
"""

import json
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables (and ``.env``)."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

    # Application
    ENV: Literal["dev", "test", "prod"] = "dev"
    PROJECT_NAME: str = "URBANFLOODS Cooperation Platform API"
    VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api/v1"

    # Database, e.g. postgresql+asyncpg://user:password@host:5432/cooperation_db
    DATABASE_URL: str

    # CORS: comma-separated string or JSON list
    ALLOWED_ORIGINS: Annotated[list[str], NoDecode] = ["http://localhost:5173"]

    # Docs (disable in production)
    ENABLE_DOCS: bool = True

    # Security and sessions
    SECRET_KEY: str
    FRONTEND_URL: str = "http://localhost:5173"
    COOKIE_SECURE: bool = False
    SESSION_COOKIE_NAME: str = "uf_session"
    SESSION_TTL_DAYS: int = 30

    # Email
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "urbanfloods@gmail.com"
    SMTP_FROM_NAME: str = "URBANFLOODS Cooperation Platform"
    EMAIL_ENABLED: bool = False

    # KNOWBASE (public REST API only)
    KNOWBASE_BASE_URL: str = "https://knowbase.urbanfloods.app"
    KNOWBASE_PUBLIC_URL: str = "https://knowbase.urbanfloods.app"
    KNOWBASE_TIMEOUT_SECONDS: float = 5.0
    KNOWBASE_CACHE_TTL_LIST: int = 900
    KNOWBASE_CACHE_TTL_DETAIL: int = 21600

    # Cloudflare Turnstile
    TURNSTILE_ENABLED: bool = False
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""

    # Uploads
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_MB: int = 5
    UPLOAD_THUMB_PX: int = 480
    UPLOAD_MAX_PX: int = 1920
    UPLOAD_URL_PREFIX: str = "/static/uploads"

    # Moderation
    REPORT_AUTO_HIDE_THRESHOLD: int = 3
    AUTO_APPROVE_AFTER_DAYS: int = 0

    # Scheduler / digest
    ENABLE_SCHEDULER: bool = False
    DIGEST_HOUR_UTC: int = 6

    # Maintenance (scheduler job / ``python -m app.cli maintenance``)
    UNVERIFIED_PURGE_DAYS: int = 30
    ORPHAN_UPLOAD_HOURS: int = 24

    # Rate limiting / proxy
    RATE_LIMIT_ENABLED: bool = True
    TRUST_PROXY_HEADERS: bool = False

    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False

    # Content
    CONTENT_LICENSE_URL: str = "https://creativecommons.org/licenses/by/4.0/"
    # Project contact named in emails (e.g. a rejected post): the University of Western Macedonia.
    CONTACT_EMAIL: str = "louta@uowm.gr"

    @field_validator("ALLOWED_ORIGINS", mode="before")
    @classmethod
    def _parse_origins(cls, v: Any) -> Any:
        """Accept a JSON list or a comma-separated string."""
        if isinstance(v, str):
            stripped = v.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [origin.strip() for origin in stripped.split(",") if origin.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
