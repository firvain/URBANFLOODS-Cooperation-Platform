"""Increment 3e: notification emails (reply to my thread, reply to my reply, comment on my post).

Unit tests call the service functions on rows flushed in ``db_session`` (rolled back after each
test) and read the ``outbox``. Endpoint tests drive ``POST /threads/{id}/replies/`` and
``POST /posts/{id}/comments/``: the email is sent by a background task after the commit.
httpx's ``ASGITransport`` awaits the whole ASGI app (background tasks included) before it
returns the response, so the outbox is filled when ``client.post`` returns.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import structlog

from app.core.config import settings
from app.db.enums import CategoryKind
from app.db.models import NotificationPreference, User
from app.services import notifications
from app.services.notifications import (
    EXCERPT_MAX_LENGTH,
    SETTINGS_PATH,
    make_excerpt,
    notify_comment_on_post,
    notify_reply_to_reply,
    notify_reply_to_thread,
    send_comment_notifications,
    send_reply_notifications,
)
from tests.factories import (
    create_category,
    create_comment,
    create_post,
    create_reply,
    create_thread,
    create_user,
    create_verified_user,
    login_as,
)

API = settings.API_V1_PREFIX
FRONTEND = settings.FRONTEND_URL.rstrip("/")
THREAD_TITLE = "Sizing retention ponds"
POST_TITLE = "Green roofs in Ljubljana"
CO_FUNDED = "co-funded by the European Union"


# --- helpers ----------------------------------------------------------------------------------


async def _thread(db, author: User, **kwargs):
    category = await create_category(db, kind=CategoryKind.FORUM)
    return await create_thread(db, category_id=category.id, author_id=author.id, **kwargs)


async def _post(db, author: User, **kwargs):
    category = await create_category(db)
    return await create_post(db, category_id=category.id, author_id=author.id, **kwargs)


async def _set_preference(db, user: User, name: str, value: bool) -> None:
    preferences = await db.get(NotificationPreference, user.id)
    setattr(preferences, name, value)
    await db.flush()


async def _forum_setup(db):
    """A thread by ``owner`` and a top-level reply on it by ``actor`` (both verified)."""
    owner = await create_verified_user(db, display_name="Olga Owner")
    actor = await create_verified_user(db, display_name="Andrej Actor")
    thread = await _thread(db, owner, title=THREAD_TITLE)
    reply = await create_reply(
        db, thread_id=thread.id, author_id=actor.id, body="We used swales and a basin."
    )
    return owner, actor, thread, reply


# --- excerpt ----------------------------------------------------------------------------------


def test_excerpt_keeps_short_text_and_collapses_whitespace() -> None:
    assert make_excerpt("  We used\n\nswales   and a basin. ") == "We used swales and a basin."


def test_excerpt_truncates_long_text() -> None:
    text = "word " * 100
    excerpt = make_excerpt(text)
    assert len(excerpt) <= EXCERPT_MAX_LENGTH
    assert excerpt.endswith("…")
    assert excerpt.startswith("word word")


def test_excerpt_of_exactly_the_limit_is_unchanged() -> None:
    text = "x" * EXCERPT_MAX_LENGTH
    assert make_excerpt(text) == text


# --- reply to my thread -----------------------------------------------------------------------


async def test_reply_to_thread_emails_thread_author(db_session, outbox) -> None:
    owner, actor, thread, reply = await _forum_setup(db_session)

    sent = await notify_reply_to_thread(db_session, reply=reply)

    assert sent is not None
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.to == owner.email
    assert msg.locale == "en"
    assert "Andrej Actor" in msg.subject
    assert THREAD_TITLE in msg.subject
    link = f"{FRONTEND}/forum/t/{thread.slug}#reply-{reply.id}"
    settings_link = f"{FRONTEND}{SETTINGS_PATH}"
    assert SETTINGS_PATH == "/account?tab=notifications"
    for body in (msg.text, msg.html):
        assert "We used swales and a basin." in body
        assert CO_FUNDED in body
    assert link in msg.text
    assert f'href="{link}"' in msg.html
    assert settings_link in msg.text
    assert f'href="{FRONTEND}/account?tab=notifications"' in msg.html.replace("&amp;", "&")
    assert "Olga Owner" in msg.text


async def test_reply_to_thread_by_thread_author_sends_nothing(db_session, outbox) -> None:
    owner = await create_verified_user(db_session)
    thread = await _thread(db_session, owner)
    reply = await create_reply(db_session, thread_id=thread.id, author_id=owner.id)

    assert await notify_reply_to_thread(db_session, reply=reply) is None
    assert outbox == []


async def test_reply_to_thread_respects_preference(db_session, outbox) -> None:
    owner, _, _, reply = await _forum_setup(db_session)
    await _set_preference(db_session, owner, "reply_to_my_thread", False)

    assert await notify_reply_to_thread(db_session, reply=reply) is None
    assert outbox == []


@pytest.mark.parametrize(
    "change",
    [
        {"is_verified": False},
        {"is_active": False},
        {"deleted_at": datetime(2026, 1, 1, tzinfo=UTC)},
    ],
    ids=["unverified", "inactive", "deleted"],
)
async def test_reply_to_thread_skips_ineligible_recipient(db_session, outbox, change) -> None:
    owner, _, _, reply = await _forum_setup(db_session)
    for name, value in change.items():
        setattr(owner, name, value)
    await db_session.flush()

    assert await notify_reply_to_thread(db_session, reply=reply) is None
    assert outbox == []


async def test_reply_to_thread_without_thread_author_sends_nothing(db_session, outbox) -> None:
    actor = await create_verified_user(db_session)
    category = await create_category(db_session, kind=CategoryKind.FORUM)
    thread = await create_thread(db_session, category_id=category.id, author_id=None)
    reply = await create_reply(db_session, thread_id=thread.id, author_id=actor.id)

    assert await notify_reply_to_thread(db_session, reply=reply) is None
    assert outbox == []


async def test_reply_to_thread_uses_greek_template(db_session, outbox) -> None:
    owner = await create_verified_user(db_session, locale="el")
    actor = await create_verified_user(db_session, display_name="Andrej Actor")
    thread = await _thread(db_session, owner, title=THREAD_TITLE)
    reply = await create_reply(db_session, thread_id=thread.id, author_id=actor.id)

    await notify_reply_to_thread(db_session, reply=reply)

    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.locale == "el"
    assert "απάντησε" in msg.subject
    assert 'lang="el"' in msg.html
    assert "συγχρηματοδοτείται" in msg.text
    assert f"{FRONTEND}/forum/t/{thread.slug}#reply-{reply.id}" in msg.text


async def test_long_reply_is_truncated_in_email(db_session, outbox) -> None:
    owner = await create_verified_user(db_session)
    actor = await create_verified_user(db_session)
    thread = await _thread(db_session, owner)
    long_body = "flood " * 120 + "SECRET-TAIL"
    reply = await create_reply(db_session, thread_id=thread.id, author_id=actor.id, body=long_body)

    await notify_reply_to_thread(db_session, reply=reply)

    msg = outbox[0]
    assert "SECRET-TAIL" not in msg.text
    assert "SECRET-TAIL" not in msg.html
    assert make_excerpt(reply.body_text) in msg.text


# --- reply to my reply ------------------------------------------------------------------------


async def test_nested_reply_notifies_parent_and_thread_authors(db_session, outbox) -> None:
    owner, parent_author, thread, parent = await _forum_setup(db_session)
    actor = await create_verified_user(db_session, display_name="Nina Nested")
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )

    await notify_reply_to_reply(db_session, reply=reply)
    await notify_reply_to_thread(db_session, reply=reply)

    by_recipient = {msg.to: msg for msg in outbox}
    assert set(by_recipient) == {owner.email, parent_author.email}
    to_parent = by_recipient[parent_author.email]
    to_owner = by_recipient[owner.email]
    assert "replied to your reply" in to_parent.subject
    assert "replied to your thread" in to_owner.subject
    for msg in (to_parent, to_owner):
        assert "Nina Nested" in msg.subject
        assert f"{FRONTEND}/forum/t/{thread.slug}#reply-{reply.id}" in msg.text


async def test_nested_reply_same_person_gets_one_email(db_session, outbox) -> None:
    owner = await create_verified_user(db_session)
    actor = await create_verified_user(db_session)
    thread = await _thread(db_session, owner)
    parent = await create_reply(db_session, thread_id=thread.id, author_id=owner.id)
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )

    await notify_reply_to_reply(db_session, reply=reply)
    await notify_reply_to_thread(db_session, reply=reply)

    assert len(outbox) == 1
    assert outbox[0].to == owner.email
    assert "replied to your reply" in outbox[0].subject


async def test_nested_reply_same_person_falls_back_to_thread_email(db_session, outbox) -> None:
    """With ``reply_to_my_reply`` off but ``reply_to_my_thread`` on, the thread email goes out."""
    owner = await create_verified_user(db_session)
    actor = await create_verified_user(db_session)
    thread = await _thread(db_session, owner)
    parent = await create_reply(db_session, thread_id=thread.id, author_id=owner.id)
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )
    await _set_preference(db_session, owner, "reply_to_my_reply", False)

    assert await notify_reply_to_reply(db_session, reply=reply) is None
    assert await notify_reply_to_thread(db_session, reply=reply) is not None

    assert len(outbox) == 1
    assert "replied to your thread" in outbox[0].subject


async def test_reply_to_own_reply_notifies_only_thread_author(db_session, outbox) -> None:
    owner, actor, thread, parent = await _forum_setup(db_session)
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )

    assert await notify_reply_to_reply(db_session, reply=reply) is None
    await notify_reply_to_thread(db_session, reply=reply)

    assert [msg.to for msg in outbox] == [owner.email]


async def test_top_level_reply_has_no_reply_to_reply_email(db_session, outbox) -> None:
    _, _, _, reply = await _forum_setup(db_session)
    assert await notify_reply_to_reply(db_session, reply=reply) is None
    assert outbox == []


async def test_reply_to_reply_respects_preference(db_session, outbox) -> None:
    _, parent_author, thread, parent = await _forum_setup(db_session)
    actor = await create_verified_user(db_session)
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )
    await _set_preference(db_session, parent_author, "reply_to_my_reply", False)

    assert await notify_reply_to_reply(db_session, reply=reply) is None
    assert outbox == []


async def test_reply_to_reply_skips_unverified_parent_author(db_session, outbox) -> None:
    owner = await create_verified_user(db_session)
    parent_author = await create_user(db_session)  # unverified
    actor = await create_verified_user(db_session)
    thread = await _thread(db_session, owner)
    parent = await create_reply(db_session, thread_id=thread.id, author_id=parent_author.id)
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )

    assert await notify_reply_to_reply(db_session, reply=reply) is None
    assert outbox == []


async def test_reply_to_reply_falls_back_to_english_for_greek(db_session, outbox) -> None:
    owner = await create_verified_user(db_session)
    parent_author = await create_verified_user(db_session, locale="el")
    actor = await create_verified_user(db_session)
    thread = await _thread(db_session, owner)
    parent = await create_reply(db_session, thread_id=thread.id, author_id=parent_author.id)
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )

    await notify_reply_to_reply(db_session, reply=reply)

    assert len(outbox) == 1
    assert outbox[0].locale == "en"
    assert "replied to your reply" in outbox[0].subject


# --- comment on my post -----------------------------------------------------------------------


async def test_comment_on_post_emails_post_author(db_session, outbox) -> None:
    author = await create_verified_user(db_session, display_name="Petra Poster")
    actor = await create_verified_user(db_session, display_name="Andrej Actor")
    post = await _post(db_session, author, title=POST_TITLE)
    comment = await create_comment(
        db_session, post_id=post.id, author_id=actor.id, body="Thanks for sharing."
    )

    assert await notify_comment_on_post(db_session, comment=comment) is not None

    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.to == author.email
    assert msg.locale == "en"
    assert "Andrej Actor" in msg.subject
    assert POST_TITLE in msg.subject
    link = f"{FRONTEND}/blog/{post.slug}#comment-{comment.id}"
    assert link in msg.text
    assert f'href="{link}"' in msg.html
    assert f"{FRONTEND}{SETTINGS_PATH}" in msg.text
    for body in (msg.text, msg.html):
        assert "Thanks for sharing." in body
        assert CO_FUNDED in body


async def test_comment_by_post_author_sends_nothing(db_session, outbox) -> None:
    author = await create_verified_user(db_session)
    post = await _post(db_session, author)
    comment = await create_comment(db_session, post_id=post.id, author_id=author.id)

    assert await notify_comment_on_post(db_session, comment=comment) is None
    assert outbox == []


async def test_comment_on_post_respects_preference(db_session, outbox) -> None:
    author = await create_verified_user(db_session)
    actor = await create_verified_user(db_session)
    post = await _post(db_session, author)
    comment = await create_comment(db_session, post_id=post.id, author_id=actor.id)
    await _set_preference(db_session, author, "comment_on_my_post", False)

    assert await notify_comment_on_post(db_session, comment=comment) is None
    assert outbox == []


async def test_comment_on_post_skips_inactive_author(db_session, outbox) -> None:
    author = await create_verified_user(db_session, is_active=False)
    actor = await create_verified_user(db_session)
    post = await _post(db_session, author)
    comment = await create_comment(db_session, post_id=post.id, author_id=actor.id)

    assert await notify_comment_on_post(db_session, comment=comment) is None
    assert outbox == []


async def test_comment_on_post_falls_back_to_english_for_greek(db_session, outbox) -> None:
    author = await create_verified_user(db_session, locale="el")
    actor = await create_verified_user(db_session)
    post = await _post(db_session, author)
    comment = await create_comment(db_session, post_id=post.id, author_id=actor.id)

    await notify_comment_on_post(db_session, comment=comment)

    assert len(outbox) == 1
    assert outbox[0].locale == "en"


# --- logging ----------------------------------------------------------------------------------


async def test_sent_log_has_ids_but_no_address(db_session, outbox) -> None:
    owner, _, _, reply = await _forum_setup(db_session)

    with structlog.testing.capture_logs() as logs:
        await notify_reply_to_thread(db_session, reply=reply)

    events = [e for e in logs if e["event"] == "notification.sent"]
    assert len(events) == 1
    assert events[0]["log_level"] == "info"
    assert events[0]["kind"] == "reply_to_thread"
    assert events[0]["recipient_id"] == owner.id
    assert events[0]["content_id"] == reply.id
    assert owner.email not in repr(logs)


# --- background runners -----------------------------------------------------------------------


async def test_runners_ignore_missing_content(database_url, outbox) -> None:
    await send_reply_notifications(2**62)
    await send_comment_notifications(2**62)
    assert outbox == []


async def test_runner_logs_and_swallows_failures(database_url, outbox, monkeypatch) -> None:
    def boom(*args, **kwargs):
        raise RuntimeError("database down")

    monkeypatch.setattr(notifications, "AsyncSessionLocal", boom)
    with structlog.testing.capture_logs() as logs:
        await send_reply_notifications(7)
        await send_comment_notifications(8)

    failed = [e for e in logs if e["event"] == "notification.failed"]
    assert {(e["kind"], e.get("reply_id"), e.get("comment_id")) for e in failed} == {
        ("reply", 7, None),
        ("comment", None, 8),
    }
    assert all(e["log_level"] == "error" for e in failed)


# --- endpoints --------------------------------------------------------------------------------


async def _committed(db, cleanup_users, **kwargs) -> User:
    user = await create_verified_user(db, **kwargs)
    cleanup_users.add(user.email)
    await db.commit()
    return user


async def _committed_thread(db, cleanup_forum_categories, author: User):
    category = await create_category(db, kind=CategoryKind.FORUM)
    cleanup_forum_categories.add(category.id)
    thread = await create_thread(
        db, category_id=category.id, author_id=author.id, title=THREAD_TITLE
    )
    await db.commit()
    return thread


async def test_create_reply_endpoint_sends_notification(
    client, db_session, cleanup_users, cleanup_forum_categories, outbox
) -> None:
    owner = await _committed(db_session, cleanup_users, locale="el")
    actor = await _committed(db_session, cleanup_users, display_name="Andrej Actor")
    thread = await _committed_thread(db_session, cleanup_forum_categories, owner)
    await login_as(client, actor)

    response = await client.post(
        f"{API}/threads/{thread.id}/replies/", json={"body_html": "<p>Try a swale.</p>"}
    )

    assert response.status_code == 201, response.text
    reply_id = response.json()["id"]
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.to == owner.email
    assert msg.locale == "el"
    assert "Try a swale." in msg.text
    assert f"{FRONTEND}/forum/t/{thread.slug}#reply-{reply_id}" in msg.text


async def test_create_nested_reply_endpoint_sends_both_kinds(
    client, db_session, cleanup_users, cleanup_forum_categories, outbox
) -> None:
    owner = await _committed(db_session, cleanup_users)
    parent_author = await _committed(db_session, cleanup_users)
    actor = await _committed(db_session, cleanup_users)
    thread = await _committed_thread(db_session, cleanup_forum_categories, owner)
    parent = await create_reply(db_session, thread_id=thread.id, author_id=parent_author.id)
    await db_session.commit()
    await login_as(client, actor)

    response = await client.post(
        f"{API}/threads/{thread.id}/replies/",
        json={"body_html": "<p>Agreed.</p>", "parent_reply_id": parent.id},
    )

    assert response.status_code == 201, response.text
    assert sorted(msg.to for msg in outbox) == sorted([owner.email, parent_author.email])


async def test_own_reply_endpoint_sends_nothing(
    client, db_session, cleanup_users, cleanup_forum_categories, outbox
) -> None:
    owner = await _committed(db_session, cleanup_users)
    thread = await _committed_thread(db_session, cleanup_forum_categories, owner)
    await login_as(client, owner)

    response = await client.post(
        f"{API}/threads/{thread.id}/replies/", json={"body_html": "<p>Update.</p>"}
    )

    assert response.status_code == 201, response.text
    assert outbox == []


async def test_create_reply_endpoint_survives_send_failure(
    client, db_session, cleanup_users, cleanup_forum_categories, outbox, monkeypatch
) -> None:
    owner = await _committed(db_session, cleanup_users)
    actor = await _committed(db_session, cleanup_users)
    thread = await _committed_thread(db_session, cleanup_forum_categories, owner)
    await login_as(client, actor)

    async def failing_send(**kwargs):
        raise ConnectionError("smtp down")

    monkeypatch.setattr("app.services.email.send_email", failing_send)
    with structlog.testing.capture_logs() as logs:
        response = await client.post(
            f"{API}/threads/{thread.id}/replies/", json={"body_html": "<p>Hello.</p>"}
        )

    assert response.status_code == 201, response.text
    reply_id = response.json()["id"]
    assert outbox == []
    failed = [e for e in logs if e["event"] == "notification.failed"]
    assert len(failed) == 1
    assert failed[0]["kind"] == "reply_to_thread"
    assert failed[0]["reply_id"] == reply_id
    assert failed[0]["error"] == "ConnectionError"
    assert owner.email not in repr(logs)
    assert actor.email not in repr(logs)


async def test_create_comment_endpoint_sends_notification(
    client, db_session, cleanup_users, cleanup_categories, outbox
) -> None:
    author = await _committed(db_session, cleanup_users)
    actor = await _committed(db_session, cleanup_users, display_name="Andrej Actor")
    category = await create_category(db_session)
    cleanup_categories.add(category.id)
    post = await create_post(
        db_session, category_id=category.id, author_id=author.id, title=POST_TITLE
    )
    await db_session.commit()
    await login_as(client, actor)

    response = await client.post(
        f"{API}/posts/{post.id}/comments/", json={"body_html": "<p>Very useful.</p>"}
    )

    assert response.status_code == 201, response.text
    comment_id = response.json()["id"]
    assert len(outbox) == 1
    msg = outbox[0]
    assert msg.to == author.email
    assert "Very useful." in msg.text
    assert f"{FRONTEND}/blog/{post.slug}#comment-{comment_id}" in msg.text


# --- one-click unsubscribe header -------------------------------------------------------------


def _unsubscribe_target(msg) -> tuple[int, str] | None:
    from urllib.parse import parse_qs, urlsplit

    from app.services.unsubscribe import read_token

    assert msg.list_unsubscribe is not None
    assert msg.list_unsubscribe.startswith(f"{FRONTEND}{API}/notifications/unsubscribe?token=")
    return read_token(parse_qs(urlsplit(msg.list_unsubscribe).query)["token"][0])


async def test_reply_to_thread_carries_its_unsubscribe_token(db_session, outbox) -> None:
    owner, _, _, reply = await _forum_setup(db_session)

    msg = await notify_reply_to_thread(db_session, reply=reply)

    assert _unsubscribe_target(msg) == (owner.id, "reply_to_my_thread")


async def test_reply_to_reply_carries_its_unsubscribe_token(db_session, outbox) -> None:
    owner, parent_author, thread, parent = await _forum_setup(db_session)
    actor = await create_verified_user(db_session)
    reply = await create_reply(
        db_session, thread_id=thread.id, author_id=actor.id, parent_reply_id=parent.id
    )

    to_parent = await notify_reply_to_reply(db_session, reply=reply)
    to_owner = await notify_reply_to_thread(db_session, reply=reply)

    assert _unsubscribe_target(to_parent) == (parent_author.id, "reply_to_my_reply")
    assert _unsubscribe_target(to_owner) == (owner.id, "reply_to_my_thread")


async def test_comment_on_post_carries_its_unsubscribe_token(db_session, outbox) -> None:
    author = await create_verified_user(db_session)
    actor = await create_verified_user(db_session)
    post = await _post(db_session, author)
    comment = await create_comment(db_session, post_id=post.id, author_id=actor.id)

    msg = await notify_comment_on_post(db_session, comment=comment)

    assert _unsubscribe_target(msg) == (author.id, "comment_on_my_post")
