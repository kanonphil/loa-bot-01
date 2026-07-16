"""bot/api/routes/internal.py의 파티장 관리(마감/재개/클리어/취소/강제퇴장/일정변경/위임) 검증."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.api import bot_ref

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
LEADER_ID = "222"
MEMBER_ID = "333"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(db.add_character(LEADER_ID, "워로드캐릭"))
    asyncio.run(db.update_character_cache(LEADER_ID, "워로드캐릭", item_level=1710.0, character_class="워로드"))
    asyncio.run(db.set_user_api_key(MEMBER_ID, "dummy-key-2"))
    asyncio.run(db.add_character(MEMBER_ID, "발키리"))
    asyncio.run(db.update_character_cache(MEMBER_ID, "발키리", item_level=1710.0, character_class="홀리나이트"))

    asyncio.run(
        db.create_party(
            message_id="999", channel_id="555", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("999", LEADER_ID, "워로드캐릭", "워로드", "dps", 8))
    asyncio.run(db.auto_assign_slot("999", MEMBER_ID, "발키리", "홀리나이트", "support", 8))

    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot(monkeypatch):
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    fake_channel.edit = AsyncMock()
    fake_channel.send = AsyncMock()
    fake_channel.delete = AsyncMock()

    fake_user = AsyncMock()
    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_channel)
    fake_bot.fetch_user = AsyncMock(return_value=fake_user)

    bot_ref.set_bot(fake_bot)
    yield fake_bot, fake_channel, fake_message, fake_user
    bot_ref.set_bot(None)


# ── 권한 체크 공통 ──────────────────────────────────────────

def test_non_leader_cannot_close(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/close", json={"discord_id": MEMBER_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is False
    assert "파티장만" in body["reason"]


# ── 마감/재개 ───────────────────────────────────────────────

def test_close_then_reopen(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/close", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    assert resp.json() == {"success": True}
    assert (asyncio.run(db.get_party("999")))["status"] == "closed"

    resp2 = client.post(
        "/api/internal/parties/999/reopen", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    assert resp2.json() == {"success": True}
    assert (asyncio.run(db.get_party("999")))["status"] == "recruiting"


def test_reopen_rejected_when_not_closed(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/reopen", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    assert resp.json()["success"] is False


# ── 클리어 ─────────────────────────────────────────────────

def test_clear_completes_raid_and_disbands(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/clear", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is True
    assert body["cleared_count"] == 2
    assert (asyncio.run(db.get_party("999")))["status"] == "disbanded"

    week = db.get_week_key_for_dt("2026-05-20T20:00:00+09:00")
    done = asyncio.run(db.get_completions(LEADER_ID, "워로드캐릭", week))
    assert "아르모체(4막)_노말" in done


def test_clear_rejected_when_no_one_joined(client, fake_bot):
    """아무도 참여하지 않은 공격대는 클리어할 수 없어야 한다 — 파티장조차 슬롯에 없는
    상태(예: 웹에서 캐릭터 선택 없이 개설)로 클리어를 시도하면 거부돼야 한다."""
    asyncio.run(
        db.create_party(
            message_id="1000", channel_id="556", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/21 20:00", scheduled_datetime="2026-05-21T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    resp = client.post(
        "/api/internal/parties/1000/clear", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is False
    assert "파티원이 없" in body["reason"]
    assert (asyncio.run(db.get_party("1000")))["status"] == "recruiting"  # 상태 그대로 유지


# ── 파티 취소 ───────────────────────────────────────────────

def test_cancel_purges_party_and_dms_members(client, fake_bot):
    _, fake_channel, _, fake_user = fake_bot
    resp = client.post(
        "/api/internal/parties/999/cancel",
        json={"discord_id": LEADER_ID, "reason": "인원 부족"},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    assert asyncio.run(db.get_party("999")) is None
    assert fake_channel.delete.called
    fake_user.send.assert_awaited()


# ── 강제 퇴장 ───────────────────────────────────────────────

def test_kick_removes_member(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/kick",
        json={"discord_id": LEADER_ID, "target_discord_id": MEMBER_ID},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    slots = asyncio.run(db.get_party_slots("999"))
    assert MEMBER_ID not in {s["discord_id"] for s in slots}


def test_leader_cannot_kick_self(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/kick",
        json={"discord_id": LEADER_ID, "target_discord_id": LEADER_ID},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "본인" in body["reason"]


# ── 일정 변경 ───────────────────────────────────────────────

def test_reschedule_updates_time_and_memo(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/reschedule",
        json={"discord_id": LEADER_ID, "scheduled_datetime": "2099-05-20T20:00", "memo": "새 공지"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is True
    party = asyncio.run(db.get_party("999"))
    assert party["memo"] == "새 공지"
    assert "2099" in party["scheduled_datetime"]


def test_reschedule_rejects_past_date(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/reschedule",
        json={"discord_id": LEADER_ID, "scheduled_datetime": "2020-01-01T10:00"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "과거" in body["reason"]


# ── 파티장 위임 ─────────────────────────────────────────────

def test_transfer_leader_to_member(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/transfer-leader",
        json={"discord_id": LEADER_ID, "new_leader_discord_id": MEMBER_ID},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True}
    party = asyncio.run(db.get_party("999"))
    assert party["leader_id"] == MEMBER_ID


def test_transfer_leader_rejects_non_member(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/transfer-leader",
        json={"discord_id": LEADER_ID, "new_leader_discord_id": "999999"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "참여 중인 인원" in body["reason"]
