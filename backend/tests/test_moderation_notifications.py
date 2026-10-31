"""Increment 5i: emails to authors when their post or discussion is approved or rejected.

Unit tests call :func:`notify_moderation_decision` on rows flushed in ``db_session`` (rolled
back) and read the ``outbox``. Endpoint tests drive the moderation actions: the email is sent by
a background task after the commit (httpx's ``ASGITransport`` runs background tasks before it
returns, so the outbox is filled when ``client.post`` returns). The auto-approve sweep is driven
through ``run_maintenance`` with a session factory joined to an outer, rolled-back transaction.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import moderation
from app.db.enums import CategoryKind, ContentStatus, ContentType, HiddenReason
from app.db.models import AuditLog, NotificationPreference, User
from app.services import notifications, scheduler
from app.services.email import render_email
from app.services.notifications import (
    SETTINGS_PATH,
    notify_moderation_decision,
    send_moderation_decision,
)
from app.services.scheduler import run_maintenance
from tests.factories import (
    create_admin,
    create_category,
    create_post,
    create_thread,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
MOD = f"{API}/moderation"
FRONTEND = settings.FRONTEND_URL.rstrip("/")
POST_TITLE = "Green roofs in Ljubljana"
THREAD_TITLE = "Sizing retention ponds"
CO_FUNDED = "co-funded by the European Union"
TRUSTED_SENTENCE = "From now on, your posts and discussions are published immediately"
NOT_PUBLIC = "It is not public"
BY_ADMIN = "An admin approved"
AUTOMATIC = "published automatically"
CONTACT_EMAIL = "louta" + "@uowm.gr"
EDIT_OR_DELETE = "edit or delete it"
NOTE_LABEL = "The admin's note:"
RESUBMIT_SENTENCE = "send it for approval again"
NOW = datetime.now(UTC)

P = ContentStatus.PENDING
PUB = ContentStatus.PUBLISHED
H = ContentStatus.HIDDEN


# --- helpers ----------------------------------------------------------------------------------


async def _member(db, **kwargs) -> User:
    """A verified member who has switched the member notifications on (they are off by default
    since 2026-10-31; see the "preference" section)."""
    return await create_verified_user(db, notify=True, **kwargs)


async def _content(db, content_type: ContentType, author: User | None, *, status, **kwargs):
    if content_type == ContentType.POST:
        category = await create_category(db)
        return await create_post(
            db,
            category_id=category.id,
            author_id=author.id if author else None,
            status=status,
            title=POST_TITLE,
            **kwargs,
        )
    category = await create_category(db, kind=CategoryKind.FORUM)
    return await create_thread(
        db,
        category_id=category.id,
        author_id=author.id if author else None,
        status=status,
        title=THREAD_TITLE,
        **kwargs,
    )


async def _approved(db, content_type: ContentType = ContentType.POST, **user_kwargs):
    author = await _member(db, display_name="Petra Poster", **user_kwargs)
    content = await _content(db, content_type, author, status=PUB)
    return author, content


async def _rejected(db, content_type: ContentType = ContentType.POST, **user_kwargs):
    author = await _member(db, display_name="Petra Poster", **user_kwargs)
    content = await _content(
        db, content_type, author, status=H, hidden_reason=HiddenReason.REJECTED
    )
    return author, content


def _link(content_type: ContentType, slug: str) -> str:
    path = f"/blog/{slug}" if content_type == ContentType.POST else f"/forum/t/{slug}"
    return f"{FRONTEND}{path}"


# --- preference -------------------------------------------------------------------------------


async def test_preference_defaults_to_off(db_session) -> None:
    user = await create_verified_user(db_session)
    preferences = await db_session.get(NotificationPreference, user.id)
    await db_session.refresh(preferences)
    assert preferences.moderation_decisions is False


async def test_column_default_is_false(db_session) -> None:
    """Migration 0009 switched the server default from true to false."""
    row = (
        await db_session.execute(
            text(
                "SELECT data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_name = 'notification_preferences' "
                "AND column_name = 'moderation_decisions'"
            )
        )
    ).one()
    assert row.data_type == "boolean"
    assert row.is_nullable == "NO"
    assert row.column_default == "false"


@pytest.mark.parametrize(
    ("decision", "status", "extra"),
    [("approved", PUB, {}), ("rejected", H, {"hidden_reason": HiddenReason.REJECTED})],
)
async def test_default_preferences_get_no_decision_email(
    db_session, outbox, decision, status, extra
) -> None:
    author = await create_verified_user(db_session)
    post = await _content(db_session, ContentType.POST, author, status=status, **extra)

    sent = await notify_moderation_decision(
        db_session, content=post, decision=decision, newly_trusted=True
    )

    assert sent is None
    assert outbox == []


async def test_preference_off_sends_nothing(db_session, outbox) -> None:
    author, post = await _approved(db_session)
    preferences = await db_session.get(NotificationPreference, author.id)
    preferences.moderation_decisions = False
    await db_session.flush()

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=True
    )

    assert sent is None
    assert outbox == []


async def test_missing_preferences_row_counts_as_the_defaults(db_session, outbox) -> None:
    author, post = await _approved(db_session)
    await db_session.delete(await db_session.get(NotificationPreference, author.id))
    await db_session.flush()

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False
    )

    assert sent is None
    assert outbox == []


# --- email content ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("content_type", "label"),
    [(ContentType.POST, "post"), (ContentType.THREAD, "discussion")],
)
async def test_approved_email(db_session, outbox, content_type, label) -> None:
    author, content = await _approved(db_session, content_type)

    sent = await notify_moderation_decision(
        db_session, content=content, decision="approved", newly_trusted=False
    )

    assert sent is not None
    assert outbox == [sent]
    assert sent.to == author.email
    assert sent.template == "content_approved"
    assert sent.locale == "en"
    assert label in sent.subject
    assert content.title in sent.subject
    link = _link(content_type, content.slug)
    for body in (sent.text, sent.html):
        assert "Petra Poster" in body
        assert content.title in body
        assert f"your {label}" in body.lower()
        assert "now public" in body
        assert CO_FUNDED in body
    assert link in sent.text
    assert f'href="{link}"' in sent.html
    assert f"{FRONTEND}{SETTINGS_PATH}" in sent.text
    assert f'href="{FRONTEND}{SETTINGS_PATH}"' in sent.html.replace("&amp;", "&")


@pytest.mark.parametrize(
    ("content_type", "label"),
    [(ContentType.POST, "post"), (ContentType.THREAD, "discussion")],
)
async def test_rejected_email(db_session, outbox, content_type, label) -> None:
    author, content = await _rejected(db_session, content_type)

    sent = await notify_moderation_decision(
        db_session, content=content, decision="rejected", newly_trusted=False
    )

    assert sent is not None
    assert sent.to == author.email
    assert sent.template == "content_rejected"
    assert label in sent.subject
    assert content.title in sent.subject
    link = _link(content_type, content.slug)
    for body in (sent.text, sent.html):
        assert "Petra Poster" in body
        assert content.title in body
        assert NOT_PUBLIC in body
        assert EDIT_OR_DELETE in body
        assert CONTACT_EMAIL in body
        assert TRUSTED_SENTENCE not in body
        assert "now public" not in body
    assert link in sent.text
    assert f'href="{link}"' in sent.html
    assert f'href="mailto:{CONTACT_EMAIL}"' in sent.html


async def test_rejected_email_includes_the_note(db_session, outbox) -> None:
    _, post = await _rejected(db_session)
    post.moderation_note = "Add the rainfall data."
    await db_session.flush()

    sent = await notify_moderation_decision(
        db_session, content=post, decision="rejected", newly_trusted=False
    )

    assert sent is not None
    assert f"{NOTE_LABEL} Add the rainfall data." in sent.text
    assert "Add the rainfall data." in sent.html
    assert "The admin&#39;s note:" in sent.html or NOTE_LABEL in sent.html
    for body in (sent.text, sent.html):
        assert RESUBMIT_SENTENCE in body


async def test_rejected_email_without_note_has_no_note_line(db_session, outbox) -> None:
    _, post = await _rejected(db_session)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="rejected", newly_trusted=False
    )

    assert sent is not None
    for body in (sent.text, sent.html):
        assert NOTE_LABEL not in body
        assert "The admin&#39;s note:" not in body
        assert RESUBMIT_SENTENCE in body


async def test_approved_email_never_has_the_resubmit_sentence(db_session, outbox) -> None:
    _, post = await _approved(db_session)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False
    )

    assert sent is not None
    assert RESUBMIT_SENTENCE not in sent.text


def test_contact_email_is_a_setting() -> None:
    assert settings.CONTACT_EMAIL == CONTACT_EMAIL


async def test_rejected_email_uses_the_contact_setting(db_session, outbox, monkeypatch) -> None:
    monkeypatch.setattr(settings, "CONTACT_EMAIL", "help@example.org")
    _, post = await _rejected(db_session)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="rejected", newly_trusted=False
    )

    assert sent is not None
    assert "help@example.org" in sent.text
    assert CONTACT_EMAIL not in sent.text


@pytest.mark.parametrize(
    ("automatic", "present", "absent"),
    [(False, BY_ADMIN, AUTOMATIC), (True, AUTOMATIC, BY_ADMIN)],
    ids=["by-admin", "automatic"],
)
async def test_approval_wording_by_admin_or_automatic(
    db_session, outbox, automatic, present, absent
) -> None:
    _, post = await _approved(db_session)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False, automatic=automatic
    )

    assert sent is not None
    for body in (sent.text, sent.html):
        assert present in body
        assert absent not in body
    if automatic:
        assert "admin" not in sent.text.split("You received this email")[0].lower()


async def test_acting_admin_gets_no_email_about_own_content(db_session, outbox) -> None:
    admin = await create_admin(db_session)
    post = await _content(db_session, ContentType.POST, admin, status=PUB)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False, actor_id=admin.id
    )

    assert sent is None
    assert outbox == []


async def test_other_actor_does_not_block_the_email(db_session, outbox) -> None:
    admin = await create_admin(db_session)
    _, post = await _approved(db_session)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False, actor_id=admin.id
    )

    assert sent is not None


def _render_context(link: str) -> dict:
    return {
        "display_name": "Petra",
        "content_type_label": "post",
        "title": "T",
        "link_url": link,
        "settings_url": SETTINGS_PATH,
        "newly_trusted": False,
        "automatic": False,
        "reason": None,
        "contact_email": CONTACT_EMAIL,
    }


@pytest.mark.parametrize("template", ["content_approved", "content_rejected"])
def test_templates_link_through_link_url(template) -> None:
    _, text_body, html = render_email(template, "en", _render_context("/blog/some-post"))
    assert f"{FRONTEND}/blog/some-post" in text_body
    assert f'href="{FRONTEND}/blog/some-post"' in html


@pytest.mark.parametrize("template", ["content_approved", "content_rejected"])
@pytest.mark.parametrize("link", ["https://evil.example/x", "//evil.example/x"])
def test_item_link_must_be_site_relative(template, link) -> None:
    with pytest.raises(ValueError):
        render_email(template, "en", _render_context(link))


@pytest.mark.parametrize("newly_trusted", [True, False])
async def test_trusted_sentence_only_when_newly_trusted(db_session, outbox, newly_trusted) -> None:
    _, post = await _approved(db_session)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=newly_trusted
    )

    assert sent is not None
    for body in (sent.text, sent.html):
        assert (TRUSTED_SENTENCE in body) is newly_trusted


async def test_greek_author_falls_back_to_english(db_session, outbox) -> None:
    _, post = await _approved(db_session, locale="el")

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False
    )

    assert sent is not None
    assert sent.locale == "en"
    assert 'lang="en"' in sent.html
    assert CO_FUNDED in sent.text


async def test_unknown_decision_is_an_error(db_session, outbox) -> None:
    _, post = await _approved(db_session)

    with pytest.raises(ValueError):
        await notify_moderation_decision(
            db_session, content=post, decision="maybe", newly_trusted=False
        )
    assert outbox == []


# --- crud: who became trusted ----------------------------------------------------------------


async def test_approve_reports_whether_the_author_became_trusted(db_session) -> None:
    admin = await create_admin(db_session)
    author = await _member(db_session)
    first = await _content(db_session, ContentType.POST, author, status=P)
    second = await _content(db_session, ContentType.THREAD, author, status=P)

    one = await moderation.approve(db_session, content=first, actor=admin)
    two = await moderation.approve(db_session, content=second, actor=admin)

    assert one == (first, True, True)
    assert two == (second, True, False)


@pytest.mark.parametrize(
    ("reason", "expected"), [(HiddenReason.REJECTED, True), (HiddenReason.ADMIN, False)]
)
async def test_unhide_reports_whether_the_author_became_trusted(
    db_session, reason, expected
) -> None:
    admin = await create_admin(db_session)
    author = await _member(db_session)
    post = await _content(db_session, ContentType.POST, author, status=H, hidden_reason=reason)
    if reason == HiddenReason.ADMIN:
        post.published_at = NOW
        await db_session.flush()

    result = await moderation.unhide(db_session, content=post, actor=admin)

    assert result.content is post
    assert result.approved is expected
    assert result.newly_trusted is expected


# --- skipped recipients and stale decisions ---------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"is_verified": False},
        {"is_active": False},
        {"deleted_at": datetime(2026, 1, 1, tzinfo=UTC)},
    ],
    ids=["unverified", "inactive", "anonymised"],
)
async def test_ineligible_author_gets_nothing(db_session, outbox, change) -> None:
    author, post = await _approved(db_session)
    for name, value in change.items():
        setattr(author, name, value)
    await db_session.flush()

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False
    )

    assert sent is None
    assert outbox == []


async def test_content_without_author_sends_nothing(db_session, outbox) -> None:
    post = await _content(db_session, ContentType.POST, None, status=PUB)

    sent = await notify_moderation_decision(
        db_session, content=post, decision="approved", newly_trusted=False
    )

    assert sent is None
    assert outbox == []


@pytest.mark.parametrize(
    ("status", "decision", "extra"),
    [
        (P, "approved", {}),
        (H, "approved", {"hidden_reason": HiddenReason.ADMIN}),
        (PUB, "rejected", {}),
        (H, "rejected", {"hidden_reason": HiddenReason.ADMIN}),
    ],
    ids=["approved-but-pending", "approved-but-hidden", "rejected-but-published", "admin-hidden"],
)
async def test_decision_that_no_longer_holds_sends_nothing(
    db_session, outbox, status, decision, extra
) -> None:
    author = await _member(db_session)
    post = await _content(db_session, ContentType.POST, author, status=status, **extra)

    sent = await notify_moderation_decision(
        db_session, content=post, decision=decision, newly_trusted=False
    )

    assert sent is None
    assert outbox == []


async def test_sent_log_has_ids_but_no_address(db_session, outbox) -> None:
    author, post = await _approved(db_session)

    with structlog.testing.capture_logs() as logs:
        await notify_moderation_decision(
            db_session, content=post, decision="approved", newly_trusted=False
        )

    sent = [e for e in logs if e["event"] == "notification.sent"]
    assert len(sent) == 1
    assert sent[0]["kind"] == "content_approved"
    assert sent[0]["recipient_id"] == author.id
    assert sent[0]["content_id"] == post.id
    assert author.email not in repr(logs)


# --- background runner ------------------------------------------------------------------------


async def test_runner_ignores_missing_content(database_url, outbox) -> None:
    await send_moderation_decision(ContentType.POST, 2**30, "approved", False)
    await send_moderation_decision(ContentType.THREAD, 2**30, "rejected", False)
    assert outbox == []


async def test_runner_reads_committed_state_only(db_session, outbox) -> None:
    """The runner opens its own session: an approval not yet committed is not seen, so nothing
    goes out before the commit."""
    author = await _member(db_session)
    post = await _content(db_session, ContentType.POST, author, status=P)
    await moderation.approve(db_session, content=post, actor=author)
    assert post.status == PUB  # flushed in this (uncommitted) transaction only

    await send_moderation_decision(ContentType.POST, post.id, "approved", True)

    assert outbox == []


async def test_runner_logs_and_swallows_failures(database_url, outbox, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(notifications, "AsyncSessionLocal", boom)
    with structlog.testing.capture_logs() as logs:
        await send_moderation_decision(ContentType.POST, 7, "approved", False)

    failed = [e for e in logs if e["event"] == "notification.failed"]
    assert len(failed) == 1
    assert failed[0]["kind"] == "moderation_decision"
    assert failed[0]["content_id"] == 7
    assert failed[0]["error"] == "RuntimeError"


# --- endpoints --------------------------------------------------------------------------------


@pytest.fixture
def env(db_session, cleanup_users, cleanup_forum_categories):
    class Env:
        db = db_session
        users = cleanup_users
        categories = cleanup_forum_categories

    return Env


async def _user(env, factory=None, **kwargs) -> User:
    user = await (factory or _member)(env.db, **kwargs)
    env.users.add(user.email)
    await env.db.commit()
    return user


async def _committed(env, content_type: ContentType, author: User | None, *, status, **kwargs):
    kind = CategoryKind.BLOG if content_type == ContentType.POST else CategoryKind.FORUM
    category = await create_category(env.db, kind=kind)
    env.categories.add(category.id)
    if content_type == ContentType.POST:
        factory, title = create_post, POST_TITLE
    else:
        factory, title = create_thread, THREAD_TITLE
    content = await factory(
        env.db,
        category_id=category.id,
        author_id=author.id if author else None,
        status=status,
        title=title,
        **kwargs,
    )
    await env.db.commit()
    return content


async def _admin(client, env) -> User:
    admin = await _user(env, factory=create_admin)
    await login_as(client, admin)
    return admin


def _url(content_type: ContentType, content_id: int, action: str) -> str:
    return f"{MOD}/{content_type.value}/{content_id}/{action}"


async def _audit_actions(db, content_type: ContentType, content_id: int, author_id: int):
    stmt = (
        select(AuditLog.action)
        .where(
            ((AuditLog.target_type == content_type.value) & (AuditLog.target_id == content_id))
            | ((AuditLog.target_type == "user") & (AuditLog.target_id == author_id))
        )
        .order_by(AuditLog.id)
    )
    return list((await db.scalars(stmt)).all())


@pytest.mark.parametrize("content_type", [ContentType.POST, ContentType.THREAD])
async def test_approve_endpoint_emails_newly_trusted_author(
    client, env, outbox, content_type
) -> None:
    author = await _user(env, display_name="Petra Poster")
    content = await _committed(env, content_type, author, status=P)
    await _admin(client, env)

    response = await client.post(_url(content_type, content.id, "approve"))

    assert response.status_code == 200, response.text
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.to == author.email
    assert msg.template == "content_approved"
    assert TRUSTED_SENTENCE in msg.text
    assert BY_ADMIN in msg.text
    assert _link(content_type, content.slug) in msg.text


async def test_approve_endpoint_for_trusted_author_omits_trusted_sentence(
    client, env, outbox
) -> None:
    author = await _user(env, trusted_at=NOW - timedelta(days=5))
    post = await _committed(env, ContentType.POST, author, status=P)
    await _admin(client, env)

    response = await client.post(_url(ContentType.POST, post.id, "approve"))

    assert response.status_code == 200, response.text
    assert len(outbox) == 1
    assert TRUSTED_SENTENCE not in outbox[0].text


async def test_approve_endpoint_audit_is_unchanged(client, env, outbox) -> None:
    author = await _user(env)
    post = await _committed(env, ContentType.POST, author, status=P)
    await _admin(client, env)

    response = await client.post(_url(ContentType.POST, post.id, "approve"))

    assert response.status_code == 200, response.text
    assert len(outbox) == 1
    assert await _audit_actions(env.db, ContentType.POST, post.id, author.id) == [
        "moderation.approve",
        "user.trusted",
    ]


async def test_reject_endpoint_emails_author_with_reason(client, env, outbox) -> None:
    author = await _user(env)
    thread = await _committed(env, ContentType.THREAD, author, status=P)
    await _admin(client, env)
    reason = "Please cite <the> sources & add a map."

    response = await client.post(
        _url(ContentType.THREAD, thread.id, "reject"), json={"reason": reason}
    )

    assert response.status_code == 200, response.text
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.to == author.email
    assert msg.template == "content_rejected"
    assert "discussion" in msg.subject
    assert reason not in msg.subject
    assert f"{NOTE_LABEL} {reason}" in msg.text
    assert "Please cite &lt;the&gt; sources &amp; add a map." in msg.html
    assert "<the>" not in msg.html
    for body in (msg.text, msg.html):
        assert RESUBMIT_SENTENCE in body
    assert await _audit_actions(env.db, ContentType.THREAD, thread.id, author.id) == [
        "moderation.reject"
    ]


async def test_unhide_rejected_emails_approval(client, env, outbox) -> None:
    author = await _user(env)
    post = await _committed(
        env, ContentType.POST, author, status=H, hidden_reason=HiddenReason.REJECTED
    )
    await _admin(client, env)

    response = await client.post(_url(ContentType.POST, post.id, "unhide"))

    assert response.status_code == 200, response.text
    assert len(outbox) == 1
    assert outbox[0].template == "content_approved"
    assert TRUSTED_SENTENCE in outbox[0].text


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_admin_deciding_own_content_gets_no_email(client, env, outbox, action) -> None:
    admin = await _admin(client, env)
    post = await _committed(env, ContentType.POST, admin, status=P)

    response = await client.post(_url(ContentType.POST, post.id, action))

    assert response.status_code == 200, response.text
    assert outbox == []


async def test_hide_and_unhide_by_admin_send_nothing(client, env, outbox) -> None:
    author = await _user(env)
    post = await _committed(env, ContentType.POST, author, status=PUB)
    await _admin(client, env)

    assert (await client.post(_url(ContentType.POST, post.id, "hide"))).status_code == 200
    assert (await client.post(_url(ContentType.POST, post.id, "unhide"))).status_code == 200

    assert outbox == []


async def test_endpoint_respects_preference(client, env, outbox) -> None:
    author = await _user(env)
    preferences = await env.db.get(NotificationPreference, author.id)
    preferences.moderation_decisions = False
    await env.db.commit()
    post = await _committed(env, ContentType.POST, author, status=P)
    await _admin(client, env)

    response = await client.post(_url(ContentType.POST, post.id, "approve"))

    assert response.status_code == 200, response.text
    assert outbox == []


@pytest.mark.parametrize("action", ["approve", "reject"])
async def test_endpoint_sends_nothing_with_default_preferences(client, env, outbox, action) -> None:
    """A member who never opened the Notifications tab gets no approval or rejection email."""
    author = await _user(env, factory=create_verified_user)
    post = await _committed(env, ContentType.POST, author, status=P)
    await _admin(client, env)

    body = {"reason": "Off topic"} if action == "reject" else None
    response = await client.post(_url(ContentType.POST, post.id, action), json=body)

    assert response.status_code == 200, response.text
    assert outbox == []


async def test_endpoint_survives_send_failure(client, env, outbox, monkeypatch) -> None:
    author = await _user(env)
    post = await _committed(env, ContentType.POST, author, status=P)
    await _admin(client, env)

    async def failing_send(**kwargs):
        raise ConnectionError("smtp down")

    monkeypatch.setattr("app.services.email.send_email", failing_send)
    with structlog.testing.capture_logs() as logs:
        response = await client.post(_url(ContentType.POST, post.id, "approve"))

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "published"
    assert outbox == []
    failed = [e for e in logs if e["event"] == "notification.failed"]
    assert len(failed) == 1
    assert failed[0]["content_id"] == post.id
    assert author.email not in repr(logs)


# --- auto-approve sweep -----------------------------------------------------------------------


@pytest.fixture
async def tx_factory(database_url: str) -> AsyncIterator[Callable[[], AsyncSession]]:
    """Sessions joined to one outer transaction (commits become savepoint releases)."""
    from app.db.session import engine

    async with engine.connect() as conn:
        outer = await conn.begin()

        def factory() -> AsyncSession:
            return AsyncSession(
                bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
            )

        try:
            yield factory
        finally:
            await outer.rollback()


async def test_auto_approve_collects_decisions(db_session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 2)
    author = await _member(db_session)
    trusted = await _member(db_session, trusted_at=NOW - timedelta(days=9))
    old = await _content(
        db_session, ContentType.POST, author, status=P, created_at=NOW - timedelta(days=3)
    )
    second = await _content(
        db_session, ContentType.THREAD, author, status=P, created_at=NOW - timedelta(days=3)
    )
    by_trusted = await _content(
        db_session, ContentType.THREAD, trusted, status=P, created_at=NOW - timedelta(days=3)
    )
    decisions: list[moderation.ApprovedItem] = []

    count = await moderation.auto_approve_stale(db_session, now=NOW, approved=decisions)

    assert count == len(decisions)
    mine = {(d.content_type, d.content_id): d.newly_trusted for d in decisions}
    assert mine[(ContentType.POST, old.id)] is True
    # Trusted by the first approval in this sweep, so not "newly" for the second.
    assert mine[(ContentType.THREAD, second.id)] is False
    assert mine[(ContentType.THREAD, by_trusted.id)] is False


async def test_sweep_emails_authors_after_commit(tx_factory, outbox, monkeypatch) -> None:
    async with tx_factory() as db:
        author = await _member(db, display_name="Petra Poster")
        category = await create_category(db)
        post = await create_post(
            db,
            category_id=category.id,
            author_id=author.id,
            status=P,
            title=POST_TITLE,
            created_at=NOW - timedelta(days=10),
        )
        slug, email = post.slug, author.email
        await db.commit()
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 7)

    with structlog.testing.capture_logs() as logs:
        counts = await run_maintenance(NOW, session_factory=tx_factory)

    assert counts["auto_approved"] >= 1
    mine = [m for m in outbox if m.to == email]
    assert len(mine) == 1
    assert mine[0].template == "content_approved"
    assert TRUSTED_SENTENCE in mine[0].text
    assert AUTOMATIC in mine[0].text
    assert BY_ADMIN not in mine[0].text
    assert f"{FRONTEND}/blog/{slug}" in mine[0].text
    sweep = [e for e in logs if e["event"] == "maintenance.decision_emails"]
    assert len(sweep) == 1
    assert 1 <= sweep[0]["count"] <= counts["auto_approved"]
    assert set(sweep[0]) <= {"event", "log_level", "count", "remaining", "step"}
    assert email not in repr(logs)


async def test_sweep_rolled_back_sends_nothing(tx_factory, outbox, monkeypatch) -> None:
    async with tx_factory() as db:
        author = await _member(db)
        category = await create_category(db)
        await create_post(
            db,
            category_id=category.id,
            author_id=author.id,
            status=P,
            created_at=NOW - timedelta(days=10),
        )
        email = author.email
        await db.commit()
    monkeypatch.setattr(settings, "AUTO_APPROVE_AFTER_DAYS", 7)
    real = moderation.auto_approve_stale

    async def approve_then_fail(db, **kwargs):
        await real(db, **kwargs)
        raise RuntimeError("audit down")

    monkeypatch.setattr(
        "app.services.scheduler.crud_moderation.auto_approve_stale", approve_then_fail
    )

    counts = await run_maintenance(NOW, session_factory=tx_factory)

    assert counts["auto_approved"] == -1
    assert [m for m in outbox if m.to == email] == []


def _items(n: int) -> list[moderation.ApprovedItem]:
    return [moderation.ApprovedItem(ContentType.POST, i + 1, False) for i in range(n)]


async def test_sweep_emails_are_capped_per_run(monkeypatch) -> None:
    calls: list[tuple] = []

    async def fake_send(content_type, content_id, decision, newly_trusted, **kwargs):
        calls.append((content_type, content_id, decision, kwargs.get("automatic")))
        return True

    monkeypatch.setattr(scheduler.notifications, "send_moderation_decision", fake_send)
    monkeypatch.setattr(scheduler, "MAX_DECISION_EMAILS_PER_RUN", 3)

    with structlog.testing.capture_logs() as logs:
        await scheduler._send_decision_emails(_items(5), lambda: None)

    assert sorted(c[1] for c in calls) == [1, 2, 3]
    assert all(c[2] == "approved" and c[3] is True for c in calls)
    (line,) = [e for e in logs if e["event"] == "maintenance.decision_emails"]
    assert line["count"] == 3
    assert line["remaining"] == 2


def test_default_cap() -> None:
    assert scheduler.MAX_DECISION_EMAILS_PER_RUN == 100


async def test_sweep_emails_run_at_most_three_at_a_time(monkeypatch) -> None:
    active = 0
    peak = 0
    done: list[int] = []

    async def fake_send(content_type, content_id, decision, newly_trusted, **kwargs):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01)
        active -= 1
        done.append(content_id)
        return content_id % 2 == 0

    monkeypatch.setattr(scheduler.notifications, "send_moderation_decision", fake_send)

    with structlog.testing.capture_logs() as logs:
        await scheduler._send_decision_emails(_items(10), lambda: None)

    assert sorted(done) == list(range(1, 11))
    assert peak == 3
    (line,) = [e for e in logs if e["event"] == "maintenance.decision_emails"]
    assert line["count"] == 5
    assert line["remaining"] == 0


# --- one-click unsubscribe header -------------------------------------------------------------


@pytest.mark.parametrize("decision", ["approved", "rejected"])
async def test_decision_email_carries_the_moderation_decisions_token(
    db_session, outbox, decision
) -> None:
    from urllib.parse import parse_qs, urlsplit

    from app.services.unsubscribe import read_token

    make = _approved if decision == "approved" else _rejected
    author, content = await make(db_session)

    sent = await notify_moderation_decision(
        db_session, content=content, decision=decision, newly_trusted=False
    )

    assert sent.list_unsubscribe.startswith(
        f"{FRONTEND}{settings.API_V1_PREFIX}/notifications/unsubscribe?token="
    )
    token = parse_qs(urlsplit(sent.list_unsubscribe).query)["token"][0]
    assert read_token(token) == (author.id, "moderation_decisions")
