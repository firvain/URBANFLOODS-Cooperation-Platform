"""Transactional email: Jinja2 templates per locale (English fallback) and pluggable backends.

Templates live in ``app/templates/email/<locale>/<template>.{subject.txt,txt.j2,html.j2}``. If any
of the three files is missing for the requested locale, all three are taken from ``en``.

Backends: ``OutboxBackend`` in tests (in-memory list), ``LoggingBackend`` when email is disabled
outside tests, ``SmtpBackend`` (aiosmtplib) otherwise. Bodies are never logged: they carry tokens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path
from typing import Any, Protocol

import aiosmtplib
import structlog
from jinja2 import (
    Environment,
    FileSystemLoader,
    StrictUndefined,
    TemplateNotFound,
    select_autoescape,
)

from app.core.config import settings

APP_NAME = "URBANFLOODS Cooperation Platform"
DEFAULT_LOCALE = "en"
SMTP_TIMEOUT_SECONDS = 20
TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"

_SUFFIXES = ("subject.txt", "txt.j2", "html.j2")
# Template and locale names are interpolated into file paths, so both are allow-listed.
_TEMPLATE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
_LOCALE_NAME = re.compile(r"^[a-z]{2,3}(?:-[A-Za-z]{2,4})?$")

_env = Environment(
    loader=FileSystemLoader(TEMPLATE_DIR),
    # Escape only the HTML body; subject and plain text are rendered verbatim.
    autoescape=select_autoescape(
        enabled_extensions=("html.j2",), default_for_string=False, default=False
    ),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
    keep_trailing_newline=True,
)


class EmailTemplateNotFound(LookupError):
    """Raised when no locale (not even English) has the requested email template."""


@dataclass(frozen=True)
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str
    locale: str


class EmailBackend(Protocol):
    async def send(self, msg: OutgoingEmail) -> None: ...


class OutboxBackend:
    """Collects messages in memory. Used in tests (see the ``outbox`` fixture)."""

    def __init__(self) -> None:
        self.messages: list[OutgoingEmail] = []

    async def send(self, msg: OutgoingEmail) -> None:
        self.messages.append(msg)


class LoggingBackend:
    """Email disabled outside tests: log recipient and subject only, never bodies."""

    async def send(self, msg: OutgoingEmail) -> None:
        structlog.get_logger(__name__).info(
            "email.not_sent", reason="EMAIL_ENABLED=false", to=msg.to, subject=msg.subject
        )


class SmtpBackend:
    """Send through SMTP with aiosmtplib: STARTTLS on 587, implicit TLS on 465, plain otherwise
    (Mailpit in dev). Logs in only when ``SMTP_USER`` is set."""

    def build_message(self, msg: OutgoingEmail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM))
        message["To"] = msg.to
        message["Subject"] = msg.subject
        message["Date"] = formatdate(usegmt=True)
        domain = settings.SMTP_FROM.rpartition("@")[2] or None
        message["Message-ID"] = make_msgid(domain=domain)
        message.set_content(msg.text)
        message.add_alternative(msg.html, subtype="html")
        return message

    async def send(self, msg: OutgoingEmail) -> None:
        port = settings.SMTP_PORT
        kwargs: dict[str, Any] = {
            "hostname": settings.SMTP_HOST,
            "port": port,
            "use_tls": port == 465,
            # Explicit False elsewhere disables aiosmtplib's opportunistic STARTTLS upgrade.
            "start_tls": port == 587,
            "timeout": SMTP_TIMEOUT_SECONDS,
        }
        if settings.SMTP_USER:
            kwargs["username"] = settings.SMTP_USER
            kwargs["password"] = settings.SMTP_PASSWORD
        await aiosmtplib.send(self.build_message(msg), **kwargs)


def _template_names(template: str, locale: str) -> list[str]:
    return [f"{locale}/{template}.{suffix}" for suffix in _SUFFIXES]


def _locale_has_template(template: str, locale: str) -> bool:
    return all((TEMPLATE_DIR / name).is_file() for name in _template_names(template, locale))


def _resolve_locale(template: str, locale: str) -> str:
    """The locale whose templates will be used: ``locale`` if it has all three files, else en."""
    if not _TEMPLATE_NAME.match(template):
        raise EmailTemplateNotFound(f"Invalid email template name: {template!r}")
    if _LOCALE_NAME.match(locale) and _locale_has_template(template, locale):
        return locale
    if _locale_has_template(template, DEFAULT_LOCALE):
        return DEFAULT_LOCALE
    raise EmailTemplateNotFound(
        f"Email template {template!r} not found (looked in {locale!r} and {DEFAULT_LOCALE!r})"
    )


def _check_link_paths(context: dict[str, Any]) -> None:
    """Every ``*_url`` value is a site-relative path; templates prefix it with ``frontend_url``,
    so a link in an email can only ever point at our own frontend."""
    for key, value in context.items():
        if key.endswith("_url") and not (
            isinstance(value, str) and value.startswith("/") and not value.startswith("//")
        ):
            raise ValueError(f"Email context {key!r} must be a path starting with '/'")


def _render(template: str, locale: str, context: dict[str, Any]) -> tuple[str, str, str, str]:
    effective = _resolve_locale(template, locale)
    _check_link_paths(context)
    full_context = {
        **context,
        "app_name": APP_NAME,
        "frontend_url": settings.FRONTEND_URL.rstrip("/"),
        "year": datetime.now(UTC).year,
        "locale": effective,
    }
    try:
        subject, text, html = (
            _env.get_template(name).render(full_context)
            for name in _template_names(template, effective)
        )
    except TemplateNotFound as exc:  # pragma: no cover - guarded by _resolve_locale
        raise EmailTemplateNotFound(str(exc)) from exc
    # One line only: a newline in a header would be a header-injection vector.
    subject = " ".join(subject.split())
    return subject, text, html, effective


def render_email(template: str, locale: str, context: dict[str, Any]) -> tuple[str, str, str]:
    """Render ``(subject, text, html)`` for ``template`` in ``locale`` (falling back to en)."""
    subject, text, html, _ = _render(template, locale, context)
    return subject, text, html


async def send_email(
    *,
    to: str,
    template: str,
    locale: str,
    context: dict[str, Any],
    backend: EmailBackend | None = None,
) -> OutgoingEmail:
    """Render and send one email. Returns what was sent; SMTP errors propagate to the caller."""
    subject, text, html, effective = _render(template, locale, context)
    msg = OutgoingEmail(to=to, subject=subject, text=text, html=html, locale=effective)
    try:
        await (backend or get_backend()).send(msg)
    except Exception as exc:
        structlog.get_logger(__name__).error(
            "email.send_failed", template=template, to=to, error=type(exc).__name__
        )
        raise
    return msg


_backend: EmailBackend | None = None


def get_backend() -> EmailBackend:
    """The process-wide backend chosen from settings (cached; see ``reset_backend``)."""
    global _backend
    if _backend is None:
        if settings.ENV == "test":
            _backend = OutboxBackend()
        elif not settings.EMAIL_ENABLED:
            _backend = LoggingBackend()
        else:
            _backend = SmtpBackend()
    return _backend


def reset_backend() -> None:
    """Forget the cached backend (tests that change settings)."""
    global _backend
    _backend = None
