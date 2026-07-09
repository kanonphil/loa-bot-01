"""bot/services/armory.py + /api/internal/armory-detail 엔드포인트 검증.
Lost Ark API 호출은 monkeypatch로 대체 — 실제 외부망 호출 없음."""
import json
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db
import bot.services.armory as armory_service
import bot.services.expedition as expedition_service

HEADERS = {"X-Webapp-Key": "test-webapp-key"}

SIBLINGS = [{"CharacterName": "발키리", "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00"}]

ARMORY_RAW = {
    "ArmoryProfile": {
        "CharacterName": "발키리",
        "CharacterClassName": "홀리나이트",
        "ItemAvgLevel": "1720.00",
        "CombatPower": "123456789",
    },
    "ArmorySkills": [
        {
            "Name": "심판의 빛",
            "Level": 10,
            "Tripods": [{"Tier": 0, "Slot": 1, "Name": "선택됨", "IsSelected": True}],
            "Rune": None,
        }
    ],
    "ArkPassive": {
        "Title": "해방자",
        "Points": [{"Name": "진화", "Value": 140, "Description": "6랭크 27레벨"}],
        "Effects": [],
    },
    "ArmoryEquipment": [
        {
            "Type": "목걸이",
            "Name": "목걸이",
            "Grade": "고대",
            "Tooltip": json.dumps(
                {"Element_001": {"type": "ItemTitle", "value": {"qualityValue": 88}}}
            ),
        }
    ],
    "ArmoryGem": {"Gems": []},
    "ArkGrid": {"Slots": [], "Effects": []},
}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.add_user_api_key("111", "본계정", "dummy-loa-key"))

    from bot.api.server import app

    return TestClient(app)


async def _fake_get_siblings(api_key, name):
    return SIBLINGS


async def _fake_get_armory(api_key, name, filters=None):
    return ARMORY_RAW


def test_get_character_armory_detail_returns_parsed_data(client, monkeypatch):
    monkeypatch.setattr(expedition_service.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(armory_service.loa, "get_armory", _fake_get_armory)

    result = asyncio.run(armory_service.get_character_armory_detail("111", "발키리"))
    assert result["character_name"] == "발키리"
    assert len(result["skills"]) == 1
    assert result["accessories"][0]["quality"] == 88


def test_get_character_armory_detail_returns_error_when_not_registered(client):
    result = asyncio.run(armory_service.get_character_armory_detail("999", "없는캐릭"))
    assert "error" in result
    assert "/api등록" in result["error"]


def test_armory_detail_endpoint_requires_webapp_key(client):
    resp = client.get(
        "/api/internal/armory-detail", params={"discord_id": "111", "character_name": "발키리"}
    )
    assert resp.status_code == 401


def test_armory_detail_endpoint_returns_parsed_data(client, monkeypatch):
    monkeypatch.setattr(expedition_service.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(armory_service.loa, "get_armory", _fake_get_armory)

    resp = client.get(
        "/api/internal/armory-detail",
        params={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["character_name"] == "발키리"
    assert body["ark_passive"]["points"][0]["description"] == "6랭크 27레벨"
