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


# ── 캐시 우선 조회 — "동기화" 버튼을 눌러야만 API를 다시 호출한다 ──────────

def test_get_armory_detail_uses_cache_without_calling_api_again(client, monkeypatch):
    """캐시가 있으면(직전에 한 번이라도 조회/동기화했으면) API를 다시 호출하지 않고
    캐시된 값을 그대로 반환해야 한다 — F5로도 새 API 호출이 안 나가는 것이 이 기능의 핵심."""
    asyncio.run(db.add_character("111", "발키리"))
    call_count = {"n": 0}

    async def counting_get_armory(api_key, name, filters=None):
        call_count["n"] += 1
        return ARMORY_RAW

    monkeypatch.setattr(expedition_service.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(armory_service.loa, "get_armory", counting_get_armory)

    first = asyncio.run(armory_service.get_character_armory_detail("111", "발키리"))
    second = asyncio.run(armory_service.get_character_armory_detail("111", "발키리"))

    assert call_count["n"] == 1  # 두 번째 조회는 캐시만 읽고 API는 안 부름
    assert first["character_name"] == second["character_name"] == "발키리"
    assert second["synced_at"] is not None


def test_sync_character_armory_detail_always_calls_api(client, monkeypatch):
    """"동기화" 버튼(sync_character_armory_detail)은 캐시 여부와 무관하게 항상 API를 호출한다."""
    asyncio.run(db.add_character("111", "발키리"))
    call_count = {"n": 0}

    async def counting_get_armory(api_key, name, filters=None):
        call_count["n"] += 1
        return ARMORY_RAW

    monkeypatch.setattr(expedition_service.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(armory_service.loa, "get_armory", counting_get_armory)

    asyncio.run(armory_service.sync_character_armory_detail("111", "발키리"))
    asyncio.run(armory_service.sync_character_armory_detail("111", "발키리"))

    assert call_count["n"] == 2


def test_sync_updates_combat_power_and_cache_for_registered_character(client, monkeypatch):
    """등록된 캐릭터라면 동기화 시 combat_power와 상세 캐시가 실제로 저장돼야 한다
    — 랭킹에 전투력이 반영되려면 이 저장이 성공해야 한다."""
    asyncio.run(db.add_character("111", "발키리"))
    monkeypatch.setattr(expedition_service.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(armory_service.loa, "get_armory", _fake_get_armory)

    asyncio.run(armory_service.sync_character_armory_detail("111", "발키리"))

    rows = asyncio.run(db.get_expedition_ranking("combat_power"))
    assert any(r["character_name"] == "발키리" and r["value"] == 123456789 for r in rows)
    cached = asyncio.run(db.get_character_armory_cache("111", "발키리"))
    assert cached is not None
    assert cached["detail"]["character_name"] == "발키리"


def test_sync_does_not_crash_when_character_not_registered(client, monkeypatch, capsys):
    """미등록 캐릭터(user_characters에 없음)를 동기화하면 combat_power/캐시 저장은
    조용히 스킵되지만(행이 없어 매칭 안 됨), 상세 정보 자체는 정상 반환돼야 하고
    원인을 알 수 있게 로그가 남아야 한다."""
    monkeypatch.setattr(expedition_service.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(armory_service.loa, "get_armory", _fake_get_armory)

    result = asyncio.run(armory_service.sync_character_armory_detail("111", "발키리"))
    assert result["character_name"] == "발키리"
    assert result["synced_at"] is None
    printed = capsys.readouterr().out
    assert "combat_power 갱신 실패" in printed


def test_armory_detail_sync_endpoint_calls_api(client, monkeypatch):
    asyncio.run(db.add_character("111", "발키리"))
    monkeypatch.setattr(expedition_service.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(armory_service.loa, "get_armory", _fake_get_armory)

    resp = client.post(
        "/api/internal/armory-detail/sync",
        params={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["character_name"] == "발키리"
