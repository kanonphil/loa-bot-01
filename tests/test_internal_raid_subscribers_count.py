"""/api/internal/raid-subscribers-count — 공대 개설 화면의 "구독자 N명에게 DM" 미리보기.
실제 발송(views._notify_new_party_subscribers)과 같은 규칙으로 세는지 확인한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
RAID = "아르모체(4막)"
URL = "/api/internal/raid-subscribers-count"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())

    async def setup():
        await db.subscribe_raid("201", RAID, "노말")
        await db.subscribe_raid("202", RAID, "전체")
        await db.subscribe_raid("203", RAID, "노말")   # 같은 사람이 노말+전체 둘 다 → 1명
        await db.subscribe_raid("203", RAID, "전체")
        await db.subscribe_raid("204", RAID, "하드")   # 다른 난이도
        await db.subscribe_raid("205", "종막", "노말")  # 다른 레이드
        await db.subscribe_raid("206", RAID, "노말")   # 같은 주 같은 레이드 공대에 이미 있음
        await db.create_party(
            message_id="900", channel_id="700", guild_id="1", leader_id="206",
            raid_name=RAID, difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2099-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
        await db.auto_assign_slot("900", "206", "캐릭", "워로드", "dps", 8)

    asyncio.run(setup())
    from bot.api.server import app

    return TestClient(app)


def _count(client, **params):
    resp = client.get(URL, params={"raid_name": RAID, "difficulty": "노말", **params}, headers=HEADERS)
    assert resp.status_code == 200
    return resp.json()["count"]


def test_counts_difficulty_and_wildcard_subscribers_once(client):
    # 다른 주(이번 주) 기준이면 206도 받는다: 201, 202, 203, 206
    assert _count(client, scheduled_datetime="2026-01-07T20:00") == 4


def test_excludes_creator(client):
    assert _count(client, discord_id="201", scheduled_datetime="2026-01-07T20:00") == 3


def test_excludes_users_already_in_same_raid_that_week(client):
    assert _count(client, scheduled_datetime="2099-05-21T20:00") == 3  # 206 제외


def test_zero_for_unknown_raid(client):
    resp = client.get(URL, params={"raid_name": "없는레이드", "difficulty": "노말"}, headers=HEADERS)
    assert resp.json() == {"count": 0}


def test_invalid_datetime_falls_back_to_this_week(client):
    assert _count(client, scheduled_datetime="not-a-date") >= 3


def test_requires_webapp_key(client):
    resp = client.get(URL, params={"raid_name": RAID, "difficulty": "노말"})
    assert resp.status_code in (401, 403)


def test_preview_matches_actual_dm_recipients(client, monkeypatch):
    """실제 발송도 같은 사람에게 한 번씩만 간다(중복 구독자에게 두 번 가던 것도 같이 정리)."""
    from bot.ui import views

    sent = []

    async def fake_get_user(_bot, uid):
        u = MagicMock()
        u.send = AsyncMock(side_effect=lambda **kw: sent.append(uid))
        return u

    expected = _count(client, discord_id="201", scheduled_datetime="2099-05-21T20:00")
    monkeypatch.setattr(views, "_get_user", fake_get_user)
    asyncio.run(views._notify_new_party_subscribers(
        MagicMock(), "1", "201", RAID, "노말", "숙련", "05/21 20:00",
        "2099-05-21T20:00:00+09:00", "701", "901",
    ))
    assert sorted(sent) == ["202", "203"]
    assert len(sent) == expected
