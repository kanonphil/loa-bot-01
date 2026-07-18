"""회귀 테스트: 공대 생성 직후 리더가 바로 참여할 때(interaction이 포럼 스레드
밖 — 명령어를 실행한 원래 채널 — 에서 온 경우), embed 갱신이 interaction.channel이
아니라 party의 실제 channel_id를 써야 한다.

버그였던 동작: _auto_join_dps/RoleSelectView가 interaction.channel.fetch_message로
스레드의 스타터 메시지를 찾으려다 실패(다른 채널이라 NotFound)해서 embed 갱신이
조용히 스킵됐다. DB에는 정상 참여됐지만 화면(스레드 embed)엔 리더가 안 보이다가,
다른 사람이 스레드 안에서 "참여하기"를 눌러야(그때는 interaction.channel이 진짜
스레드) 비로소 함께 나타났다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.ui import views

LEADER_ID = "222"
MESSAGE_ID = "700"
CHANNEL_ID = "600"  # 파티의 실제 스레드 채널 ID


def _setup_db(tmp_path, monkeypatch, *, total_slots=8, min_level=1700):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(
        db.create_party(
            message_id=MESSAGE_ID, channel_id=CHANNEL_ID, guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=total_slots, min_level=min_level,
        )
    )


def _make_interaction(correct_channel):
    """interaction.channel은 "잘못된"(스레드 밖) 채널이고, interaction.client.get_channel은
    party의 진짜 channel_id로 호출됐을 때만 올바른 채널을 반환하도록 구성."""
    wrong_channel = MagicMock()
    wrong_channel.fetch_message = AsyncMock(side_effect=AssertionError(
        "interaction.channel에서 fetch_message가 호출되면 안 된다 — party의 channel_id를 써야 한다"
    ))

    interaction = MagicMock()
    interaction.user.id = int(LEADER_ID)
    interaction.channel = wrong_channel
    interaction.client.get_channel = MagicMock(
        side_effect=lambda cid: correct_channel if cid == int(CHANNEL_ID) else None
    )
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    return interaction, wrong_channel


def test_auto_join_dps_refreshes_embed_via_party_channel_id(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    correct_msg = MagicMock()
    correct_channel = MagicMock()
    correct_channel.fetch_message = AsyncMock(return_value=correct_msg)
    interaction, wrong_channel = _make_interaction(correct_channel)

    party_view = MagicMock()
    party_view._refresh_party = AsyncMock()

    asyncio.run(
        views._auto_join_dps(
            interaction, LEADER_ID, {"name": "워로드본캐", "class": "워로드"},
            MESSAGE_ID, 8, party_view,
        )
    )

    party_view._refresh_party.assert_awaited_once_with(correct_msg)
    wrong_channel.fetch_message.assert_not_called()
    correct_channel.fetch_message.assert_awaited_once_with(int(MESSAGE_ID))


def test_role_select_callback_refreshes_embed_via_party_channel_id(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)

    correct_msg = MagicMock()
    correct_channel = MagicMock()
    correct_channel.fetch_message = AsyncMock(return_value=correct_msg)
    interaction, wrong_channel = _make_interaction(correct_channel)

    party_view = MagicMock()
    party_view._refresh_party = AsyncMock()

    view = views.RoleSelectView(
        LEADER_ID, {"name": "홀나부캐", "class": "홀리나이트"}, MESSAGE_ID, 8, party_view,
    )
    support_cb = view._make_role_cb("support")
    asyncio.run(support_cb(interaction))

    party_view._refresh_party.assert_awaited_once_with(correct_msg)
    wrong_channel.fetch_message.assert_not_called()
    correct_channel.fetch_message.assert_awaited_once_with(int(MESSAGE_ID))
