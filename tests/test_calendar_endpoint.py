"""일정 캘린더 내부 API(/api/internal/parties/calendar) 검증.
클리어된 파티(status=disbanded)는 행이 남아있으니 캘린더에 포함되고,
취소된 파티(purge)는 완전히 삭제되니 자연히 빠져야 한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
GUILD_ID = "1"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())

    async def _seed():
        await db.create_party(
            message_id="recruiting-1", channel_id="555", guild_id=GUILD_ID, leader_id="111",
            raid_name="카멘", difficulty="노말", proficiency="숙련",
            scheduled_time="05/10 20:00", scheduled_datetime="2026-05-10T20:00:00+09:00",
            total_slots=8, min_level=1620,
        )
        await db.create_party(
            message_id="cleared-1", channel_id="555", guild_id=GUILD_ID, leader_id="111",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/12 21:00", scheduled_datetime="2026-05-12T21:00:00+09:00",
            total_slots=8, min_level=1700,
        )
        await db.disband_party("cleared-1")  # 클리어 처리 — 행은 남고 status만 disbanded

        await db.create_party(
            message_id="cancelled-1", channel_id="555", guild_id=GUILD_ID, leader_id="111",
            raid_name="쿠크세이튼", difficulty="노말", proficiency="숙련",
            scheduled_time="05/15 20:00", scheduled_datetime="2026-05-15T20:00:00+09:00",
            total_slots=4, min_level=1540,
        )
        await db.purge_party("cancelled-1")  # 취소 처리 — 완전 삭제

        await db.create_party(
            message_id="other-month-1", channel_id="555", guild_id=GUILD_ID, leader_id="111",
            raid_name="카멘", difficulty="하드", proficiency="숙련",
            scheduled_time="06/03 20:00", scheduled_datetime="2026-06-03T20:00:00+09:00",
            total_slots=8, min_level=1660,
        )

    asyncio.run(_seed())

    from bot.api.server import app

    return TestClient(app)


def test_calendar_includes_cleared_party(client):
    resp = client.get(
        "/api/internal/parties/calendar",
        params={"guild_id": GUILD_ID, "start": "2026-05-01T00:00:00", "end": "2026-06-01T00:00:00"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    ids = {p["message_id"] for p in resp.json()}
    assert "recruiting-1" in ids
    assert "cleared-1" in ids
    cleared = next(p for p in resp.json() if p["message_id"] == "cleared-1")
    assert cleared["status"] == "disbanded"


def test_calendar_excludes_cancelled_party(client):
    resp = client.get(
        "/api/internal/parties/calendar",
        params={"guild_id": GUILD_ID, "start": "2026-05-01T00:00:00", "end": "2026-06-01T00:00:00"},
        headers=HEADERS,
    )
    ids = {p["message_id"] for p in resp.json()}
    assert "cancelled-1" not in ids


def test_calendar_excludes_other_month(client):
    resp = client.get(
        "/api/internal/parties/calendar",
        params={"guild_id": GUILD_ID, "start": "2026-05-01T00:00:00", "end": "2026-06-01T00:00:00"},
        headers=HEADERS,
    )
    ids = {p["message_id"] for p in resp.json()}
    assert "other-month-1" not in ids


def test_calendar_requires_webapp_key(client):
    resp = client.get(
        "/api/internal/parties/calendar",
        params={"guild_id": GUILD_ID, "start": "2026-05-01T00:00:00", "end": "2026-06-01T00:00:00"},
    )
    assert resp.status_code == 401
