"""bot/api/routes/internal.py의 관리자 통계/구독·알림/클리어 편집/봇 상태 엔드포인트
(관리자 앱에만 있던 화면을 웹에 옮기며 추가) 검증."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import bot.database.manager as db
from bot.api import bot_ref

HEADERS = {"X-Webapp-Key": "test-webapp-key"}
ADMIN_ID = "111"
USER_A = "222"
USER_B = "333"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    import config
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN_ID})

    async def seed():
        await db.set_user_api_key(USER_A, "k1")
        await db.add_user_api_key(USER_A, "메인캐릭", "k1")
        await db.add_character(USER_A, "메인캐릭")
        await db.set_user_api_key(USER_B, "k2")
        await db.add_character(USER_B, "부캐")
        await db.toggle_completion(USER_A, "메인캐릭", "아르모체(4막)", "노말")
        await db.toggle_completion(USER_A, "메인캐릭", "아르모체(4막)", "하드")
        await db.toggle_completion(USER_B, "부캐", "아르모체(4막)", "노말")
        await db.subscribe_raid(USER_A, "아르모체(4막)", "하드")
        await db.log_notification(USER_A, "아르모체(4막)", "하드", "900")
        await db.create_party(
            message_id="900", channel_id="700", guild_id="1", leader_id=USER_A,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
        await db.auto_assign_slot("900", USER_A, "메인캐릭", "워로드", "dps", 8)

    asyncio.run(seed())
    from bot.api.server import app

    return TestClient(app)


def _get(client, path, **params):
    return client.get(f"/api/internal/admin/{path}", params={"discord_id": ADMIN_ID, **params}, headers=HEADERS)


def test_stats_weekly_counts_by_raid_and_difficulty(client):
    body = _get(client, "stats/weekly").json()
    # toggle_completion은 같은 레이드를 한 주에 한 난이도만 인정한다(하드를 찍으면 노말이 빠짐)
    counts = {(r["raid_name"], r["difficulty"]): r["count"] for r in body["data"]}
    assert counts[("아르모체(4막)", "노말")] == 1
    assert counts[("아르모체(4막)", "하드")] == 1


def test_stats_characters_include_representative(client):
    body = _get(client, "stats/characters").json()
    row = next(r for r in body["data"] if r["discord_id"] == USER_A)
    assert row["clears"] == 1
    assert row["representative"] == "메인캐릭"


def test_stats_weeks_always_includes_current(client):
    body = _get(client, "stats/weeks").json()
    assert body["current"] == db.get_week_key()
    assert body["weeks"][0] == body["current"]


def test_stats_activity_shape(client):
    body = _get(client, "stats/activity", guild_id="1").json()
    assert body["popular_raids"][0]["raid_name"] == "아르모체(4막)"
    assert body["active_users"]["user_count"] == 1
    assert isinstance(body["weekly_parties"], list)


def test_stats_reject_non_admin(client):
    resp = client.get("/api/internal/admin/stats/weekly", params={"discord_id": USER_A}, headers=HEADERS)
    assert resp.status_code == 403


def test_subscriptions_carry_representative(client):
    body = _get(client, "subscriptions").json()
    assert body[0]["discord_id"] == USER_A
    assert body[0]["representative"] == "메인캐릭"


def test_notification_logs_listed(client):
    body = _get(client, "notification-logs").json()
    assert body[0]["message_id"] == "900"


def test_completions_get_and_set_for_past_week(client):
    week = "2026-01-07"
    body = _get(client, "completions", target_discord_id=USER_B, character_name="부캐", week_key=week).json()
    assert body["completions"] == []
    resp = client.post(
        "/api/internal/admin/completions/set",
        json={"discord_id": ADMIN_ID, "target_discord_id": USER_B, "character_name": "부캐",
              "raid_name": "아르모체(4막)", "difficulty": "하드", "week_key": week, "done": True},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    body = _get(client, "completions", target_discord_id=USER_B, character_name="부캐", week_key=week).json()
    assert body["completions"] == ["아르모체(4막)_하드"]
    resp = client.post(
        "/api/internal/admin/completions/set",
        json={"discord_id": ADMIN_ID, "target_discord_id": USER_B, "character_name": "부캐",
              "raid_name": "아르모체(4막)", "difficulty": "하드", "week_key": week, "done": False},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    assert asyncio.run(db.get_completions(USER_B, "부캐", week)) == set()


def test_completions_set_rejects_non_admin(client):
    resp = client.post(
        "/api/internal/admin/completions/set",
        json={"discord_id": USER_A, "target_discord_id": USER_B, "character_name": "부캐",
              "raid_name": "아르모체(4막)", "difficulty": "하드", "week_key": "2026-01-07", "done": True},
        headers=HEADERS,
    )
    assert resp.json()["success"] is False


def test_notify_all_dms_every_registered_user(client):
    fake_user = AsyncMock()
    bot = MagicMock()
    bot.fetch_user = AsyncMock(return_value=fake_user)
    bot_ref.set_bot(bot)
    try:
        resp = client.post("/api/internal/admin/notify-all", json={"discord_id": ADMIN_ID, "content": "공지"}, headers=HEADERS)
    finally:
        bot_ref.set_bot(None)
    body = resp.json()
    assert body["success"] is True
    assert body["sent"] == 2 and body["total"] == 2
    assert fake_user.send.await_count == 2


def test_notify_all_rejects_non_admin_without_sending(client):
    bot = MagicMock(); bot.fetch_user = AsyncMock()
    bot_ref.set_bot(bot)
    try:
        resp = client.post("/api/internal/admin/notify-all", json={"discord_id": USER_A, "content": "공지"}, headers=HEADERS)
    finally:
        bot_ref.set_bot(None)
    assert resp.json()["success"] is False
    bot.fetch_user.assert_not_called()


def test_status_reports_counts_and_no_restart_route(client):
    body = _get(client, "status").json()
    assert body["user_count"] == 2
    assert body["active_party_count"] == 1
    assert body["subscription_count"] == 1
    assert body["is_online"] is False  # 테스트엔 봇 없음
    assert client.post("/api/internal/admin/status/restart", json={"discord_id": ADMIN_ID}, headers=HEADERS).status_code == 404
