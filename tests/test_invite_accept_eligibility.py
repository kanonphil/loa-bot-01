"""회귀 테스트: 초대(InviteResponseView.accept)를 통한 참여가 일반 "참여하기" 버튼과
동일한 참여 규칙(골드 완료 캐릭터 제외, 같은 레이드 타 공대 중복 참여 제외)을 지켜야
한다. 이전에는 초대 수락 시 최소 아이템 레벨만 확인해서, 이미 이번 주 골드를 완료했거나
같은 레이드 다른 공대에 참여 중인 캐릭터로도 초대를 받아 참여할 수 있는 구멍이 있었다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.ui import views

INVITEE_ID = "333"
MESSAGE_ID = "700"
CHANNEL_ID = "600"
CHAR_NAME = "워로드본캐"


def _setup_party(tmp_path, monkeypatch, *, total_slots=8, min_level=1700):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(INVITEE_ID, "dummy-key"))
    asyncio.run(db.add_character(INVITEE_ID, CHAR_NAME))
    asyncio.run(db.update_character_cache(INVITEE_ID, CHAR_NAME, 1720, "워로드"))
    asyncio.run(
        db.create_party(
            message_id=MESSAGE_ID, channel_id=CHANNEL_ID, guild_id="1", leader_id="111",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=total_slots, min_level=min_level,
        )
    )
    asyncio.run(db.create_invite(MESSAGE_ID, INVITEE_ID, 1))


def _make_interaction():
    interaction = MagicMock()
    interaction.user.id = int(INVITEE_ID)
    interaction.response.edit_message = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.client.fetch_user = AsyncMock(side_effect=AssertionError("리더 DM이 발송되면 안 된다"))

    fake_msg = AsyncMock()
    fake_msg.edit = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_msg)
    interaction.client.get_channel = MagicMock(return_value=fake_channel)
    return interaction


def _run_accept(interaction, party):
    view = views.InviteResponseView(MESSAGE_ID, party, INVITEE_ID, client=interaction.client)
    asyncio.run(view.accept.callback(interaction))


def test_accept_rejects_gold_done_character(tmp_path, monkeypatch):
    _setup_party(tmp_path, monkeypatch)
    party = asyncio.run(db.get_party(MESSAGE_ID))
    # 완료 기록은 party의 일정(scheduled_datetime) 기준 주차로 남겨야
    # get_party_join_eligibility가 같은 주차로 비교해서 걸러낸다.
    party_week = db.get_week_key_for_dt(party["scheduled_datetime"])
    asyncio.run(db.add_completion(INVITEE_ID, CHAR_NAME, "아르모체(4막)", "노말", party_week))

    interaction = _make_interaction()
    _run_accept(interaction, party)

    content = interaction.response.edit_message.call_args.kwargs["content"]
    assert "골드 완료" in content
    slots = asyncio.run(db.get_party_slots(MESSAGE_ID))
    assert slots == []  # 실제로 파티에 배정되지 않아야 한다


def test_accept_rejects_character_already_in_other_party_same_raid(tmp_path, monkeypatch):
    _setup_party(tmp_path, monkeypatch)
    # 같은 레이드의 다른(활성) 공대에 이 캐릭터가 이미 참여 중인 상태를 만든다
    asyncio.run(
        db.create_party(
            message_id="701", channel_id="601", guild_id="1", leader_id="222",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    ok, _, _ = asyncio.run(
        db.auto_assign_slot("701", INVITEE_ID, CHAR_NAME, "워로드", "dps", 8)
    )
    assert ok

    party = asyncio.run(db.get_party(MESSAGE_ID))
    interaction = _make_interaction()
    _run_accept(interaction, party)

    content = interaction.response.edit_message.call_args.kwargs["content"]
    assert "다른 공대 참여 중" in content
    slots = asyncio.run(db.get_party_slots(MESSAGE_ID))
    assert slots == []


def test_accept_rejects_when_party_already_closed(tmp_path, monkeypatch):
    """회귀 테스트: 기존 코드는 파티 status가 disbanded인지만 확인해서, 모집 마감(closed)
    이나 만석(full) 상태에서도 초대 수락으로 참여할 수 있는 구멍이 있었다."""
    _setup_party(tmp_path, monkeypatch)
    asyncio.run(db.close_party(MESSAGE_ID))
    party = asyncio.run(db.get_party(MESSAGE_ID))

    interaction = _make_interaction()
    _run_accept(interaction, party)

    content = interaction.response.edit_message.call_args.kwargs["content"]
    assert "마감" in content
    slots = asyncio.run(db.get_party_slots(MESSAGE_ID))
    assert slots == []


def test_accept_succeeds_for_qualifying_character(tmp_path, monkeypatch):
    _setup_party(tmp_path, monkeypatch)
    party = asyncio.run(db.get_party(MESSAGE_ID))

    interaction = _make_interaction()
    interaction.client.fetch_user = AsyncMock(return_value=MagicMock(send=AsyncMock()))
    _run_accept(interaction, party)

    content = interaction.response.edit_message.call_args.kwargs["content"]
    assert "참여했습니다" in content
    slots = asyncio.run(db.get_party_slots(MESSAGE_ID))
    assert len(slots) == 1
    assert slots[0]["character_name"] == CHAR_NAME
