"""bot/api/routes/internal.py의 공대 모집(참여/나가기) 엔드포인트 검증."""
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


@pytest.fixture()
def party_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key("111", "dummy-key"))
    asyncio.run(db.add_character("111", "발키리"))
    asyncio.run(
        db.update_character_cache("111", "발키리", item_level=1710.0, character_class="홀리나이트")
    )
    asyncio.run(db.set_user_api_key("222", "dummy-key-2"))
    asyncio.run(db.add_character("222", "워로드캐릭"))
    asyncio.run(
        db.update_character_cache("222", "워로드캐릭", item_level=1710.0, character_class="워로드")
    )

    asyncio.run(
        db.create_party(
            message_id="999", channel_id="555", guild_id="1", leader_id="222",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("999", "222", "워로드캐릭", "워로드", "dps", 8))
    return "999"


@pytest.fixture()
def client():
    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot(monkeypatch):
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    fake_channel.edit = AsyncMock()

    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_channel)

    bot_ref.set_bot(fake_bot)
    yield fake_bot, fake_channel, fake_message
    bot_ref.set_bot(None)


def test_list_parties_includes_slots(client, party_setup, fake_bot):
    resp = client.get("/api/internal/parties", params={"guild_id": "1"}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert len(data[0]["slots"]) == 1
    assert data[0]["slots"][0]["character_name"] == "워로드캐릭"


def test_support_classes_endpoint_includes_known_support_class(client, party_setup, fake_bot):
    """공대 개설 폼이 캐릭터별 역할 선택지를 제한하는 데 쓰는 목록 — 서포터로
    분류된 직업(예: 홀리나이트)이 포함돼야 한다."""
    resp = client.get("/api/internal/support-classes", headers=HEADERS)
    assert resp.status_code == 200
    classes = resp.json()
    assert "홀리나이트" in classes
    assert "워로드" not in classes


def test_party_detail_returns_none_for_missing(client, party_setup, fake_bot):
    resp = client.get("/api/internal/parties/no-such-id", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() is None


def test_eligibility_endpoint_matches_shared_logic(client, party_setup, fake_bot):
    resp = client.get(
        "/api/internal/parties/999/eligibility",
        params={"discord_id": "111"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["can_join"] is True
    assert [q["name"] for q in data["qualifying"]] == ["발키리"]


def test_join_success_refreshes_discord_embed(client, party_setup, fake_bot):
    """아르모체(4막) 노말은 party_split=4(8인을 4+4로 분할)라 party_group 지정이 필요하다."""
    _, fake_channel, fake_message = fake_bot

    resp = client.post(
        "/api/internal/parties/999/join",
        json={
            "discord_id": "111",
            "character_name": "발키리",
            "role": "support",
            "party_group": 1,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["slot_number"] == 2

    fake_channel.fetch_message.assert_awaited_once()
    fake_message.edit.assert_awaited_once()
    slots = asyncio.run(db.get_party_slots(party_setup))
    assert any(s["discord_id"] == "111" and s["role"] == "support" for s in slots)


def test_join_requires_party_group_when_raid_is_split(client, party_setup, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "발키리", "role": "support"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "파티" in body["reason"]


def test_join_rejects_ineligible_character_tampering(client, party_setup, fake_bot):
    """participant가 낮은 레벨 캐릭터로 조작해서 보내도 서버가 다시 검증해서 막아야 한다."""
    asyncio.run(
        db.update_character_cache("111", "발키리", item_level=1000.0, character_class="홀리나이트")
    )
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "발키리", "role": "support"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_join_rejects_support_role_for_non_support_class(client, party_setup, fake_bot):
    asyncio.run(db.add_character("111", "워로드둘째"))
    asyncio.run(
        db.update_character_cache("111", "워로드둘째", item_level=1710.0, character_class="워로드")
    )
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "워로드둘째", "role": "support"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "서포터" in resp.json()["reason"]


def test_leave_removes_slot_and_refreshes_embed(client, party_setup, fake_bot):
    _, fake_channel, fake_message = fake_bot
    asyncio.run(db.auto_assign_slot("999", "111", "발키리", "서포터", "support", 8))

    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "111"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    slots = asyncio.run(db.get_party_slots("999"))
    assert not any(s["discord_id"] == "111" for s in slots)
    fake_message.edit.assert_awaited()


def test_leave_transfers_leadership_when_leader_leaves(client, party_setup, fake_bot):
    asyncio.run(db.auto_assign_slot("999", "111", "발키리", "서포터", "support", 8))

    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "222"},  # 원래 파티장
        headers=HEADERS,
    )
    assert resp.status_code == 200

    party = asyncio.run(db.get_party("999"))
    assert party["leader_id"] == "111"


def test_leave_disbands_party_when_last_member_leaves(client, party_setup, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "222"},  # 유일한 멤버이자 파티장
        headers=HEADERS,
    )
    assert resp.status_code == 200

    party = asyncio.run(db.get_party("999"))
    assert party["status"] == "disbanded"


def test_leave_rejects_user_not_in_party(client, party_setup, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "999999"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
