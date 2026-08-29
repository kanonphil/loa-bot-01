"""웹 파티 초대 API(bot/api/routes/internal.py) 검증 — 등록 유저 초대만 지원(v1).
핵심 판단 로직 자체는 test_invite_core.py에서 이미 검증하므로, 여기서는 라우트가
올바른 core 함수/discord_id를 연결해 호출하는지와 인증(X-Webapp-Key)만 확인한다."""
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
LEADER_ID = "111"
TARGET_ID = "222"
MESSAGE_ID = "700"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(db.add_character(LEADER_ID, "리더캐릭"))
    asyncio.run(db.set_user_api_key(TARGET_ID, "dummy-key-2"))
    asyncio.run(db.add_character(TARGET_ID, "타겟캐릭"))
    asyncio.run(db.update_character_cache(TARGET_ID, "타겟캐릭", 1720.0, "워로드"))

    asyncio.run(
        db.create_party(
            message_id=MESSAGE_ID, channel_id="600", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )

    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot():
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=fake_channel)
    bot.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock(), display_name="유저"))
    bot_ref.set_bot(bot)
    yield bot
    bot_ref.set_bot(None)


def test_invitable_users_lists_registered_non_members(client):
    resp = client.get(
        f"/api/internal/parties/{MESSAGE_ID}/invitable-users",
        params={"discord_id": LEADER_ID},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is True
    ids = {u["discord_id"] for u in body["users"]}
    assert TARGET_ID in ids
    assert LEADER_ID not in ids
    assert body["available_slots"] == list(range(1, 9))


def test_invitable_users_rejects_non_leader(client):
    resp = client.get(
        f"/api/internal/parties/{MESSAGE_ID}/invitable-users",
        params={"discord_id": "999"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False


def test_create_invite_then_my_invites_then_accept(client, fake_bot):
    create_resp = client.post(
        f"/api/internal/parties/{MESSAGE_ID}/invite",
        json={"discord_id": LEADER_ID, "target_discord_id": TARGET_ID, "slot_number": 1},
        headers=HEADERS,
    )
    assert create_resp.json()["success"] is True

    my_invites_resp = client.get(
        "/api/internal/my-invites", params={"discord_id": TARGET_ID}, headers=HEADERS
    )
    invites = my_invites_resp.json()
    assert len(invites) == 1
    assert invites[0]["message_id"] == MESSAGE_ID
    assert invites[0]["slot_number"] == 1

    accept_resp = client.post(
        f"/api/internal/invites/{MESSAGE_ID}/accept",
        json={"discord_id": TARGET_ID, "character_name": "타겟캐릭", "role": "dps"},
        headers=HEADERS,
    )
    assert accept_resp.json()["success"] is True

    slots = asyncio.run(db.get_party_slots(MESSAGE_ID))
    assert len(slots) == 1
    assert slots[0]["character_name"] == "타겟캐릭"

    # 수락 후 초대 목록에서 사라져야 한다
    my_invites_after = client.get(
        "/api/internal/my-invites", params={"discord_id": TARGET_ID}, headers=HEADERS
    ).json()
    assert my_invites_after == []


def test_decline_invite_removes_reservation(client, fake_bot):
    client.post(
        f"/api/internal/parties/{MESSAGE_ID}/invite",
        json={"discord_id": LEADER_ID, "target_discord_id": TARGET_ID, "slot_number": 1},
        headers=HEADERS,
    )

    resp = client.post(
        f"/api/internal/invites/{MESSAGE_ID}/decline",
        json={"discord_id": TARGET_ID},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    assert asyncio.run(db.get_reserved_slots(MESSAGE_ID)) == {}


def test_invite_routes_require_webapp_key(client):
    assert client.get(f"/api/internal/parties/{MESSAGE_ID}/invitable-users", params={"discord_id": LEADER_ID}).status_code == 401
    assert client.post(f"/api/internal/parties/{MESSAGE_ID}/invite", json={"discord_id": LEADER_ID, "target_discord_id": TARGET_ID, "slot_number": 1}).status_code == 401
    assert client.get("/api/internal/my-invites", params={"discord_id": TARGET_ID}).status_code == 401
    assert client.post(f"/api/internal/invites/{MESSAGE_ID}/accept", json={"discord_id": TARGET_ID, "character_name": "x", "role": "dps"}).status_code == 401
    assert client.post(f"/api/internal/invites/{MESSAGE_ID}/decline", json={"discord_id": TARGET_ID}).status_code == 401
