"""공대 참여 캐릭터 변경(파티를 나갔다 재참여하지 않고 캐릭터만 교체) 검증.

bot/database/manager.py의 get_party_switch_eligibility/switch_party_character와
bot/api/routes/internal.py의 switch-eligibility·switch-character 엔드포인트,
그리고 bot/ui/views.py의 _switch_character_core(디스코드·웹 공유 로직)를 검증한다."""
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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(db.add_character(LEADER_ID, "워로드본캐"))
    asyncio.run(db.add_character(LEADER_ID, "홀나부캐"))
    asyncio.run(db.add_character(LEADER_ID, "육성중캐릭"))  # 레벨 미달
    asyncio.run(db.add_character(LEADER_ID, "캐시없는캐릭"))  # 동기화 안 됨
    asyncio.run(db.update_character_cache(LEADER_ID, "워로드본캐", item_level=1710.0, character_class="워로드"))
    asyncio.run(db.update_character_cache(LEADER_ID, "홀나부캐", item_level=1710.0, character_class="홀리나이트"))
    asyncio.run(db.update_character_cache(LEADER_ID, "육성중캐릭", item_level=1000.0, character_class="기공사"))

    asyncio.run(
        db.create_party(
            message_id="900", channel_id="700", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("900", LEADER_ID, "워로드본캐", "워로드", "dps", 8))

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


# ── 후보 목록(eligibility) ──────────────────────────────────

def test_switch_eligibility_lists_other_registered_characters(client, fake_bot):
    resp = client.get(
        "/api/internal/parties/900/switch-eligibility",
        params={"discord_id": LEADER_ID},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["can_switch"] is True
    assert body["current_character"] == "워로드본캐"
    names = {c["name"] for c in body["candidates"]}
    assert names == {"홀나부캐"}  # 워로드본캐(현재)는 제외, 레벨미달/캐시없음도 제외
    assert body["level_too_low"] == [{"name": "육성중캐릭", "level": 1000.0}]
    assert body["no_cache"] == ["캐시없는캐릭"]
    holy = next(c for c in body["candidates"] if c["name"] == "홀나부캐")
    assert holy["in_other_party"] is None


def test_switch_eligibility_rejects_non_member(client, fake_bot):
    resp = client.get(
        "/api/internal/parties/900/switch-eligibility",
        params={"discord_id": "999999"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["can_switch"] is False
    assert "참여하고 있지 않습니다" in body["reason"]


def test_switch_eligibility_flags_character_in_other_party(client, fake_bot):
    """같은 레이드·같은 주차의 다른 공대에 이미 참여 중인 캐릭터는 후보에서 빼지 않고
    in_other_party로 표시해야 한다(선택 자체는 가능, 실행 시 그 공대에서 자동으로 빠짐)."""
    asyncio.run(
        db.create_party(
            message_id="901", channel_id="701", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 21:00", scheduled_datetime="2026-05-20T21:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("901", LEADER_ID, "홀나부캐", "홀리나이트", "support", 8))

    resp = client.get(
        "/api/internal/parties/900/switch-eligibility",
        params={"discord_id": LEADER_ID},
        headers=HEADERS,
    )
    holy = next(c for c in resp.json()["candidates"] if c["name"] == "홀나부캐")
    assert holy["in_other_party"] == {"message_id": "901", "raid_name": "아르모체(4막)"}


# ── 실제 교체 ────────────────────────────────────────────────

def test_switch_character_replaces_slot_character(client, fake_bot):
    before_slot_number = next(
        s for s in asyncio.run(db.get_party_slots("900")) if s["discord_id"] == LEADER_ID
    )["slot_number"]

    resp = client.post(
        "/api/internal/parties/900/switch-character",
        json={"discord_id": LEADER_ID, "character_name": "홀나부캐"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is True
    assert body["left_other_party"] is None

    slots = asyncio.run(db.get_party_slots("900"))
    mine = next(s for s in slots if s["discord_id"] == LEADER_ID)
    assert mine["character_name"] == "홀나부캐"
    assert mine["character_class"] == "홀리나이트"
    assert mine["slot_number"] == before_slot_number  # 슬롯 번호는 그대로 유지


def test_switch_character_downgrades_support_role_if_new_character_not_support(client, fake_bot):
    """기존 역할이 서포터였는데 바꾼 캐릭터가 서포터 직업이 아니면 자동으로 딜러로 내린다."""
    asyncio.run(db.switch_party_character("900", LEADER_ID, "워로드본캐", "워로드", "support"))
    resp = client.post(
        "/api/internal/parties/900/switch-character",
        json={"discord_id": LEADER_ID, "character_name": "홀나부캐"},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    slots = asyncio.run(db.get_party_slots("900"))
    mine = next(s for s in slots if s["discord_id"] == LEADER_ID)
    # 홀리나이트는 서포터 직업이라 role 유지(support)
    assert mine["role"] == "support"


def test_switch_character_leaves_other_party_automatically(client, fake_bot):
    """타 공대에 참여 중인 캐릭터로 교체하면, 그 공대에서는 자동으로 나가야 한다
    (한 캐릭터가 같은 레이드에 동시에 두 공대 참여하지 않도록)."""
    asyncio.run(
        db.create_party(
            message_id="901", channel_id="701", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 21:00", scheduled_datetime="2026-05-20T21:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("901", LEADER_ID, "홀나부캐", "홀리나이트", "support", 8))

    resp = client.post(
        "/api/internal/parties/900/switch-character",
        json={"discord_id": LEADER_ID, "character_name": "홀나부캐"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is True
    assert body["left_other_party"] == "901"

    other_slots = asyncio.run(db.get_party_slots("901"))
    assert other_slots == []  # 다른 공대에서는 빠짐 (혼자였으므로 파티는 해체됨)
    assert (asyncio.run(db.get_party("901")))["status"] == "disbanded"

    slots_900 = asyncio.run(db.get_party_slots("900"))
    mine = next(s for s in slots_900 if s["discord_id"] == LEADER_ID)
    assert mine["character_name"] == "홀나부캐"


def test_switch_character_rejects_same_character(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/900/switch-character",
        json={"discord_id": LEADER_ID, "character_name": "워로드본캐"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "이미 이 캐릭터로 참여 중" in body["reason"]


def test_switch_character_rejects_level_too_low(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/900/switch-character",
        json={"discord_id": LEADER_ID, "character_name": "육성중캐릭"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    slots = asyncio.run(db.get_party_slots("900"))
    assert next(s for s in slots if s["discord_id"] == LEADER_ID)["character_name"] == "워로드본캐"


def test_switch_character_rejects_non_member(client, fake_bot):
    resp = client.post(
        "/api/internal/parties/900/switch-character",
        json={"discord_id": "999999", "character_name": "홀나부캐"},
        headers=HEADERS,
    )
    assert resp.json()["success"] is False
