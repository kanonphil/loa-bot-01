"""회귀 테스트: /전체레이드체크는 캐릭터마다 매번 로스트아크 API를 호출하면 안 되고,
캐시된 아이템레벨이 있으면 그대로 써야 한다 — 이전에는 캐시 유무와 무관하게 항상
캐릭터 수만큼 API를 호출해서 캐릭터가 많은 유저는 느렸다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.database.manager as db
from bot.cogs.raid import Raid

DISCORD_ID = "111"


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.set_user_api_key(DISCORD_ID, "dummy-key"))


def _make_interaction():
    interaction = MagicMock()
    interaction.user.id = int(DISCORD_ID)
    interaction.response.defer = AsyncMock()
    interaction.followup.send = AsyncMock()
    return interaction


def test_raid_check_all_uses_cache_without_api_call(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    asyncio.run(db.add_character(DISCORD_ID, "발키리"))
    asyncio.run(db.add_character(DISCORD_ID, "워로드부캐"))
    asyncio.run(db.update_character_cache(DISCORD_ID, "발키리", 1720.0, "홀리나이트"))
    asyncio.run(db.update_character_cache(DISCORD_ID, "워로드부캐", 1700.0, "워로드"))

    no_network = AsyncMock(side_effect=AssertionError("캐시가 있는데 API가 호출되면 안 된다"))
    import bot.cogs.raid as raid_module
    monkeypatch.setattr(raid_module.loa, "get_character_info", no_network)

    cog = Raid(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Raid.raid_check_all.callback(cog, interaction))

    no_network.assert_not_called()
    kwargs = interaction.followup.send.call_args.kwargs
    assert len(kwargs["embeds"]) == 2


def test_raid_check_all_falls_back_to_api_when_cache_missing(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    asyncio.run(db.add_character(DISCORD_ID, "발키리"))  # 캐시 없음

    async def fake_get_character_info(api_key, name):
        return {"CharacterName": name, "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00"}

    import bot.cogs.raid as raid_module
    monkeypatch.setattr(raid_module.loa, "get_character_info", fake_get_character_info)

    cog = Raid(bot=MagicMock())
    interaction = _make_interaction()
    asyncio.run(Raid.raid_check_all.callback(cog, interaction))

    kwargs = interaction.followup.send.call_args.kwargs
    assert len(kwargs["embeds"]) == 1
    # 보충 조회한 결과가 캐시에 반영돼 다음부터는 API 호출 없이도 재사용된다
    cached = asyncio.run(db.get_cached_characters(DISCORD_ID))
    assert cached[0]["item_level"] == 1720.0
