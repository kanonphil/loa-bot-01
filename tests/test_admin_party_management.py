"""웹 관리자의 "공대 관리" 기능 검증 —
1) 강제 마감/재개/강퇴/일정변경/파티장위임: 기존 리더 전용 라우트가 관리자의
   discord_id도 받아주는지(_require_leader_or_admin), 2) 클리어 되돌리기:
   관리자 전용 신규 액션(_admin_revert_clear_core) + 목록 조회(/admin/parties)."""
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
import config
from bot.api import bot_ref

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
LEADER_ID = "222"
MEMBER_ID = "333"
ADMIN_ID = "777"
OUTSIDER_ID = "888"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})
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
def fake_bot():
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


# ── 관리자가 파티장 없이 기존 리더 액션을 대신 쓸 수 있는지 ──────────

def test_admin_can_close_party_they_do_not_lead(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/close", json={"discord_id": ADMIN_ID}, headers=HEADERS
    )
    assert resp.json()["success"] is True
    assert (asyncio.run(db.get_party("999")))["status"] == "closed"


def test_outsider_still_rejected(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/close", json={"discord_id": OUTSIDER_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is False
    assert "파티장만" in body["reason"]


def test_admin_can_kick_member(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/kick",
        json={"discord_id": ADMIN_ID, "target_discord_id": MEMBER_ID},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    slots = asyncio.run(db.get_party_slots("999"))
    assert MEMBER_ID not in {s["discord_id"] for s in slots}


def test_admin_can_transfer_leader(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/transfer-leader",
        json={"discord_id": ADMIN_ID, "new_leader_discord_id": MEMBER_ID},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    assert (asyncio.run(db.get_party("999")))["leader_id"] == MEMBER_ID


def test_admin_can_reschedule(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/reschedule",
        json={"discord_id": ADMIN_ID, "scheduled_datetime": "2099-06-01T21:00:00+09:00"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is True
    assert (asyncio.run(db.get_party("999")))["scheduled_datetime"] == "2099-06-01T21:00:00+09:00"


def test_admin_can_reopen_after_close(client, fake_bot):
    client.post("/api/internal/parties/999/close", json={"discord_id": ADMIN_ID}, headers=HEADERS)
    resp = client.post(
        "/api/internal/parties/999/reopen", json={"discord_id": ADMIN_ID}, headers=HEADERS
    )
    assert resp.json()["success"] is True
    assert (asyncio.run(db.get_party("999")))["status"] == "recruiting"


def test_admin_can_clear_party_they_do_not_lead(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/clear", json={"discord_id": ADMIN_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is True
    assert body["cleared_count"] == 2
    assert (asyncio.run(db.get_party("999")))["status"] == "disbanded"


# ── 클리어 되돌리기 (관리자 전용) ────────────────────────────────

def test_revert_clear_restores_status_and_completions(client, fake_bot):
    clear_resp = client.post(
        "/api/internal/parties/999/clear", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    assert clear_resp.json()["success"] is True
    week = db.get_week_key_for_dt("2026-05-20T20:00:00+09:00")
    assert "아르모체(4막)_노말" in asyncio.run(db.get_completions(LEADER_ID, "워로드캐릭", week))

    revert_resp = client.post(
        "/api/internal/admin/parties/999/revert-clear", json={"discord_id": ADMIN_ID}, headers=HEADERS
    )
    body = revert_resp.json()
    assert body["success"] is True
    assert body["new_status"] == "recruiting"  # 8인 중 2명만 참여 -> full 아님
    assert (asyncio.run(db.get_party("999")))["status"] == "recruiting"
    assert "아르모체(4막)_노말" not in asyncio.run(db.get_completions(LEADER_ID, "워로드캐릭", week))
    assert "아르모체(4막)_노말" not in asyncio.run(db.get_completions(MEMBER_ID, "발키리", week))


def test_revert_clear_picks_full_when_party_was_full(client, fake_bot):
    for i in range(6):
        did = f"extra{i}"
        asyncio.run(db.set_user_api_key(did, f"key-{i}"))
        asyncio.run(db.add_character(did, f"캐릭{i}"))
        asyncio.run(db.auto_assign_slot("999", did, f"캐릭{i}", "워로드", "dps", 8))

    client.post("/api/internal/parties/999/clear", json={"discord_id": LEADER_ID}, headers=HEADERS)
    resp = client.post(
        "/api/internal/admin/parties/999/revert-clear", json={"discord_id": ADMIN_ID}, headers=HEADERS
    )
    assert resp.json()["new_status"] == "full"


def test_leader_cannot_revert_clear_own_party(client, fake_bot):
    """파티장 본인은 되돌리기를 못 쓴다 — 관리자 전용으로 의도적으로 제한."""
    client.post("/api/internal/parties/999/clear", json={"discord_id": LEADER_ID}, headers=HEADERS)
    resp = client.post(
        "/api/internal/admin/parties/999/revert-clear", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is False
    assert "관리자 권한이 없습니다" in body["reason"]
    assert (asyncio.run(db.get_party("999")))["status"] == "disbanded"  # 그대로 유지


def test_revert_clear_rejected_when_not_disbanded(client, fake_bot):
    resp = client.post(
        "/api/internal/admin/parties/999/revert-clear", json={"discord_id": ADMIN_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is False
    assert "클리어 상태가 아닙니다" in body["reason"]


def test_revert_clear_rejected_when_already_purged(client, fake_bot):
    client.post("/api/internal/parties/999/cancel", json={"discord_id": LEADER_ID}, headers=HEADERS)
    resp = client.post(
        "/api/internal/admin/parties/999/revert-clear", json={"discord_id": ADMIN_ID}, headers=HEADERS
    )
    body = resp.json()
    assert body["success"] is False
    assert "정리된 파티" in body["reason"]


# ── 관리자 목록 조회 ────────────────────────────────────────────

def test_admin_list_parties_splits_open_and_closed(client, fake_bot):
    asyncio.run(
        db.create_party(
            message_id="1001", channel_id="600", guild_id="1", leader_id=MEMBER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/22 20:00", scheduled_datetime="2026-05-22T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    client.post("/api/internal/parties/999/clear", json={"discord_id": LEADER_ID}, headers=HEADERS)

    resp = client.get("/api/internal/admin/parties", params={"guild_id": "1"}, headers=HEADERS)
    body = resp.json()

    open_ids = {p["message_id"] for p in body["open"]}
    closed_ids = {p["message_id"]: p for p in body["closed"]}

    assert "1001" in open_ids
    assert "999" in closed_ids
    assert closed_ids["999"]["is_live"] is True  # 아직 purge 전 — 되돌리기 가능
    assert "slots" in body["open"][0]  # 오픈 쪽엔 슬롯까지 붙어옴(1001은 참여자가 없어 빈 배열)
