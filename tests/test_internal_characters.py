"""bot/api/routes/internal.py의 원정대 관리(캐릭터 추가/삭제/동기화) 엔드포인트 검증.
Lost Ark API 호출(bot.api.lostark)은 monkeypatch로 대체 — 실제 외부망 호출 없음."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db
from bot.api.routes import internal

HEADERS = {"X-Webapp-Key": "test-webapp-key"}

SIBLINGS = [
    {"CharacterName": "발키리", "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00", "ServerName": "루페온"},
    {"CharacterName": "워로드부캐", "CharacterClassName": "워로드", "ItemMaxLevel": "1,700.00", "ServerName": "루페온"},
]


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.set_user_api_key("111", "dummy-loa-key"))

    from bot.api.server import app

    return TestClient(app)


async def _fake_get_siblings(api_key, name):
    return SIBLINGS


def test_add_character_requires_api_key(client, monkeypatch):
    resp = client.post(
        "/api/internal/characters/add",
        json={"discord_id": "999", "character_name": "발키리"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "/api등록" in body["reason"]


def test_add_character_success(client, monkeypatch):
    monkeypatch.setattr(internal.loa, "get_siblings", _fake_get_siblings)

    resp = client.post(
        "/api/internal/characters/add",
        json={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["character_class"] == "홀리나이트"
    assert body["item_level"] == 1720.0

    chars = asyncio.run(db.get_user_characters("111"))
    assert chars == ["발키리"]


def test_add_character_rejects_duplicate(client, monkeypatch):
    monkeypatch.setattr(internal.loa, "get_siblings", _fake_get_siblings)
    asyncio.run(db.add_character("111", "발키리"))

    resp = client.post(
        "/api/internal/characters/add",
        json={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "이미 등록된" in body["reason"]


def test_add_character_rejects_character_not_found(client, monkeypatch):
    async def fake_not_found(api_key, name):
        return None

    monkeypatch.setattr(internal.loa, "get_siblings", fake_not_found)

    resp = client.post(
        "/api/internal/characters/add",
        json={"discord_id": "111", "character_name": "없는캐릭터"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "찾을 수 없습니다" in body["reason"]


def test_add_character_rejects_other_expedition(client, monkeypatch):
    """이미 등록된 캐릭터가 있는데, 새로 추가하려는 캐릭터의 원정대(siblings)에
    그 등록된 캐릭터가 없으면 — 다른 사람 원정대를 등록하려는 시도로 보고 거부."""
    asyncio.run(db.add_character("111", "이미등록된캐릭"))

    async def other_expedition_siblings(api_key, name):
        return [{"CharacterName": "발키리", "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00"}]

    monkeypatch.setattr(internal.loa, "get_siblings", other_expedition_siblings)

    resp = client.post(
        "/api/internal/characters/add",
        json={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "본인 원정대" in body["reason"]


def test_remove_character_success(client):
    asyncio.run(db.add_character("111", "발키리"))

    resp = client.post(
        "/api/internal/characters/remove",
        json={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    assert asyncio.run(db.get_user_characters("111")) == []


def test_remove_character_not_registered(client):
    resp = client.post(
        "/api/internal/characters/remove",
        json={"discord_id": "111", "character_name": "없는캐릭터"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "등록된 캐릭터가 아닙니다" in body["reason"]


def test_sync_characters_updates_cached_levels(client, monkeypatch):
    asyncio.run(db.add_character("111", "발키리"))
    asyncio.run(db.add_character("111", "워로드부캐"))
    monkeypatch.setattr(internal.loa, "get_siblings", _fake_get_siblings)

    resp = client.post(
        "/api/internal/characters/sync",
        json={"discord_id": "111"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"success": True, "updated": 2, "total": 2}

    cached = asyncio.run(db.get_cached_characters("111", max_age_hours=99999))
    levels = {c["character_name"]: c["item_level"] for c in cached}
    assert levels["발키리"] == 1720.0
    assert levels["워로드부캐"] == 1700.0


def test_sync_characters_requires_api_key(client):
    resp = client.post(
        "/api/internal/characters/sync",
        json={"discord_id": "999"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "/api등록" in body["reason"]


def test_sync_characters_no_characters_registered(client):
    resp = client.post(
        "/api/internal/characters/sync",
        json={"discord_id": "111"},
        headers=HEADERS,
    )
    assert resp.json() == {"success": True, "updated": 0, "total": 0}
