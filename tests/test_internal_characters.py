"""bot/api/routes/internal.py의 원정대 관리(캐릭터 추가/삭제/동기화) 엔드포인트 검증.
Lost Ark API 호출(bot.api.lostark)은 monkeypatch로 대체 — 실제 외부망 호출 없음."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.api import bot_ref
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
    # add_user_api_key로 등록해야 user_api_keys에도 row가 생겨 다중 계정 기반
    # 캐릭터 등록/동기화 로직(register_character_auto_detect 등)이 정상 동작한다.
    asyncio.run(db.add_user_api_key("111", "발키리", "dummy-loa-key"))

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
    """등록된 계정(API 키)으로 조회했을 때 그 원정대(siblings)에 해당 캐릭터가 없으면
    — 남의 캐릭터를 등록하려는 시도로 보고 거부. 등록된 모든 계정을 다 시도해도
    못 찾으면 실패해야 한다."""
    asyncio.run(db.add_character("111", "이미등록된캐릭"))

    async def other_expedition_siblings(api_key, name):
        # 등록된 계정(dummy-loa-key)의 원정대에는 "다른사람캐릭"이 없다.
        return [{"CharacterName": "발키리", "CharacterClassName": "홀리나이트", "ItemMaxLevel": "1,720.00"}]

    monkeypatch.setattr(internal.loa, "get_siblings", other_expedition_siblings)

    resp = client.post(
        "/api/internal/characters/add",
        json={"discord_id": "111", "character_name": "다른사람캐릭"},
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "찾을 수 없습니다" in body["reason"]


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


def test_remove_character_leaves_active_party(client):
    """회귀 테스트: 참여 중이던 캐릭터를 삭제하면 그 공대에서도 자동으로 나가야 한다
    — 이전에는 캐릭터만 지워지고 party_slots에는 유령 파티원으로 계속 남아 있었다."""
    asyncio.run(raids_module.reload())
    asyncio.run(db.add_character("111", "발키리"))
    asyncio.run(
        db.create_party(
            message_id="700", channel_id="600", guild_id="1", leader_id="222",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("700", "111", "발키리", "홀리나이트", "support", 8))

    fake_msg = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_msg)
    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_channel)
    bot_ref.set_bot(fake_bot)
    try:
        resp = client.post(
            "/api/internal/characters/remove",
            json={"discord_id": "111", "character_name": "발키리"},
            headers=HEADERS,
        )
    finally:
        bot_ref.set_bot(None)

    assert resp.json() == {"success": True}
    slots = asyncio.run(db.get_party_slots("700"))
    assert not any(s["discord_id"] == "111" for s in slots)


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
