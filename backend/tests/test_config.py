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
