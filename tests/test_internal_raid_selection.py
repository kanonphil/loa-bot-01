"""bot/api/routes/internal.py의 레이드 선택(GET/POST /raid-selection) 엔드포인트 검증."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-Webapp-Key": "test-webapp-key"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())

    from bot.api.server import app

    return TestClient(app)


def test_get_raid_selection_not_customized(client):
    resp = client.get(
        "/api/internal/raid-selection",
        params={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json() == {"customized": False, "selected_raids": []}


def test_set_then_get_raid_selection(client):
    post_resp = client.post(
        "/api/internal/raid-selection",
        json={"discord_id": "111", "character_name": "발키리", "raid_names": ["카멘", "종막"]},
        headers=HEADERS,
    )
    assert post_resp.status_code == 200
    assert post_resp.json() == {"success": True}

    get_resp = client.get(
        "/api/internal/raid-selection",
        params={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    body = get_resp.json()
    assert body["customized"] is True
    assert set(body["selected_raids"]) == {"카멘", "종막"}


def test_deselecting_all_is_still_customized(client):
    client.post(
        "/api/internal/raid-selection",
        json={"discord_id": "111", "character_name": "발키리", "raid_names": []},
        headers=HEADERS,
    )
    resp = client.get(
        "/api/internal/raid-selection",
        params={"discord_id": "111", "character_name": "발키리"},
        headers=HEADERS,
    )
    assert resp.json() == {"customized": True, "selected_raids": []}


def test_raid_selection_requires_webapp_key(client):
    resp = client.get(
        "/api/internal/raid-selection", params={"discord_id": "111", "character_name": "발키리"}
    )
    assert resp.status_code == 401
