"""웹 설정/관리자 화면이 봇 DB를 다루기 위한 내부 API — 디스코드 DM 구독(/레이드구독),
사전 알림 시간, 게스트 초대 후보, 공대 포럼 채널 설정, 지난 주차 클리어 기록."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import MagicMock

import discord
import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
import config
from bot.api import bot_ref

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
LEADER_ID = "222"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(db.create_party(
        message_id="900", channel_id="700", guild_id="1", leader_id=LEADER_ID,
        raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
        scheduled_time="05/20 20:00", scheduled_datetime="2099-05-20T20:00:00+09:00",
        total_slots=8, min_level=1700,
    ))
    asyncio.run(db.auto_assign_slot("900", LEADER_ID, "워로드캐릭", "워로드", "dps", 8))
    from bot.api.server import app

    return TestClient(app)


def _member(member_id: int, name: str, is_bot: bool = False):
    m = MagicMock()
    m.id = member_id
    m.display_name = name
    m.bot = is_bot
    return m


@pytest.fixture()
def fake_guild(monkeypatch):
    forum = MagicMock(spec=discord.ForumChannel)
    forum.id = 700
    forum.name = "공대모집"
    text = MagicMock(spec=discord.TextChannel)
    text.id = 701
    text.name = "잡담"
    guild = MagicMock()
    guild.members = [_member(222, "리더"), _member(333, "게스트후보"), _member(444, "봇", is_bot=True), _member(555, "다른게스트")]
    guild.channels = [forum, text]
    guild.get_channel = lambda cid: {700: forum, 701: text}.get(cid)
    fake_bot = MagicMock()
    fake_bot.get_guild = MagicMock(return_value=guild)
    bot_ref.set_bot(fake_bot)
    yield guild
    bot_ref.set_bot(None)


# ── 디스코드 DM 구독 ──────────────────────────────────────────

def test_subscription_add_list_remove(client):
    resp = client.post("/api/internal/subscriptions", json={"discord_id": "111", "raid_name": "아르모체(4막)", "difficulty": "전체"}, headers=HEADERS)
    assert resp.json() == {"success": True}
    dup = client.post("/api/internal/subscriptions", json={"discord_id": "111", "raid_name": "아르모체(4막)", "difficulty": "전체"}, headers=HEADERS)
    assert dup.json()["success"] is False and "이미" in dup.json()["reason"]

    listed = client.get("/api/internal/subscriptions", params={"discord_id": "111"}, headers=HEADERS).json()
    assert [(s["raid_name"], s["difficulty"]) for s in listed] == [("아르모체(4막)", "전체")]

    removed = client.post("/api/internal/subscriptions/remove", json={"discord_id": "111", "raid_name": "아르모체(4막)", "difficulty": "전체"}, headers=HEADERS)
    assert removed.json() == {"success": True}
    assert client.get("/api/internal/subscriptions", params={"discord_id": "111"}, headers=HEADERS).json() == []


def test_subscription_rejects_unknown_raid_or_difficulty(client):
    bad_raid = client.post("/api/internal/subscriptions", json={"discord_id": "111", "raid_name": "없는레이드", "difficulty": "전체"}, headers=HEADERS).json()
    assert bad_raid["success"] is False
    bad_diff = client.post("/api/internal/subscriptions", json={"discord_id": "111", "raid_name": "아르모체(4막)", "difficulty": "익스트림"}, headers=HEADERS).json()
    assert bad_diff["success"] is False
    assert asyncio.run(db.get_user_subscriptions("111")) == []


# ── 사전 알림 설정 ────────────────────────────────────────────

def test_preferences_default_off_and_roundtrip(client):
    assert client.get("/api/internal/preferences", params={"discord_id": "111"}, headers=HEADERS).json()["pre_notify_hours"] == 0.0
    ok = client.post("/api/internal/preferences", json={"discord_id": "111", "pre_notify_hours": 2}, headers=HEADERS).json()
    assert ok == {"success": True, "pre_notify_hours": 2.0}
    assert client.get("/api/internal/preferences", params={"discord_id": "111"}, headers=HEADERS).json()["pre_notify_hours"] == 2.0
    bad = client.post("/api/internal/preferences", json={"discord_id": "111", "pre_notify_hours": 5}, headers=HEADERS).json()
    assert bad["success"] is False


# ── 게스트 초대 후보 ──────────────────────────────────────────

def test_guest_candidates_excludes_bots_registered_and_party_members(client, fake_guild):
    resp = client.get("/api/internal/parties/900/guest-candidates", params={"discord_id": LEADER_ID, "guild_id": "1"}, headers=HEADERS)
    body = resp.json()
    assert body["success"] is True
    assert [m["discord_id"] for m in body["members"]] == ["333", "555"]
    assert body["available_slots"] == [2, 3, 4, 5, 6, 7, 8]


def test_guest_candidates_requires_leader(client, fake_guild):
    body = client.get("/api/internal/parties/900/guest-candidates", params={"discord_id": "333", "guild_id": "1"}, headers=HEADERS).json()
    assert body["success"] is False


# ── 공대 포럼 채널 설정 ────────────────────────────────────────

def test_admin_forum_channel_lists_only_forums_and_sets(client, fake_guild, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    listed = client.get("/api/internal/admin/forum-channel", params={"discord_id": "999", "guild_id": "1"}, headers=HEADERS).json()
    assert listed["forum_channel_id"] is None
    assert listed["channels"] == [{"id": "700", "name": "공대모집"}]

    ok = client.post("/api/internal/admin/forum-channel", json={"discord_id": "999", "guild_id": "1", "channel_id": "700"}, headers=HEADERS).json()
    assert ok == {"success": True, "forum_channel_id": "700", "forum_channel_name": "공대모집"}
    assert asyncio.run(db.get_forum_channel_id("1")) == "700"

    again = client.get("/api/internal/admin/forum-channel", params={"discord_id": "999", "guild_id": "1"}, headers=HEADERS).json()
    assert again["forum_channel_name"] == "공대모집"


def test_admin_forum_channel_rejects_text_channel_and_non_admin(client, fake_guild, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    bad = client.post("/api/internal/admin/forum-channel", json={"discord_id": "999", "guild_id": "1", "channel_id": "701"}, headers=HEADERS).json()
    assert bad["success"] is False
    denied = client.post("/api/internal/admin/forum-channel", json={"discord_id": "111", "guild_id": "1", "channel_id": "700"}, headers=HEADERS).json()
    assert denied["success"] is False
    assert client.get("/api/internal/admin/forum-channel", params={"discord_id": "111", "guild_id": "1"}, headers=HEADERS).status_code == 403


# ── 지난 주차 클리어 기록 ─────────────────────────────────────

def test_completion_weeks_and_week_detail(client):
    asyncio.run(db.add_character("111", "발키리"))
    asyncio.run(db.update_character_cache("111", "발키리", item_level=1710.0, character_class="홀리나이트"))
    asyncio.run(db.add_completion("111", "발키리", "아르모체(4막)", "노말", "2026-05-06"))
    asyncio.run(db.add_completion("111", "발키리", "종막", "하드", "2026-05-06"))
    asyncio.run(db.add_completion("111", "발키리", "종막", "노말", "2026-04-29"))

    weeks = client.get("/api/internal/completions/weeks", params={"discord_id": "111"}, headers=HEADERS).json()
    assert weeks["weeks"][0] == weeks["current_week"]
    assert "2026-05-06" in weeks["weeks"] and "2026-04-29" in weeks["weeks"]

    week = client.get("/api/internal/completions/week", params={"discord_id": "111", "week_key": "2026-05-06"}, headers=HEADERS).json()
    assert week["week_key"] == "2026-05-06"
    assert len(week["characters"]) == 1
    entry = week["characters"][0]
    assert entry["character_name"] == "발키리" and entry["character_class"] == "홀리나이트"
    assert [(c["raid_name"], c["difficulty"]) for c in entry["completions"]] == [("아르모체(4막)", "노말"), ("종막", "하드")]
