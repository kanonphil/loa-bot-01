"""bot/cogs/account.py의 /api등록 길드 확인 로직 검증.
실제 로스트아크 API 호출(bot.api.lostark)은 monkeypatch로 대체."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock

import pytest

import bot.database.manager as db
import config
from bot.cogs.account import verify_and_register_api_key

SIBLINGS = [{"CharacterName": "발키리", "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00"}]


@pytest.fixture()
def clean_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


def test_registration_succeeds_when_guild_matches(clean_db, monkeypatch):
    monkeypatch.setattr(config, "REQUIRED_GUILD_NAME", "동물롱장")

    async def fake_get_siblings(api_key, name):
        return SIBLINGS

    async def fake_get_armory(api_key, name):
        return {"ArmoryProfile": {"GuildName": "동물롱장"}}

    monkeypatch.setattr("bot.cogs.account.loa.get_siblings", fake_get_siblings)
    monkeypatch.setattr("bot.cogs.account.loa.get_armory", fake_get_armory)

    success, message, siblings, api_key_id = asyncio.run(
        verify_and_register_api_key("111", "dummy-key", "발키리")
    )

    assert success is True
    assert siblings == SIBLINGS
    assert api_key_id is not None
    assert asyncio.run(db.get_user_api_key("111")) == "dummy-key"
    accounts = asyncio.run(db.list_user_api_keys("111"))
    assert len(accounts) == 1
    assert accounts[0]["label"] == "발키리"
    assert asyncio.run(db.get_user_api_key_by_id(api_key_id)) == "dummy-key"


def test_registration_rejected_when_guild_mismatches(clean_db, monkeypatch):
    monkeypatch.setattr(config, "REQUIRED_GUILD_NAME", "동물롱장")

    async def fake_get_siblings(api_key, name):
        return SIBLINGS

    async def fake_get_armory(api_key, name):
        return {"ArmoryProfile": {"GuildName": "다른길드"}}

    monkeypatch.setattr("bot.cogs.account.loa.get_siblings", fake_get_siblings)
    monkeypatch.setattr("bot.cogs.account.loa.get_armory", fake_get_armory)

    success, message, siblings, api_key_id = asyncio.run(
        verify_and_register_api_key("111", "dummy-key", "발키리")
    )

    assert success is False
    assert "동물롱장" in message
    assert "다른길드" in message
    assert api_key_id is None
    assert asyncio.run(db.get_user_api_key("111")) is None
    assert asyncio.run(db.list_user_api_keys("111")) == []


def test_registration_rejected_when_no_guild(clean_db, monkeypatch):
    monkeypatch.setattr(config, "REQUIRED_GUILD_NAME", "동물롱장")

    async def fake_get_siblings(api_key, name):
        return SIBLINGS

    async def fake_get_armory(api_key, name):
        return {"ArmoryProfile": {"GuildName": ""}}

    monkeypatch.setattr("bot.cogs.account.loa.get_siblings", fake_get_siblings)
    monkeypatch.setattr("bot.cogs.account.loa.get_armory", fake_get_armory)

    success, message, siblings, api_key_id = asyncio.run(
        verify_and_register_api_key("111", "dummy-key", "발키리")
    )

    assert success is False
    assert "길드 미가입" in message
    assert api_key_id is None
    assert asyncio.run(db.get_user_api_key("111")) is None


def test_guild_check_skipped_when_required_guild_name_empty(clean_db, monkeypatch):
    monkeypatch.setattr(config, "REQUIRED_GUILD_NAME", "")

    async def fake_get_siblings(api_key, name):
        return SIBLINGS

    get_armory_mock = AsyncMock()
    monkeypatch.setattr("bot.cogs.account.loa.get_siblings", fake_get_siblings)
    monkeypatch.setattr("bot.cogs.account.loa.get_armory", get_armory_mock)

    success, message, siblings, api_key_id = asyncio.run(
        verify_and_register_api_key("111", "dummy-key", "발키리")
    )

    assert success is True
    assert asyncio.run(db.get_user_api_key("111")) == "dummy-key"
    get_armory_mock.assert_not_called()


def test_registration_rejected_when_character_not_found(clean_db, monkeypatch):
    monkeypatch.setattr(config, "REQUIRED_GUILD_NAME", "동물롱장")

    async def fake_get_siblings(api_key, name):
        return None

    monkeypatch.setattr("bot.cogs.account.loa.get_siblings", fake_get_siblings)

    success, message, siblings, api_key_id = asyncio.run(
        verify_and_register_api_key("111", "dummy-key", "없는캐릭터")
    )

    assert success is False
    assert "찾을 수 없습니다" in message
    assert api_key_id is None
    assert asyncio.run(db.get_user_api_key("111")) is None


def test_second_account_registration_adds_without_replacing_first(clean_db, monkeypatch):
    monkeypatch.setattr(config, "REQUIRED_GUILD_NAME", "동물롱장")

    async def fake_get_armory(api_key, name):
        return {"ArmoryProfile": {"GuildName": "동물롱장"}}

    first_siblings = SIBLINGS
    second_siblings = [
        {"CharacterName": "슬레이어부캐", "CharacterClassName": "슬레이어", "ItemMaxLevel": "1,680.00"}
    ]

    async def fake_get_siblings_first(api_key, name):
        return first_siblings

    monkeypatch.setattr("bot.cogs.account.loa.get_siblings", fake_get_siblings_first)
    monkeypatch.setattr("bot.cogs.account.loa.get_armory", fake_get_armory)

    success1, _, _, id1 = asyncio.run(
        verify_and_register_api_key("111", "key-a", "발키리")
    )
    assert success1 is True

    async def fake_get_siblings_second(api_key, name):
        return second_siblings

    monkeypatch.setattr("bot.cogs.account.loa.get_siblings", fake_get_siblings_second)

    success2, message2, siblings2, id2 = asyncio.run(
        verify_and_register_api_key("111", "key-b", "슬레이어부캐")
    )

    assert success2 is True
    assert siblings2 == second_siblings
    assert id2 is not None
    assert id2 != id1

    accounts = asyncio.run(db.list_user_api_keys("111"))
    assert len(accounts) == 2
    labels = {acc["label"] for acc in accounts}
    assert labels == {"발키리", "슬레이어부캐"}

    # 첫 번째 계정(레거시 컬럼)은 그대로 유지되고 두 번째 계정도 개별 조회 가능
    assert asyncio.run(db.get_user_api_key("111")) == "key-a"
    assert asyncio.run(db.get_user_api_key_by_id(id2)) == "key-b"
