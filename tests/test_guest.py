"""bot/services/guest.py::lookup_guest_character 검증.
Lost Ark API 호출은 monkeypatch로 대체 — 실제 외부망 호출 없음."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest

import bot.database.manager as db
import bot.services.guest as guest_service
import config

PROFILE_ARMORY = {
    "ArmoryProfile": {
        "CharacterName": "게스트캐릭",
        "CharacterClassName": "디스트로이어",
        "ItemAvgLevel": "1680.00",
        "CombatPower": "98765432",
    }
}


@pytest.fixture()
def db_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())


def test_lookup_returns_error_when_lookup_id_not_configured(db_setup, monkeypatch):
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", "")
    result = asyncio.run(guest_service.lookup_guest_character("아무캐릭"))
    assert "error" in result


def test_lookup_returns_error_when_admin_key_missing(db_setup, monkeypatch):
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", "999")
    result = asyncio.run(guest_service.lookup_guest_character("아무캐릭"))
    assert "error" in result


def test_lookup_returns_parsed_character_info(db_setup, monkeypatch):
    asyncio.run(db.add_user_api_key("999", "관리자", "dummy-loa-key"))
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", "999")

    async def _fake_get_armory(api_key, name, filters=None):
        assert filters == "profiles"
        return PROFILE_ARMORY

    monkeypatch.setattr(guest_service.loa, "get_armory", _fake_get_armory)

    result = asyncio.run(guest_service.lookup_guest_character("게스트캐릭"))
    assert result["character_name"] == "게스트캐릭"
    assert result["character_class"] == "디스트로이어"
    assert result["item_level"] == 1680.0
    assert result["combat_power"] == "98765432"


def test_lookup_returns_error_when_character_not_found(db_setup, monkeypatch):
    asyncio.run(db.add_user_api_key("999", "관리자", "dummy-loa-key"))
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", "999")

    async def _fake_get_armory_none(api_key, name, filters=None):
        return None

    monkeypatch.setattr(guest_service.loa, "get_armory", _fake_get_armory_none)

    result = asyncio.run(guest_service.lookup_guest_character("없는캐릭"))
    assert "error" in result
    assert "없는캐릭" in result["error"]
