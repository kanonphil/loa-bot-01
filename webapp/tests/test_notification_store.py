"""webapp.notification_store가 실제로 동작하는지 검증 (알림 저장, 구독, 읽음 처리, 보관기간 자동 삭제)."""
import os

os.environ.setdefault("DISCORD_CLIENT_ID", "test-client-id")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DISCORD_REDIRECT_URI", "http://localhost:8001/callback")
os.environ.setdefault("BOT_API_BASE_URL", "http://bot-server.internal")
os.environ.setdefault("BOT_API_WEBAPP_KEY", "test-webapp-key")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from webapp import config, notification_store


@pytest.fixture()
def db_path(tmp_path, monkeypatch):
    path = str(tmp_path / "notif_test.db")
    monkeypatch.setattr(config, "NOTIFICATION_DB_PATH", path)
    asyncio.run(notification_store.init_db())
    return path


def test_default_not_subscribed(db_path):
    assert asyncio.run(notification_store.is_subscribed("111")) is False


def test_subscribe_toggle(db_path):
    async def run():
        await notification_store.set_subscribed("111", True)
        assert await notification_store.is_subscribed("111") is True
        await notification_store.set_subscribed("111", False)
        assert await notification_store.is_subscribed("111") is False

    asyncio.run(run())


def test_add_notification_appears_in_unread_for_everyone(db_path):
    async def run():
        await notification_store.add_notification("created", "msg-1", "카멘 하드 공격대가 모집을 시작했습니다.")
        unread_a = await notification_store.list_unread("111")
        unread_b = await notification_store.list_unread("222")
        assert len(unread_a) == 1
        assert len(unread_b) == 1
        assert unread_a[0]["text"] == "카멘 하드 공격대가 모집을 시작했습니다."

    asyncio.run(run())


def test_mark_read_removes_from_unread_only_for_that_user(db_path):
    async def run():
        saved = await notification_store.add_notification("created", "msg-1", "text")
        notif = await notification_store.mark_read("111", saved["id"])
        assert notif["message_id"] == "msg-1"

        assert await notification_store.list_unread("111") == []
        unread_other = await notification_store.list_unread("222")
        assert len(unread_other) == 1

    asyncio.run(run())


def test_mark_read_unknown_id_returns_none(db_path):
    assert asyncio.run(notification_store.mark_read("111", 9999)) is None


def test_unread_count(db_path):
    async def run():
        await notification_store.add_notification("created", "msg-1", "a")
        await notification_store.add_notification("cleared", "msg-2", "b")
        assert await notification_store.unread_count("111") == 2
        first = (await notification_store.list_unread("111"))[-1]
        await notification_store.mark_read("111", first["id"])
        assert await notification_store.unread_count("111") == 1

    asyncio.run(run())


def test_list_unread_newest_first(db_path):
    async def run():
        await notification_store.add_notification("created", "msg-1", "first")
        await notification_store.add_notification("created", "msg-2", "second")
        unread = await notification_store.list_unread("111")
        assert [n["text"] for n in unread] == ["second", "first"]

    asyncio.run(run())


def test_delete_expired_removes_old_notifications_and_reads(db_path):
    async def run():
        saved = await notification_store.add_notification("created", "msg-1", "old")
        old_time = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        import aiosqlite

        async with aiosqlite.connect(config.NOTIFICATION_DB_PATH) as db:
            await db.execute(
                "UPDATE notifications SET created_at=? WHERE id=?", (old_time, saved["id"])
            )
            await db.commit()
        await notification_store.mark_read("111", saved["id"])

        await notification_store.add_notification("created", "msg-2", "recent")

        deleted = await notification_store.delete_expired(30)
        assert deleted == 1

        remaining = await notification_store.list_unread("222")
        assert [n["text"] for n in remaining] == ["recent"]

    asyncio.run(run())
