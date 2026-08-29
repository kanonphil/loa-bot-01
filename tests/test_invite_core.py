"""파티 초대의 공유 핵심 로직(bot/ui/views.py의 _create_invite_core/_accept_invite_core/
_decline_invite_core) 및 db.get_invitable_users/get_user_invites 검증.
웹 API(bot/api/routes/internal.py)와 디스코드 View가 동일하게 쓰는 함수들이다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.ui.views import _create_invite_core, _accept_invite_core, _decline_invite_core

LEADER_ID = "111"
TARGET_ID = "222"
ADMIN_ID = "999"
MESSAGE_ID = "700"


def _make_bot():
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=fake_channel)
    bot.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock(), display_name="리더캐릭"))
    return bot


@pytest.fixture()
def party(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    import config
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})

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
    return MESSAGE_ID


# ── _create_invite_core ──────────────────────────────────────

def test_create_invite_succeeds_and_dms_target(party):
    bot = _make_bot()
    result = asyncio.run(_create_invite_core(bot, party, LEADER_ID, TARGET_ID, 1))

    assert result["success"] is True
    assert asyncio.run(db.get_reserved_slots(party)) == {1: TARGET_ID}
    bot.fetch_user.assert_any_call(int(TARGET_ID))


def test_create_invite_allows_admin_who_is_not_leader(party):
    bot = _make_bot()
    result = asyncio.run(_create_invite_core(bot, party, ADMIN_ID, TARGET_ID, 1))
    assert result["success"] is True


def test_create_invite_rejects_non_leader_non_admin(party):
    bot = _make_bot()
    result = asyncio.run(_create_invite_core(bot, party, "555", TARGET_ID, 1))
    assert result["success"] is False
    assert "파티장만" in result["reason"]
    assert asyncio.run(db.get_reserved_slots(party)) == {}


def test_create_invite_rejects_occupied_slot(party):
    asyncio.run(db.auto_assign_slot(party, "333", "다른캐릭", "버서커", "dps", 8))
    bot = _make_bot()
    result = asyncio.run(_create_invite_core(bot, party, LEADER_ID, TARGET_ID, 1))
    assert result["success"] is False
    assert "슬롯" in result["reason"]


def test_create_invite_rejects_target_already_in_party(party):
    asyncio.run(db.auto_assign_slot(party, TARGET_ID, "타겟캐릭", "워로드", "dps", 8))
    bot = _make_bot()
    result = asyncio.run(_create_invite_core(bot, party, LEADER_ID, TARGET_ID, 2))
    assert result["success"] is False
    assert "이미 파티에 참여" in result["reason"]


def test_create_invite_rejects_duplicate_invite(party):
    bot = _make_bot()
    asyncio.run(_create_invite_core(bot, party, LEADER_ID, TARGET_ID, 1))
    result = asyncio.run(_create_invite_core(bot, party, LEADER_ID, "444", 1))
    assert result["success"] is False
    assert "슬롯" in result["reason"]  # 슬롯 1은 이미 예약됨


def test_create_invite_rolls_back_on_dm_failure(party):
    import discord

    bot = _make_bot()
    bot.fetch_user = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "DM 비활성화"))
    result = asyncio.run(_create_invite_core(bot, party, LEADER_ID, TARGET_ID, 1))

    assert result["success"] is False
    assert "DM" in result["reason"]
    assert asyncio.run(db.get_reserved_slots(party)) == {}  # 롤백돼야 함


# ── _accept_invite_core ──────────────────────────────────────

def test_accept_invite_succeeds_and_notifies_leader(party):
    asyncio.run(db.create_invite(party, TARGET_ID, 1))
    bot = _make_bot()

    result = asyncio.run(_accept_invite_core(bot, party, TARGET_ID, "타겟캐릭", "dps"))

    assert result["success"] is True
    slots = asyncio.run(db.get_party_slots(party))
    assert len(slots) == 1
    assert slots[0]["character_name"] == "타겟캐릭"
    bot.fetch_user.assert_any_call(int(LEADER_ID))


def test_accept_invite_rejects_character_not_in_qualifying_list(party):
    asyncio.run(db.create_invite(party, TARGET_ID, 1))
    bot = _make_bot()
    result = asyncio.run(_accept_invite_core(bot, party, TARGET_ID, "존재안하는캐릭", "dps"))
    assert result["success"] is False
    assert "참여 가능한 캐릭터 목록" in result["reason"]


def test_accept_invite_rejects_support_role_for_non_support_class(party):
    asyncio.run(db.create_invite(party, TARGET_ID, 1))
    bot = _make_bot()
    result = asyncio.run(_accept_invite_core(bot, party, TARGET_ID, "타겟캐릭", "support"))
    assert result["success"] is False
    assert "서포터 역할을 맡을 수 없습니다" in result["reason"]


def test_accept_invite_rejects_when_party_disbanded(party):
    asyncio.run(db.create_invite(party, TARGET_ID, 1))
    asyncio.run(db.disband_party(party))
    bot = _make_bot()
    result = asyncio.run(_accept_invite_core(bot, party, TARGET_ID, "타겟캐릭", "dps"))
    assert result["success"] is False
    assert "종료된 공대" in result["reason"]


def test_accept_invite_rejects_when_no_reservation(party):
    """초대 자체가 없는데 accept를 호출하면(예: 이미 취소된 초대) assign_invite_slot이 거부해야 한다."""
    bot = _make_bot()
    result = asyncio.run(_accept_invite_core(bot, party, TARGET_ID, "타겟캐릭", "dps"))
    assert result["success"] is False


# ── _decline_invite_core ─────────────────────────────────────

def test_decline_invite_succeeds_and_notifies_leader(party):
    asyncio.run(db.create_invite(party, TARGET_ID, 1))
    bot = _make_bot()

    result = asyncio.run(_decline_invite_core(bot, party, TARGET_ID))

    assert result["success"] is True
    assert asyncio.run(db.get_reserved_slots(party)) == {}
    bot.fetch_user.assert_any_call(int(LEADER_ID))


def test_decline_invite_rejects_when_no_such_invite(party):
    bot = _make_bot()
    result = asyncio.run(_decline_invite_core(bot, party, TARGET_ID))
    assert result["success"] is False
    assert "초대 정보를 찾을 수 없습니다" in result["reason"]


def test_decline_invite_rejects_when_party_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    bot = _make_bot()
    result = asyncio.run(_decline_invite_core(bot, "nonexistent", TARGET_ID))
    assert result["success"] is False
    assert "파티를 찾을 수 없습니다" in result["reason"]


# ── db.get_invitable_users / get_user_invites ────────────────

def test_get_invitable_users_excludes_given_ids(party):
    users = asyncio.run(db.get_invitable_users({LEADER_ID}))
    ids = {u["discord_id"] for u in users}
    assert TARGET_ID in ids
    assert LEADER_ID not in ids
    target = next(u for u in users if u["discord_id"] == TARGET_ID)
    assert target["representative"] == "타겟캐릭"


def test_get_user_invites_joins_party_info(party):
    asyncio.run(db.create_invite(party, TARGET_ID, 3))
    invites = asyncio.run(db.get_user_invites(TARGET_ID))
    assert len(invites) == 1
    assert invites[0]["message_id"] == party
    assert invites[0]["slot_number"] == 3
    assert invites[0]["raid_name"] == "아르모체(4막)"
    assert invites[0]["leader_id"] == LEADER_ID


def test_get_user_invites_empty_when_none(party):
    assert asyncio.run(db.get_user_invites(TARGET_ID)) == []
