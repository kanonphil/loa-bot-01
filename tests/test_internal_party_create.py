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


def test_create_party_duplicate_submit_reuses_same_thread(client, fake_bot):
    """폼 재제출/더블클릭으로 같은 조건(리더+레이드+난이도+일정)의 요청이 짧은 시간
    안에 다시 들어와도 스레드를 또 만들지 않고 방금 만든 파티를 그대로 반환해야 한다
    — 정상 스레드 + 빈 스레드가 함께 생기던 버그의 재발 방지."""
    asyncio.run(db.set_forum_channel("1", "999"))
    _, fake_forum, fake_thread, fake_starter_msg = fake_bot

    first = client.post("/api/internal/parties/create", json=_payload(), headers=HEADERS)
    second = client.post("/api/internal/parties/create", json=_payload(), headers=HEADERS)

    assert first.json()["success"] is True
    assert second.json()["success"] is True
    assert first.json()["message_id"] == second.json()["message_id"]
    assert fake_forum.create_thread.call_count == 1  # 스레드는 한 번만 생성됨


def test_create_party_different_difficulty_is_not_treated_as_duplicate(client, fake_bot):
    """조건이 다르면(예: 난이도가 다름) 중복으로 취급하지 않고 각각 새 스레드를 만든다."""
    asyncio.run(db.set_forum_channel("1", "999"))
    _, fake_forum, fake_thread, _ = fake_bot

    # 서로 다른 파티라 message_id도 달라야 하므로, 호출마다 다른 starter_msg를 반환하게 한다
    # (fixture 기본값은 두 호출 모두 같은 id=888을 내려줘서 PK 충돌이 난다).
    def _new_starter_msg(msg_id):
        msg = AsyncMock()
        msg.id = msg_id
        msg.edit = AsyncMock()
        return msg

    fake_forum.create_thread = AsyncMock(
        side_effect=[(fake_thread, _new_starter_msg(801)), (fake_thread, _new_starter_msg(802))]
    )

    first = client.post("/api/internal/parties/create", json=_payload(difficulty="노말"), headers=HEADERS)
    second = client.post("/api/internal/parties/create", json=_payload(difficulty="하드"), headers=HEADERS)

    assert first.json()["success"] is True
    assert second.json()["success"] is True
    assert first.json()["message_id"] != second.json()["message_id"]
    assert fake_forum.create_thread.call_count == 2


def test_find_recent_duplicate_party_matches_same_condition(client):
    asyncio.run(db.set_forum_channel("1", "999"))
    asyncio.run(
        db.create_party(
            message_id="1", channel_id="c1", guild_id="1", leader_id="111",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="5/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1600,
        )
    )
    dup = asyncio.run(
        db.find_recent_duplicate_party("111", "아르모체(4막)", "노말", "2026-05-20T20:00:00+09:00")
    )
    assert dup is not None
    assert dup["message_id"] == "1"


def test_find_recent_duplicate_party_ignores_different_leader_or_condition(client):
    asyncio.run(db.set_forum_channel("1", "999"))
    asyncio.run(
        db.create_party(
            message_id="1", channel_id="c1", guild_id="1", leader_id="111",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="5/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1600,
        )
    )
    # 다른 리더
    assert asyncio.run(
        db.find_recent_duplicate_party("222", "아르모체(4막)", "노말", "2026-05-20T20:00:00+09:00")
    ) is None
    # 다른 난이도
    assert asyncio.run(
        db.find_recent_duplicate_party("111", "아르모체(4막)", "하드", "2026-05-20T20:00:00+09:00")
    ) is None
    # 다른 일정
    assert asyncio.run(
        db.find_recent_duplicate_party("111", "아르모체(4막)", "노말", "2026-05-21T20:00:00+09:00")
    ) is None


def test_create_party_proficiency_options_endpoint(client, fake_bot):
    resp = client.get("/api/internal/parties/proficiency-options", headers=HEADERS)
    assert resp.status_code == 200
    values = [o["value"] for o in resp.json()]
    assert "숙련" in values
    assert "트라이" in values
