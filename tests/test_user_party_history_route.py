"""웹 '공대 이력' 페이지가 쓰는 내부 API 엔드포인트(GET /api/internal/user-party-history) 검증.

관리자 전용 /api/users/{id}/history(ADMIN_API_KEY)와는 별도로, 웹앱 전용 인증
(X-Webapp-Key)으로 같은 데이터를 내려주는 엔드포인트가 필요해서 추가했다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
LEADER_ID = "111"


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
    asyncio.run(db.auto_assign_slot("900", LEADER_ID, "워로드본캐", "워로드", "dps", 8))

    from bot.api.server import app

    return TestClient(app)


def test_user_party_history_returns_entries_for_member(client):
    resp = client.get(
        "/api/internal/user-party-history",
        params={"discord_id": LEADER_ID},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["character_name"] == "워로드본캐"


def test_user_party_history_rejects_missing_webapp_key(client):
    resp = client.get("/api/internal/user-party-history", params={"discord_id": LEADER_ID})
    assert resp.status_code in (401, 403, 422)
