"""Transactional email: Jinja2 templates per locale (English fallback) and pluggable backends.

Templates live in ``app/templates/email/<locale>/<template>.{subject.txt,txt.j2,html.j2}``. If any
of the three files is missing for the requested locale, all three are taken from ``en``.

Backends: ``OutboxBackend`` in tests (in-memory list), ``LoggingBackend`` when email is disabled
outside tests, ``SmtpBackend`` (aiosmtplib) otherwise. Bodies are never logged: they carry tokens.

Deliverability: every message is marked ``Auto-Submitted: auto-generated`` (RFC 3834). The
notification emails a member can switch off also carry ``List-Unsubscribe`` and
``List-Unsubscribe-Post: List-Unsubscribe=One-Click`` (RFC 8058), pointing at the signed one-click
endpoint (see ``services/unsubscribe.py``). Link text in the HTML parts never shows an address:
the SMTP relay rewrites every link for click tracking, and a visible address that differs from
the real target is a phishing signal to spam filters.
"""

from __future__ import annotations

import hashlib
import hmac
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
    # The template name, for logs that must not carry the address or the subject.
    template: str = ""
    # Absolute https URL of the one-click unsubscribe endpoint (notification emails only).
    list_unsubscribe: str | None = None


class EmailBackend(Protocol):
    async def send(self, msg: OutgoingEmail) -> None: ...


class OutboxBackend:
    """Collects messages in memory. Used in tests (see the ``outbox`` fixture)."""

    def __init__(self) -> None:
        self.messages: list[OutgoingEmail] = []

    async def send(self, msg: OutgoingEmail) -> None:
        self.messages.append(msg)


def address_hash(address: str) -> str:
    """Keyed, truncated hash of an address for logs: correlatable within one deployment, never
    the address itself (a recipient is personal data, and subjects may name other members)."""
    key = settings.SECRET_KEY.encode()
    return hmac.new(key, address.casefold().encode(), hashlib.sha256).hexdigest()[:12]


class LoggingBackend:
    """Email disabled outside tests: log the template and a keyed hash of the address only;
    never the address, the subject or the bodies."""

    async def send(self, msg: OutgoingEmail) -> None:
        structlog.get_logger(__name__).info(
            "email.not_sent",
            reason="EMAIL_ENABLED=false",
            template=msg.template,
            locale=msg.locale,
            to_hash=address_hash(msg.to),
        )


class SmtpBackend:
    """Send through SMTP with aiosmtplib: STARTTLS on 587, implicit TLS on 465, plain otherwise
    (Mailpit in dev). Logs in only when ``SMTP_USER`` is set. Adds ``Reply-To`` when
    ``SMTP_REPLY_TO`` is set, ``Auto-Submitted`` always and the RFC 8058 one-click
    ``List-Unsubscribe`` pair when the message has an unsubscribe URL."""

    def build_message(self, msg: OutgoingEmail) -> EmailMessage:
        message = EmailMessage()
        message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM))
        message["To"] = msg.to
        if settings.SMTP_REPLY_TO:
            message["Reply-To"] = settings.SMTP_REPLY_TO
        message["Subject"] = msg.subject
        message["Date"] = formatdate(usegmt=True)
        domain = settings.SMTP_FROM.rpartition("@")[2] or None
        message["Message-ID"] = make_msgid(domain=domain)
        message["Auto-Submitted"] = "auto-generated"
        if msg.list_unsubscribe:
            message["List-Unsubscribe"] = f"<{msg.list_unsubscribe}>"
            message["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
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


def _check_list_unsubscribe(url: str | None) -> None:
    """An unsubscribe URL becomes a header: absolute http(s), no whitespace or angle brackets
    (header injection, and ``<…>`` delimits it)."""
    if url is None:
        return
    if not url.startswith(("https://", "http://")) or any(c.isspace() or c in "<>" for c in url):
        raise ValueError("list_unsubscribe must be an absolute http(s) URL without whitespace")


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
    list_unsubscribe: str | None = None,
) -> OutgoingEmail:
    """Render and send one email. Returns what was sent; SMTP errors propagate to the caller.
    ``list_unsubscribe``: the one-click unsubscribe URL, only for emails a member can switch
    off."""
    _check_list_unsubscribe(list_unsubscribe)
    subject, text, html, effective = _render(template, locale, context)
    msg = OutgoingEmail(
        to=to,
        subject=subject,
        text=text,
        html=html,
        locale=effective,
        template=template,
        list_unsubscribe=list_unsubscribe,
    )
    try:
        await (backend or get_backend()).send(msg)
    except Exception as exc:
        # Never log the address: a recipient is personal data (see docs/legal/privacy-policy.md).
        structlog.get_logger(__name__).error(
            "email.send_failed", template=template, error=type(exc).__name__
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
