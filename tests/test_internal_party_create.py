"""bot/api/routes/internal.py의 공대 개설(POST /parties/create) 엔드포인트 검증."""
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

HEADERS = {"X-Webapp-Key": "test-webapp-key"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key("111", "dummy-key"))

    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot(monkeypatch):
    fake_thread = MagicMock()
    fake_thread.id = 777
    fake_starter_msg = AsyncMock()
    fake_starter_msg.id = 888
    fake_starter_msg.edit = AsyncMock()

    fake_forum = MagicMock()
    fake_forum.create_thread = AsyncMock(return_value=(fake_thread, fake_starter_msg))

    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_forum)
    fake_bot.fetch_user = AsyncMock(side_effect=Exception("no subscribers expected"))

    bot_ref.set_bot(fake_bot)
    yield fake_bot, fake_forum, fake_thread, fake_starter_msg
    bot_ref.set_bot(None)


def _payload(**overrides):
    payload = {
        "discord_id": "111",
        "guild_id": "1",
        "raid_name": "아르모체(4막)",
        "difficulty": "노말",
        "proficiency": "숙련",
        "scheduled_datetime": "2026-05-20T20:00",
        "memo": "음성 필수",
    }
    payload.update(overrides)
    return payload


def test_create_party_requires_forum_channel_set(client, fake_bot):
    resp = client.post("/api/internal/parties/create", json=_payload(), headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "포럼 채널" in body["reason"]


def test_create_party_requires_api_key(client, fake_bot):
    asyncio.run(db.set_forum_channel("1", "999"))
    resp = client.post(
        "/api/internal/parties/create",
        json=_payload(discord_id="999999"),
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "/api등록" in body["reason"]


def test_create_party_rejects_unknown_raid(client, fake_bot):
    asyncio.run(db.set_forum_channel("1", "999"))
    resp = client.post(
        "/api/internal/parties/create",
        json=_payload(raid_name="없는레이드"),
        headers=HEADERS,
    )
    body = resp.json()
    assert body["success"] is False
    assert "존재하지 않는 레이드" in body["reason"]


def test_create_party_success_creates_thread_and_db_row(client, fake_bot):
    asyncio.run(db.set_forum_channel("1", "999"))
    _, fake_forum, fake_thread, fake_starter_msg = fake_bot

    resp = client.post("/api/internal/parties/create", json=_payload(), headers=HEADERS)
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["message_id"] == "888"

    assert fake_forum.create_thread.called
    party = asyncio.run(db.get_party("888"))
    assert party is not None
    assert party["leader_id"] == "111"
    assert party["raid_name"] == "아르모체(4막)"
    assert party["memo"] == "음성 필수"
    assert party["channel_id"] == "777"


def test_create_party_proficiency_options_endpoint(client, fake_bot):
    resp = client.get("/api/internal/parties/proficiency-options", headers=HEADERS)
    assert resp.status_code == 200
    values = [o["value"] for o in resp.json()]
    assert "숙련" in values
    assert "트라이" in values
