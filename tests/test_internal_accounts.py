"""bot/api/routes/internal.py의 부계정(로스트아크 API 키) 추가 엔드포인트 검증.
웹 원정대 관리 페이지의 "부계정 추가" 폼이 호출하는 API — Discord /api등록(ApiKeyModal)과
동일한 검증(+길드 확인) 로직(bot.services.expedition.verify_and_register_api_key)을 그대로 쓴다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db
import config
from bot.api.routes import internal

HEADERS = {"X-Webapp-Key": "test-webapp-key"}

SIBLINGS = [
    {"CharacterName": "발키리", "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00"},
    {"CharacterName": "워로드부캐", "CharacterClassName": "워로드", "ItemMaxLevel": "1,700.00"},
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    monkeypatch.setattr(config, "REQUIRED_GUILD_NAME", "동물롱장")

    from bot.api.server import app

    return TestClient(app)


async def _fake_get_siblings(api_key, name):
    return SIBLINGS


async def _fake_get_armory_matching_guild(api_key, name):
    return {"ArmoryProfile": {"GuildName": "동물롱장"}}


def test_add_account_registers_whole_expedition(client, monkeypatch):
    monkeypatch.setattr(internal.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(internal.loa, "get_armory", _fake_get_armory_matching_guild)

    resp = client.post(
        "/api/internal/accounts/add",
        json={"discord_id": "111", "api_key": "dummy-key", "character_name": "발키리"},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body == {"success": True, "label": "발키리", "added": 2, "total": 2}

    accounts = asyncio.run(db.list_user_api_keys("111"))
    assert len(accounts) == 1
    assert accounts[0]["label"] == "발키리"
    assert set(asyncio.run(db.get_user_characters("111"))) == {"발키리", "워로드부캐"}


def test_add_account_rejects_wrong_guild(client, monkeypatch):
    async def fake_get_armory_wrong_guild(api_key, name):
        return {"ArmoryProfile": {"GuildName": "다른길드"}}

    monkeypatch.setattr(internal.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(internal.loa, "get_armory", fake_get_armory_wrong_guild)

    resp = client.post(
        "/api/internal/accounts/add",
        json={"discord_id": "111", "api_key": "dummy-key", "character_name": "발키리"},
        headers=HEADERS,
    )

    body = resp.json()
    assert body["success"] is False
    assert "다른길드" in body["reason"]
    assert asyncio.run(db.list_user_api_keys("111")) == []


def test_add_account_as_second_account_keeps_first(client, monkeypatch):
    """이미 계정이 하나 등록돼 있어도, 두 번째 계정 추가는 첫 번째를 건드리지 않고 별도로 쌓인다."""
    asyncio.run(db.add_user_api_key("111", "기존계정", "existing-key"))
    asyncio.run(db.add_character("111", "기존캐릭", api_key_id=(asyncio.run(db.list_user_api_keys("111")))[0]["id"]))

    monkeypatch.setattr(internal.loa, "get_siblings", _fake_get_siblings)
    monkeypatch.setattr(internal.loa, "get_armory", _fake_get_armory_matching_guild)

    resp = client.post(
        "/api/internal/accounts/add",
        json={"discord_id": "111", "api_key": "dummy-key", "character_name": "발키리"},
        headers=HEADERS,
    )

    body = resp.json()
    assert body["success"] is True

    accounts = asyncio.run(db.list_user_api_keys("111"))
    assert len(accounts) == 2
    labels = {acc["label"] for acc in accounts}
    assert labels == {"기존계정", "발키리"}
    assert "기존캐릭" in asyncio.run(db.get_user_characters("111"))  # 기존 캐릭터는 그대로 유지


def test_add_account_requires_webapp_key(client):
    resp = client.post(
        "/api/internal/accounts/add",
        json={"discord_id": "111", "api_key": "dummy-key", "character_name": "발키리"},
    )
    assert resp.status_code == 401


# ── 계정 목록/삭제 (웹 "내 계정" 관리 — 기존 /api확인, /api삭제 웹 버전) ──────

def test_list_accounts_returns_masked_key(client):
    key_id = asyncio.run(db.add_user_api_key("111", "발키리", "abcdefgh12345678"))

    resp = client.get("/api/internal/accounts/list", params={"discord_id": "111"}, headers=HEADERS)

    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == key_id
    assert body[0]["label"] == "발키리"
    assert body[0]["masked_key"] == "abcdefgh****5678"


def test_list_accounts_empty_when_none_registered(client):
    resp = client.get("/api/internal/accounts/list", params={"discord_id": "111"}, headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() == []


def test_remove_account_deletes_and_unlinks_characters(client):
    key_id = asyncio.run(db.add_user_api_key("111", "발키리", "dummy-key"))
    asyncio.run(db.add_character("111", "발키리캐릭", api_key_id=key_id))

    resp = client.post(
        "/api/internal/accounts/remove",
        json={"discord_id": "111", "key_id": key_id},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    assert asyncio.run(db.list_user_api_keys("111")) == []
    # 계정만 삭제되고 캐릭터 자체는 남는다(연결만 해제)
    assert "발키리캐릭" in asyncio.run(db.get_user_characters("111"))


def test_remove_account_rejects_other_users_account(client):
    """discord_id가 소유자와 다르면 삭제되면 안 된다 — remove_user_api_key의 ownership 체크."""
    key_id = asyncio.run(db.add_user_api_key("111", "발키리", "dummy-key"))

    resp = client.post(
        "/api/internal/accounts/remove",
        json={"discord_id": "222", "key_id": key_id},
        headers=HEADERS,
    )

    assert resp.status_code == 200
    assert resp.json() == {"success": False}
    assert len(asyncio.run(db.list_user_api_keys("111"))) == 1


def test_list_accounts_requires_webapp_key(client):
    resp = client.get("/api/internal/accounts/list", params={"discord_id": "111"})
    assert resp.status_code == 401


def test_remove_account_requires_webapp_key(client):
    resp = client.post("/api/internal/accounts/remove", json={"discord_id": "111", "key_id": 1})
    assert resp.status_code == 401
