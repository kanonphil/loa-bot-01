"""공대 참여 역할(딜러/서포터) 변경(파티를 나갔다 재참여하지 않고 역할만 전환) 검증.

기존엔 서포터로 참여한 뒤 딜러로 바꾸려면 나갔다 재참여하는 방법뿐이었다 —
bot/database/manager.py의 switch_party_role과 bot/api/routes/internal.py의
switch-role 엔드포인트, bot/ui/views.py의 _switch_role_core를 검증한다."""
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
OTHER_ID = "333"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(db.add_character(LEADER_ID, "홀나캐릭"))
    asyncio.run(db.update_character_cache(LEADER_ID, "홀나캐릭", item_level=1710.0, character_class="홀리나이트"))

    asyncio.run(db.set_user_api_key(OTHER_ID, "dummy-key-2"))
    asyncio.run(db.add_character(OTHER_ID, "워로드캐릭"))
    asyncio.run(db.update_character_cache(OTHER_ID, "워로드캐릭", item_level=1710.0, character_class="워로드"))

    # 분할 파티(party_split=4)로 만들어서 "같은 소파티" 범위 판정도 같이 검증한다.
    asyncio.run(
        db.create_party(
            message_id="900", channel_id="700", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("900", LEADER_ID, "홀나캐릭", "홀리나이트", "support", 8, party_group=1, party_split=4))
    asyncio.run(db.auto_assign_slot("900", OTHER_ID, "워로드캐릭", "워로드", "dps", 8, party_group=1, party_split=4))

    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot(monkeypatch):
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    fake_channel.edit = AsyncMock()
    fake_channel.send = AsyncMock()

    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_channel)

    bot_ref.set_bot(fake_bot)
    yield fake_bot, fake_channel, fake_message
    bot_ref.set_bot(None)


def test_switch_role_support_to_dps_always_allowed(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/900/switch-role",
        json={"discord_id": LEADER_ID, "new_role": "dps"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is True

    slots = asyncio.run(db.get_party_slots("900"))
    mine = next(s for s in slots if s["discord_id"] == LEADER_ID)
    assert mine["role"] == "dps"
    assert mine["character_name"] == "홀나캐릭"  # 캐릭터·슬롯은 그대로


def test_switch_role_dps_to_support_rejects_non_support_class(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/900/switch-role",
        json={"discord_id": OTHER_ID, "new_role": "support"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "서포터 역할을 맡을 수 없습니다" in body["reason"]


def test_switch_role_dps_to_support_rejects_if_party_already_has_support(client, fake_bot):
    # 홀나캐릭이 이미 서포터라서, 같은 소파티(1파티)의 다른 멤버는 서포터로 못 바꾼다.
    asyncio.run(db.switch_party_role("900", OTHER_ID, "dps"))  # no-op, 이미 dps
    # 워로드는 서포터 직업이 아니라 애초에 막히므로, 서포터 직업 캐릭터를 하나 더 추가해 검증.
    asyncio.run(db.add_character(OTHER_ID, "바드캐릭"))
    asyncio.run(db.update_character_cache(OTHER_ID, "바드캐릭", item_level=1710.0, character_class="바드"))
    asyncio.run(db.switch_party_character("900", OTHER_ID, "바드캐릭", "바드", "dps"))

    resp = client.post(
        "/api/internal/parties/900/switch-role",
        json={"discord_id": OTHER_ID, "new_role": "support"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "이미 서포터가 있는 파티" in body["reason"]


def test_switch_role_dps_to_support_allowed_in_other_sub_party(client, fake_bot):
    """분할 파티에서 1파티에 서포터가 있어도, 2파티는 별개 범위라 허용돼야 한다."""
    asyncio.run(db.add_character(OTHER_ID, "바드캐릭"))
    asyncio.run(db.update_character_cache(OTHER_ID, "바드캐릭", item_level=1710.0, character_class="바드"))
    asyncio.run(db.leave_slot("900", OTHER_ID))
    asyncio.run(db.auto_assign_slot("900", OTHER_ID, "바드캐릭", "바드", "dps", 8, party_group=2, party_split=4))

    resp = client.post(
        "/api/internal/parties/900/switch-role",
        json={"discord_id": OTHER_ID, "new_role": "support"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is True
    slots = asyncio.run(db.get_party_slots("900"))
    mine = next(s for s in slots if s["discord_id"] == OTHER_ID)
    assert mine["role"] == "support"


def test_switch_role_rejects_same_role(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/900/switch-role",
        json={"discord_id": LEADER_ID, "new_role": "support"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "이미 이 역할" in body["reason"]


def test_switch_role_rejects_non_member(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/900/switch-role",
        json={"discord_id": "999999", "new_role": "dps"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "참여하고 있지 않습니다" in body["reason"]
