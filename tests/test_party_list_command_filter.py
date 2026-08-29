"""/공대확인 명령어의 레이드/난이도 필터 검증. 웹 /parties는 이미 검색이 있었는데
디스코드 쪽엔 없어서 생긴 격차를 메운다 — bot/cogs/party.py의 Party.party_list."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.cogs.party import Party

GUILD_ID = "1"


@pytest.fixture()
def two_raids(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_forum_channel(GUILD_ID, "555"))

    asyncio.run(
        db.create_party(
            message_id="1", channel_id="700", guild_id=GUILD_ID, leader_id="111",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(
        db.create_party(
            message_id="2", channel_id="701", guild_id=GUILD_ID, leader_id="222",
            raid_name="세르카", difficulty="하드", proficiency="숙련",
            scheduled_time="05/21 20:00", scheduled_datetime="2026-05-21T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )


def _make_interaction():
    interaction = MagicMock()
    interaction.guild_id = int(GUILD_ID)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def test_party_list_without_filter_shows_all(two_raids):
    cog = Party(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Party.party_list.callback(cog, interaction, raid_name=None, difficulty=None))

    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert "총 **2**개" in embed.description


def test_party_list_filters_by_raid_name(two_raids):
    cog = Party(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Party.party_list.callback(cog, interaction, raid_name="세르카", difficulty=None))

    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert "총 **1**개" in embed.description
    assert "세르카" in str(embed.to_dict())
    assert "아르모체" not in str(embed.to_dict())


def test_party_list_filters_by_raid_and_difficulty_with_no_match(two_raids):
    cog = Party(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Party.party_list.callback(cog, interaction, raid_name="세르카", difficulty="노말"))

    interaction.followup.send.assert_awaited_once()
    message = interaction.followup.send.call_args.args[0]
    assert "조건에 맞는" in message
