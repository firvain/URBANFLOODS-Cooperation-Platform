"""Email service: template rendering, locale fallback, backends, SMTP message building."""

from __future__ import annotations

from collections.abc import Iterator
from email.message import EmailMessage
from unittest.mock import AsyncMock

import pytest
import structlog

from app.core.config import settings
from app.services import email as email_service
from app.services.email import (
    EmailTemplateNotFound,
    LoggingBackend,
    OutboxBackend,
    OutgoingEmail,
    SmtpBackend,
    get_backend,
    render_email,
    reset_backend,
    send_email,
)

VERIFY_PATH = "/verify-email?token=abc123"
VERIFY_URL = settings.FRONTEND_URL.rstrip("/") + VERIFY_PATH


@pytest.fixture
def fresh_backend() -> Iterator[None]:
    """Forget the cached backend before and after a test that changes settings."""
    reset_backend()
    yield
    reset_backend()


def _ctx(**extra: object) -> dict:
    return {"display_name": "Maria", "verify_url": VERIFY_PATH, **extra}


# --- rendering ---------------------------------------------------------------------------


def test_render_verify_email_en() -> None:
    subject, text, html = render_email("verify_email", "en", _ctx())
    assert "Verify" in subject
    assert "\n" not in subject
    assert VERIFY_URL in text
    assert f'<a href="{VERIFY_URL}"' in html
    assert "URBANFLOODS Cooperation Platform" in text
    assert "co-funded by the European Union" in text
    assert "co-funded by the European Union" in html
    assert "if it wasn't you, ignore this email" in text


def test_render_escapes_html_but_not_text() -> None:
    _, text, html = render_email("verify_email", "en", _ctx(display_name="<script>x</script>"))
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "<script>x</script>" in text


def test_render_reset_password_en() -> None:
    reset_url = settings.FRONTEND_URL + "/reset-password?token=r1"
    subject, text, html = render_email(
        "reset_password", "en", {"display_name": "Maria", "reset_url": "/reset-password?token=r1"}
    )
    assert subject
    assert reset_url in text
    assert f'<a href="{reset_url}"' in html
    assert "If you did not request this, ignore this email" in text


def test_render_change_email_and_welcome_en() -> None:
    confirm_path = "/account/confirm-email?token=c1"
    confirm_url = settings.FRONTEND_URL + confirm_path
    subject, text, html = render_email(
        "change_email",
        "en",
        {"display_name": "Maria", "confirm_url": confirm_path, "new_email": "new@example.org"},
    )
    assert confirm_url in text and f'<a href="{confirm_url}"' in html
    assert "new@example.org" in text

    login_url = settings.FRONTEND_URL + "/login"
    subject, text, html = render_email("welcome", "en", {"display_name": "Maria"})
    assert "Welcome" in subject
    assert login_url in text and f'<a href="{login_url}"' in html


def test_common_context_injected() -> None:
    _, text, html = render_email("welcome", "en", {"display_name": "M"})
    assert settings.FRONTEND_URL in text
    assert settings.FRONTEND_URL in html


def test_locale_fallback_to_english_when_template_missing() -> None:
    subject, _, _ = render_email("welcome", "el", {"display_name": "Maria"})
    en_subject, _, _ = render_email("welcome", "en", {"display_name": "Maria"})
    assert subject == en_subject
    assert "Welcome" in subject


def test_greek_template_used_when_present() -> None:
    subject, text, html = render_email("verify_email", "el", _ctx())
    assert "Επιβεβαιώστε" in subject
    assert VERIFY_URL in text
    assert f'<a href="{VERIFY_URL}"' in html
    assert 'lang="el"' in html


def test_unknown_locale_falls_back_to_english() -> None:
    assert render_email("verify_email", "xx", _ctx()) == render_email("verify_email", "en", _ctx())
    # Hostile locale values never reach the filesystem.
    assert render_email("verify_email", "../en", _ctx()) == render_email(
        "verify_email", "en", _ctx()
    )


@pytest.mark.parametrize(
    "bad", ["https://evil.example/phish", "//evil.example/x", "verify-email", 42]
)
def test_url_context_values_must_be_site_relative_paths(bad) -> None:
    with pytest.raises(ValueError, match="verify_url"):
        render_email("verify_email", "en", _ctx(verify_url=bad))


def test_missing_context_variable_raises() -> None:
    with pytest.raises(Exception, match="verify_url"):
        render_email("verify_email", "en", {"display_name": "Maria"})


def test_unknown_template_raises() -> None:
    with pytest.raises(EmailTemplateNotFound, match="no_such_template"):
        render_email("no_such_template", "en", {})
    with pytest.raises(EmailTemplateNotFound):
        render_email("../../core/config", "en", {})


# --- send_email + outbox -----------------------------------------------------------------


async def test_send_email_with_explicit_outbox_backend() -> None:
    backend = OutboxBackend()
    msg = await send_email(
        to="maria@example.org",
        template="verify_email",
        locale="en",
        context=_ctx(),
        backend=backend,
    )
    assert backend.messages == [msg]
    assert isinstance(msg, OutgoingEmail)
    assert msg.to == "maria@example.org"
    assert msg.locale == "en"
    assert "Verify" in msg.subject
    assert VERIFY_URL in msg.text
    assert VERIFY_URL in msg.html


async def test_send_email_records_effective_locale(outbox) -> None:
    msg = await send_email(
        to="m@example.org",
        template="welcome",
        locale="el",
        context={"display_name": "M"},
    )
    assert outbox == [msg]
    assert msg.locale == "en"  # no Greek welcome template yet


async def test_outbox_fixture_uses_default_backend(outbox) -> None:
    assert outbox == []
    await send_email(to="a@example.org", template="verify_email", locale="en", context=_ctx())
    assert len(outbox) == 1
    assert outbox[0].to == "a@example.org"


async def test_outbox_fixture_is_cleared_between_tests(outbox) -> None:
    assert outbox == []


# --- backend selection -------------------------------------------------------------------


def test_get_backend_is_outbox_in_test_env(fresh_backend) -> None:
    assert settings.ENV == "test"
    assert settings.EMAIL_ENABLED is False
    backend = get_backend()
    assert isinstance(backend, OutboxBackend)
    assert get_backend() is backend  # cached


def test_get_backend_is_outbox_in_test_env_even_if_enabled(fresh_backend, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    assert isinstance(get_backend(), OutboxBackend)


def test_get_backend_is_smtp_when_enabled_outside_test(fresh_backend, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(settings, "ENV", "prod")
    assert isinstance(get_backend(), SmtpBackend)


def test_get_backend_is_logging_when_disabled_outside_test(fresh_backend, monkeypatch) -> None:
    monkeypatch.setattr(settings, "EMAIL_ENABLED", False)
    monkeypatch.setattr(settings, "ENV", "dev")
    assert isinstance(get_backend(), LoggingBackend)


async def test_logging_backend_logs_subject_and_to_but_never_bodies() -> None:
    msg = OutgoingEmail(
        to="m@example.org", subject="Hello", text="SECRET-TOKEN", html="SECRET-TOKEN", locale="en"
    )
    with structlog.testing.capture_logs() as logs:
        await LoggingBackend().send(msg)
    assert len(logs) == 1
    assert logs[0]["to"] == "m@example.org"
    assert logs[0]["subject"] == "Hello"
    assert "SECRET-TOKEN" not in repr(logs)


# --- SMTP --------------------------------------------------------------------------------


def _outgoing() -> OutgoingEmail:
    return OutgoingEmail(
        to="maria@example.org",
        subject="Verify your email",
        text="Plain body",
        html="<p>HTML body</p>",
        locale="en",
    )


@pytest.fixture
def smtp_send(monkeypatch) -> AsyncMock:
    mock = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(email_service.aiosmtplib, "send", mock)
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.org")
    monkeypatch.setattr(settings, "SMTP_PORT", 587)
    monkeypatch.setattr(settings, "SMTP_FROM", "noreply@example.org")
    monkeypatch.setattr(settings, "SMTP_FROM_NAME", "URBANFLOODS Cooperation Platform")
    monkeypatch.setattr(settings, "SMTP_USER", "")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "")
    return mock


async def test_smtp_backend_builds_multipart_message(smtp_send) -> None:
    await SmtpBackend().send(_outgoing())

    smtp_send.assert_awaited_once()
    message = smtp_send.await_args.args[0]
    assert isinstance(message, EmailMessage)
    assert message["From"] == "URBANFLOODS Cooperation Platform <noreply@example.org>"
    assert message["To"] == "maria@example.org"
    assert message["Subject"] == "Verify your email"
    assert message["Message-ID"]
    assert message["Message-ID"].endswith("@example.org>")
    assert message["Date"]
    assert message.get_content_type() == "multipart/alternative"
    parts = list(message.iter_parts())
    assert [p.get_content_type() for p in parts] == ["text/plain", "text/html"]
    assert parts[0].get_content().strip() == "Plain body"
    assert parts[1].get_content().strip() == "<p>HTML body</p>"


async def test_smtp_backend_uses_starttls_on_587_without_auth(smtp_send) -> None:
    await SmtpBackend().send(_outgoing())
    kwargs = smtp_send.await_args.kwargs
    assert kwargs["hostname"] == "smtp.example.org"
    assert kwargs["port"] == 587
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False
    assert kwargs["timeout"] == 20
    assert "username" not in kwargs
    assert "password" not in kwargs


async def test_smtp_backend_authenticates_when_user_set(smtp_send, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SMTP_USER", "user@example.org")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "app-password")
    await SmtpBackend().send(_outgoing())
    kwargs = smtp_send.await_args.kwargs
    assert kwargs["username"] == "user@example.org"
    assert kwargs["password"] == "app-password"


async def test_smtp_backend_plain_on_other_ports(smtp_send, monkeypatch) -> None:
    """Mailpit in dev listens on 1025 without TLS: no STARTTLS, no implicit TLS."""
    monkeypatch.setattr(settings, "SMTP_PORT", 1025)
    await SmtpBackend().send(_outgoing())
    kwargs = smtp_send.await_args.kwargs
    assert kwargs["port"] == 1025
    assert kwargs["start_tls"] is False
    assert kwargs["use_tls"] is False


async def test_smtp_backend_implicit_tls_on_465(smtp_send, monkeypatch) -> None:
    monkeypatch.setattr(settings, "SMTP_PORT", 465)
    await SmtpBackend().send(_outgoing())
    kwargs = smtp_send.await_args.kwargs
    assert kwargs["use_tls"] is True
    assert kwargs["start_tls"] is False
