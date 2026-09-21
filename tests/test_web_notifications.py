"""봇 DM을 웹 알림함에도 남기는 브릿지(web_notifications) 검증 — _send_dm 미러링,
_web_text 정리, 파티원 전체 공지, 내부 API 피드."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db
from bot.ui.views import _notify_members_web, _send_dm, _web_text

HEADERS = {"X-Webapp-Key": "test-webapp-key"}


@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


def test_web_text_strips_markdown_links_and_leading_emoji():
    text = _web_text("📅 **아르모체(4막) 하드** 공대 일정이 변경되었습니다.\n새 일정: **05/21 21:00**\nhttps://discord.com/channels/1/2")
    assert text == "아르모체(4막) 하드 공대 일정이 변경되었습니다. 새 일정: 05/21 21:00"


def test_send_dm_records_web_notification_even_when_dm_blocked(fresh_db):
    client = MagicMock()
    client.fetch_user = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "dm closed"))
    asyncio.run(_send_dm(client, "111", "⚠️ **카멘 하드** 공대에서 파티장에 의해 퇴장되었습니다.", kind="kicked", message_id="900"))
    rows = asyncio.run(db.get_web_notifications_after(0))
    assert len(rows) == 1
    assert rows[0]["discord_id"] == "111" and rows[0]["kind"] == "kicked" and rows[0]["message_id"] == "900"
    assert rows[0]["text"] == "카멘 하드 공대에서 파티장에 의해 퇴장되었습니다."


def test_send_dm_default_kind_is_dm(fresh_db):
    client = MagicMock(); client.fetch_user = AsyncMock(return_value=AsyncMock())
    asyncio.run(_send_dm(client, "111", "안녕"))
    assert asyncio.run(db.get_web_notifications_after(0))[0]["kind"] == "dm"


def test_notify_members_web_writes_one_row_per_member(fresh_db):
    asyncio.run(db.create_party(
        message_id="900", channel_id="700", guild_id="1", leader_id="111",
        raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
        scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
        total_slots=8, min_level=1700,
    ))
    asyncio.run(db.auto_assign_slot("900", "111", "리더캐릭", "워로드", "dps", 8))
    asyncio.run(db.auto_assign_slot("900", "222", "멤버캐릭", "바드", "support", 8))
    asyncio.run(_notify_members_web("900", "party_full", "파티가 완성되었습니다.", exclude="111"))
    rows = asyncio.run(db.get_web_notifications_after(0))
    assert [(r["discord_id"], r["kind"]) for r in rows] == [("222", "party_full")]


def test_feed_endpoint_cursor_semantics(fresh_db):
    from bot.api.server import app
    client = TestClient(app)
    asyncio.run(db.add_web_notification("111", "invited", "900", "초대"))
    asyncio.run(db.add_web_notification("222", "kicked", "900", "퇴장"))

    first = client.get("/api/internal/web-notifications", headers=HEADERS).json()
    assert first == {"latest_id": 2, "items": []}
    later = client.get("/api/internal/web-notifications", params={"after_id": 1}, headers=HEADERS).json()
    assert later["latest_id"] == 2
    assert [i["id"] for i in later["items"]] == [2]
    assert later["items"][0]["discord_id"] == "222"


def test_party_detail_includes_waitlist_count(fresh_db):
    from bot.api.server import app
    client = TestClient(app)
    asyncio.run(db.create_party(
        message_id="900", channel_id="700", guild_id="1", leader_id="111",
        raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
        scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
        total_slots=8, min_level=1700,
    ))
    asyncio.run(db.add_waitlist("900", "333"))
    body = client.get("/api/internal/parties/900", headers=HEADERS).json()
    assert body["waitlist_count"] == 1
    status = client.get("/api/internal/parties/900/waitlist-status", params={"discord_id": "333"}, headers=HEADERS).json()
    assert status == {"on_waitlist": True, "count": 1}
