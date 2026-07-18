"""회귀 테스트: /원정대 명령어는 캐시를 즉시 보여줘야 하고, 열 때마다 전체 동기화
(sync_characters_for_discord_id — 캐릭터당 아머리 조회 1회 + 0.2초 sleep)를 다시
호출하면 안 된다. 최신화는 화면의 "동기화" 버튼으로만 해야 한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.api.lostark as loa
import bot.database.manager as db
from bot.cogs.expedition import Expedition

DISCORD_ID = "111"


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.add_user_api_key(DISCORD_ID, "본계정", "dummy-key"))
    asyncio.run(db.add_character(DISCORD_ID, "발키리"))
    asyncio.run(db.update_character_cache(DISCORD_ID, "발키리", 1720.0, "홀리나이트"))


def _make_interaction():
    interaction = MagicMock()
    interaction.user.id = int(DISCORD_ID)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def test_expedition_command_does_not_trigger_full_sync(tmp_path, monkeypatch):
    """회귀 테스트: /원정대는 열 때마다 로스트아크 API를 호출해 전체 동기화하면 안 된다
    — 캐시를 즉시 보여주고, 최신화는 화면의 "동기화" 버튼으로만 해야 한다."""
    _setup_db(tmp_path, monkeypatch)
    no_network = AsyncMock(side_effect=AssertionError("/원정대에서 로스트아크 API가 호출되면 안 된다"))
    monkeypatch.setattr(loa, "get_siblings", no_network)
    monkeypatch.setattr(loa, "get_combat_power", no_network)
    monkeypatch.setattr(loa, "get_armory", no_network)

    cog = Expedition(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Expedition.expedition.callback(cog, interaction))

    no_network.assert_not_called()
    interaction.followup.send.assert_awaited_once()


def test_expedition_command_shows_cached_character_immediately(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    cog = Expedition(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Expedition.expedition.callback(cog, interaction))

    embed = interaction.followup.send.call_args.kwargs["embed"]
    assert "발키리" in str(embed.to_dict())
