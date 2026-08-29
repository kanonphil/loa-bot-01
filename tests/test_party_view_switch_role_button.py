"""디스코드 파티 뷰의 "역할 변경" 버튼(PartyView._handle_switch_role) 검증.
_switch_role_core/db.switch_party_role은 이미 test_party_role_switch.py에서
검증되므로, 여기서는 버튼 핸들러가 현재 role을 보고 올바른 방향으로 토글을
시도하고, 성공/실패 메시지를 그대로 전달하는지만 확인한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.ui.views import PartyView

LEADER_ID = "222"
OTHER_ID = "333"


@pytest.fixture()
def party(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(db.add_character(LEADER_ID, "홀나캐릭"))
    asyncio.run(db.update_character_cache(LEADER_ID, "홀나캐릭", item_level=1710.0, character_class="홀리나이트"))
    asyncio.run(db.set_user_api_key(OTHER_ID, "dummy-key-2"))
    asyncio.run(db.add_character(OTHER_ID, "워로드캐릭"))
    asyncio.run(db.update_character_cache(OTHER_ID, "워로드캐릭", item_level=1710.0, character_class="워로드"))

    asyncio.run(
        db.create_party(
            message_id="900", channel_id="700", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("900", LEADER_ID, "홀나캐릭", "홀리나이트", "support", 8))
    asyncio.run(db.auto_assign_slot("900", OTHER_ID, "워로드캐릭", "워로드", "dps", 8))
    return "900"


def _make_interaction(discord_id: str, channel_id: str = "700"):
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    fake_client = MagicMock()
    fake_client.get_channel = MagicMock(return_value=fake_channel)

    interaction = MagicMock()
    interaction.channel.id = int(channel_id)
    interaction.user.id = int(discord_id)
    interaction.client = fake_client
    interaction.response.send_message = AsyncMock()
    return interaction


def test_switch_role_button_toggles_support_to_dps(party):
    view = PartyView(total_slots=8)
    interaction = _make_interaction(LEADER_ID)

    asyncio.run(view._handle_switch_role(interaction))

    interaction.response.send_message.assert_awaited_once()
    message = interaction.response.send_message.call_args.args[0]
    assert "딜러" in message
    slots = asyncio.run(db.get_party_slots(party))
    mine = next(s for s in slots if s["discord_id"] == LEADER_ID)
    assert mine["role"] == "dps"


def test_switch_role_button_rejects_non_support_class_with_db_reason(party):
    """워로드(딜러 전용 직업)는 서포터로 못 바꾼다 — db.switch_party_role이 만드는
    사유 메시지가 그대로 사용자에게 전달돼야 한다(핸들러가 따로 재검증하지 않음)."""
    view = PartyView(total_slots=8)
    interaction = _make_interaction(OTHER_ID)

    asyncio.run(view._handle_switch_role(interaction))

    interaction.response.send_message.assert_awaited_once()
    message = interaction.response.send_message.call_args.args[0]
    assert "서포터 역할을 맡을 수 없습니다" in message
    slots = asyncio.run(db.get_party_slots(party))
    mine = next(s for s in slots if s["discord_id"] == OTHER_ID)
    assert mine["role"] == "dps"  # 실패했으니 그대로 유지


def test_switch_role_button_rejects_non_member(party):
    view = PartyView(total_slots=8)
    interaction = _make_interaction("999999")

    asyncio.run(view._handle_switch_role(interaction))

    interaction.response.send_message.assert_awaited_once()
    message = interaction.response.send_message.call_args.args[0]
    assert "참여 중이 아닙니다" in message
