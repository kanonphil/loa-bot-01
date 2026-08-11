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
    assert body["has_more"] is False
    assert len(body["entries"]) == 1
    assert body["entries"][0]["character_name"] == "워로드본캐"


def test_user_party_history_pagination_reports_has_more(client):
    # 이미 1건 있는 상태에서 25건을 더 만들어 총 26건 — limit=20 기본값 기준으로
    # 21번째 이후는 has_more=True로 신호가 가야 한다(예전엔 조용히 잘렸다).
    async def seed():
        for i in range(25):
            mid = f"extra-{i}"
            await db.create_party(
                message_id=mid, channel_id="700", guild_id="1", leader_id=LEADER_ID,
                raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
                scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
                total_slots=8, min_level=1700,
            )
            await db.auto_assign_slot(mid, LEADER_ID, "워로드본캐", "워로드", "dps", 8)

    asyncio.run(seed())

    resp = client.get(
        "/api/internal/user-party-history",
        params={"discord_id": LEADER_ID},
        headers=HEADERS,
    )
    body = resp.json()
    assert len(body["entries"]) == 20
    assert body["has_more"] is True

    resp2 = client.get(
        "/api/internal/user-party-history",
        params={"discord_id": LEADER_ID, "limit": 20, "offset": 20},
        headers=HEADERS,
    )
    body2 = resp2.json()
    assert len(body2["entries"]) == 6
    assert body2["has_more"] is False


def test_user_party_history_rejects_missing_webapp_key(client):
    resp = client.get("/api/internal/user-party-history", params={"discord_id": LEADER_ID})
    assert resp.status_code in (401, 403, 422)
