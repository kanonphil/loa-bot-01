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


def test_list_read_returns_only_read_items_with_filters_applied(db_path):
    """읽음 탭 — 읽은 알림만, 종류 토글/레이드 필터도 동일하게 적용."""
    async def run():
        a = await notification_store.add_notification("created", "m1", "읽을 알림")
        await notification_store.add_notification("created", "m2", "안 읽은 알림")
        await notification_store.mark_read("111", a["id"])

        read = await notification_store.list_read("111")
        assert [n["message_id"] for n in read] == ["m1"]
        # 종류를 끄면 읽음 목록에서도 빠진다
        await notification_store.set_type_preferences("111", created=False, cleared=True, guest_joined=True)
        assert await notification_store.list_read("111") == []

    asyncio.run(run())


# ── 세부 설정: 종류 토글 + 레이드 필터 ────────────────────

def test_preferences_default_all_types_on_no_filters(db_path):
    prefs = asyncio.run(notification_store.get_preferences("111"))
    assert prefs["subscribed"] is False
    assert prefs["notify_created"] is True
    assert prefs["notify_cleared"] is True
    assert prefs["notify_guest_joined"] is True
    assert prefs["raid_filters"] == []


def test_type_preferences_filter_unread_and_count(db_path):
    async def run():
        await notification_store.add_notification("created", "msg-1", "모집", raid_name="카멘", difficulty="하드")
        await notification_store.add_notification("cleared", "msg-2", "클리어", raid_name="카멘", difficulty="하드")
        await notification_store.set_type_preferences("111", created=False, cleared=True, guest_joined=True)

        unread = await notification_store.list_unread("111")
        assert [n["type"] for n in unread] == ["cleared"]
        assert await notification_store.unread_count("111") == 1
        # 다른 유저는 영향 없음
        assert await notification_store.unread_count("222") == 2

    asyncio.run(run())


def test_type_preferences_do_not_touch_subscribed_flag(db_path):
    async def run():
        await notification_store.set_subscribed("111", True)
        await notification_store.set_type_preferences("111", created=False, cleared=True, guest_joined=True)
        assert await notification_store.is_subscribed("111") is True

    asyncio.run(run())


def test_raid_filters_limit_to_selected_raid_and_difficulty(db_path):
    async def run():
        await notification_store.add_notification("created", "m1", "카멘 하드", raid_name="카멘", difficulty="하드")
        await notification_store.add_notification("created", "m2", "카멘 노말", raid_name="카멘", difficulty="노말")
        await notification_store.add_notification("created", "m3", "종막 하드", raid_name="종막", difficulty="하드")

        await notification_store.add_raid_filter("111", "카멘", "하드")
        unread = await notification_store.list_unread("111")
        assert [n["message_id"] for n in unread] == ["m1"]

        # difficulty가 NULL인 필터는 그 레이드의 모든 난이도를 포함
        await notification_store.remove_raid_filter("111", "카멘", "하드")
        await notification_store.add_raid_filter("111", "카멘", None)
        unread = await notification_store.list_unread("111")
        assert sorted(n["message_id"] for n in unread) == ["m1", "m2"]

    asyncio.run(run())


def test_raid_filter_keeps_legacy_notifications_without_raid_metadata(db_path):
    """레이드 정보가 없는 구버전 알림은 필터로 걸러낼 근거가 없으므로 계속 보여준다."""
    async def run():
        await notification_store.add_notification("created", "m1", "구버전 알림")
        await notification_store.add_raid_filter("111", "카멘", "하드")
        unread = await notification_store.list_unread("111")
        assert [n["message_id"] for n in unread] == ["m1"]

    asyncio.run(run())


def test_event_matches_for_realtime_toast(db_path):
    async def run():
        await notification_store.set_type_preferences("111", created=True, cleared=False, guest_joined=True)
        await notification_store.add_raid_filter("111", "카멘", None)

        assert await notification_store.event_matches("111", "created", "카멘", "하드") is True
        assert await notification_store.event_matches("111", "created", "종막", "하드") is False
        assert await notification_store.event_matches("111", "cleared", "카멘", "하드") is False
        # 설정 없는 유저는 전부 통과 (기존 동작 유지)
        assert await notification_store.event_matches("222", "cleared", "종막", "하드") is True

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
