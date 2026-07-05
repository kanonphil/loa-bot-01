"""일정 캘린더 내부 API(/api/internal/parties/calendar) 검증.
클리어된 파티(status=disbanded)는 parties 테이블에 남아있든, 주간 리셋으로
purge돼 party_history로 넘어갔든 캘린더에 포함되어야 한다. 취소된(cancelled)
파티는 party_history에는 남지만 실제 진행되지 않은 일정이라 캘린더에서 뺀다."""
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
        await db.purge_party("cancelled-1", archived_status="cancelled")  # 취소 처리 — 실제 취소 흐름과 동일하게 명시

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


def test_calendar_still_shows_cleared_party_after_weekly_reset_purges_it(client):
    """주간 리셋(bot.py의 party_notification_task)은 지난 주에 클리어된 파티를
    한 주 지나면 스레드와 함께 parties 테이블에서도 purge한다. 이 시나리오를
    재현해도(직접 purge_party 호출) 캘린더에서는 계속 보여야 한다 — 그래야
    "6월 기록이 아무것도 없다"던 문제가 재발하지 않는다."""
    asyncio.run(db.purge_party("cleared-1"))  # 실제 주간 리셋과 동일 — status override 없이 그대로 purge

    resp = client.get(
        "/api/internal/parties/calendar",
        params={"guild_id": GUILD_ID, "start": "2026-05-01T00:00:00", "end": "2026-06-01T00:00:00"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    parties = {p["message_id"]: p for p in resp.json()}
    assert "cleared-1" in parties
    assert parties["cleared-1"]["status"] == "disbanded"
    assert parties["cleared-1"]["slot_count"] == 0  # 이 시나리오에서는 파티원을 안 넣었으므로 0명이 맞음
