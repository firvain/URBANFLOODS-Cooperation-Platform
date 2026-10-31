import pytest

from app.core.config import Settings


@pytest.fixture
def base_env(monkeypatch):
    """Only the required settings; ignore any local .env file."""
    for name in ("ENV", "ALLOWED_ORIGINS"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost:5432/db")
    monkeypatch.setenv("SECRET_KEY", "x")
    return monkeypatch


def test_allowed_origins_parses_comma_separated_string(base_env):
    base_env.setenv("ALLOWED_ORIGINS", "http://a,http://b")

    s = Settings(_env_file=None)

    assert s.ALLOWED_ORIGINS == ["http://a", "http://b"]


def test_allowed_origins_accepts_json_list(base_env):
    base_env.setenv("ALLOWED_ORIGINS", '["http://a", "http://b"]')

    s = Settings(_env_file=None)

    assert s.ALLOWED_ORIGINS == ["http://a", "http://b"]


def test_settings_defaults(base_env):
    s = Settings(_env_file=None)

    assert s.API_V1_PREFIX == "/api/v1"
    assert s.SESSION_COOKIE_NAME == "uf_session"
    assert s.ENV == "dev"
    assert s.REPORT_AUTO_HIDE_THRESHOLD == 3
    assert s.AUTO_APPROVE_AFTER_DAYS == 0


def test_email_defaults_are_the_brevo_relay_and_project_addresses(base_env):
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_FROM", "SMTP_FROM_NAME", "SMTP_REPLY_TO"):
        base_env.delenv(name, raising=False)

    s = Settings(_env_file=None)

    assert s.SMTP_HOST == "smtp-relay.brevo.com"
    assert s.SMTP_PORT == 587
    assert s.SMTP_FROM == "noreply@cooperation.urbanfloods.app"
    assert s.SMTP_FROM_NAME == "URBANFLOODS Cooperation Platform"
    assert s.SMTP_REPLY_TO == "urbanfloods@uowm.gr"
