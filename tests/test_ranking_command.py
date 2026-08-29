"""/랭킹 슬래시 커맨드(bot/cogs/ranking.py) 검증. db.get_expedition_ranking 자체의
집계 로직은 test_ranking.py에서 이미 검증되므로, 여기서는 커맨드가 옵션(기준/역할)을
올바르게 전달하고 임베드를 만들어 보내는지만 확인한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.database.manager as db
from bot.cogs.ranking import Ranking


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))

    async def setup():
        await db.init_db()
        await db.add_character("111", "발키리")
        await db.add_character("222", "바드")
        await db.update_character_cache("111", "발키리", 1720.0, "홀리나이트")
        await db.update_character_cache("222", "바드", 1710.0, "바드")
        await db.update_character_combat_power("111", "발키리", 4_300_000)
        await db.update_character_combat_power("222", "바드", 4_100_000)

    asyncio.run(setup())


def _make_interaction():
    interaction = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def test_ranking_command_default_metric_shows_combat_power(seeded):
    cog = Ranking(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Ranking.ranking.callback(cog, interaction, metric="combat_power", role=None))

    interaction.followup.send.assert_awaited_once()
    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert "전투력" in embed.title
    assert "발키리" in embed.description
    assert "바드" in embed.description


def test_ranking_command_no_data_sends_plain_message(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    cog = Ranking(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Ranking.ranking.callback(cog, interaction, metric="combat_power", role=None))

    interaction.followup.send.assert_awaited_once()
    assert "embed" not in interaction.followup.send.call_args.kwargs
    message = interaction.followup.send.call_args.args[0]
    assert "랭킹 데이터가 없습니다" in message
