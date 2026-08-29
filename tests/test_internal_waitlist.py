"""빈자리 대기 알림(웹) — bot/api/routes/internal.py의 waitlist-status/waitlist
엔드포인트 검증. Discord PartyView._handle_waitlist와 동일한 규칙(참여 중이면
거부, 토글 방식)을 웹에서도 그대로 쓴다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
LEADER_ID = "222"
OTHER_ID = "333"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())

    asyncio.run(
        db.create_party(
            message_id="900", channel_id="700", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("900", LEADER_ID, "워로드캐릭", "워로드", "dps", 8))

    from bot.api.server import app

    return TestClient(app)


def test_waitlist_status_defaults_false(client):
    resp = client.get(
        "/api/internal/parties/900/waitlist-status", params={"discord_id": OTHER_ID}, headers=HEADERS
    )
    assert resp.status_code == 200
    assert resp.json() == {"on_waitlist": False}


def test_toggle_waitlist_adds_then_removes(client):
    resp1 = client.post(
        "/api/internal/parties/900/waitlist", json={"discord_id": OTHER_ID}, headers=HEADERS
    )
    assert resp1.json() == {"success": True, "on_waitlist": True}
    assert asyncio.run(db.get_waitlist("900")) == [OTHER_ID]

    status = client.get(
        "/api/internal/parties/900/waitlist-status", params={"discord_id": OTHER_ID}, headers=HEADERS
    )
    assert status.json() == {"on_waitlist": True}

    resp2 = client.post(
        "/api/internal/parties/900/waitlist", json={"discord_id": OTHER_ID}, headers=HEADERS
    )
    assert resp2.json() == {"success": True, "on_waitlist": False}
    assert asyncio.run(db.get_waitlist("900")) == []


def test_toggle_waitlist_rejects_existing_member(client):
    resp = client.post(
        "/api/internal/parties/900/waitlist", json={"discord_id": LEADER_ID}, headers=HEADERS
    )
    assert resp.json() == {"success": False, "reason": "이미 파티에 참여 중입니다."}
    assert asyncio.run(db.get_waitlist("900")) == []


def test_waitlist_requires_webapp_key(client):
    resp = client.post("/api/internal/parties/900/waitlist", json={"discord_id": OTHER_ID})
    assert resp.status_code == 401
