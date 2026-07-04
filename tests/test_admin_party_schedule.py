"""관리자 앱에서 일정 변경 시 Discord embed/스레드 제목도 같이 갱신되는지 검증.
(버그: 예전에는 DB만 바뀌고 Discord에는 반영이 안 됐음 — /clear는 되는데 /schedule은 안 됐던 문제)
"""
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


@pytest.fixture()
def party_message_id(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(
        db.create_party(
            message_id="999",
            channel_id="555",
            guild_id="1",
            leader_id="111",
            raid_name="카멘",
            difficulty="노말",
            proficiency="숙련",
            scheduled_time="05/20 20:00",
            scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8,
            min_level=1620,
        )
    )
    return "999"


@pytest.fixture()
def client():
    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot(monkeypatch):
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    fake_channel.edit = AsyncMock()

    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_channel)

    bot_ref.set_bot(fake_bot)
    yield fake_bot, fake_channel, fake_message
    bot_ref.set_bot(None)


def test_schedule_change_updates_db(client, party_message_id, fake_bot):
    resp = client.patch(
        f"/api/parties/{party_message_id}/schedule",
        json={"scheduled_time": "05/21 21:00", "scheduled_datetime": "2026-05-21T21:00:00+09:00"},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 200
    party = asyncio.run(db.get_party(party_message_id))
    assert party["scheduled_time"] == "05/21 21:00"


def test_schedule_change_refreshes_discord_embed(client, party_message_id, fake_bot):
    _, fake_channel, fake_message = fake_bot

    client.patch(
        f"/api/parties/{party_message_id}/schedule",
        json={"scheduled_time": "05/21 21:00", "scheduled_datetime": "2026-05-21T21:00:00+09:00"},
        headers={"X-API-Key": "test-admin-key"},
    )

    fake_channel.fetch_message.assert_awaited_once_with(int(party_message_id))
    fake_message.edit.assert_awaited_once()
    _, kwargs = fake_message.edit.call_args
    assert kwargs["embed"] is not None
    assert kwargs["view"] is not None  # 파티가 아직 활성 상태라 view(버튼)는 유지되어야 함


def test_schedule_change_renames_thread_with_new_time(client, party_message_id, fake_bot):
    _, fake_channel, _ = fake_bot

    client.patch(
        f"/api/parties/{party_message_id}/schedule",
        json={"scheduled_time": "05/21 21:00", "scheduled_datetime": "2026-05-21T21:00:00+09:00"},
        headers={"X-API-Key": "test-admin-key"},
    )

    fake_channel.edit.assert_awaited_once()
    _, kwargs = fake_channel.edit.call_args
    assert "05/21 21:00" in kwargs["name"]


def test_schedule_change_still_works_when_bot_not_ready(client, party_message_id):
    """봇이 아직 안 붙어있어도(bot_ref 미설정) DB 업데이트 자체는 실패하면 안 된다."""
    bot_ref.set_bot(None)
    resp = client.patch(
        f"/api/parties/{party_message_id}/schedule",
        json={"scheduled_time": "05/22 20:00", "scheduled_datetime": "2026-05-22T20:00:00+09:00"},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 200
