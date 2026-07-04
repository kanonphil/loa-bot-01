"""관리자 앱에서 메모 변경 시에도 Discord embed가 갱신되는지 검증 (schedule과 동일했던 버그)."""
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


def test_memo_change_updates_db(client, party_message_id, fake_bot):
    resp = client.patch(
        f"/api/parties/{party_message_id}/memo",
        json={"memo": "지각자 대기 안 함"},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 200
    party = asyncio.run(db.get_party(party_message_id))
    assert party["memo"] == "지각자 대기 안 함"


def test_memo_change_refreshes_discord_embed(client, party_message_id, fake_bot):
    _, fake_channel, fake_message = fake_bot

    client.patch(
        f"/api/parties/{party_message_id}/memo",
        json={"memo": "지각자 대기 안 함"},
        headers={"X-API-Key": "test-admin-key"},
    )

    fake_channel.fetch_message.assert_awaited_once_with(int(party_message_id))
    fake_message.edit.assert_awaited_once()
    _, kwargs = fake_message.edit.call_args
    assert kwargs["embed"] is not None
    assert kwargs["view"] is not None


def test_memo_change_does_not_rename_channel(client, party_message_id, fake_bot):
    """메모는 스레드 제목에 안 들어가니, 채널 이름은 안 건드려야 한다."""
    _, fake_channel, _ = fake_bot

    client.patch(
        f"/api/parties/{party_message_id}/memo",
        json={"memo": "지각자 대기 안 함"},
        headers={"X-API-Key": "test-admin-key"},
    )

    fake_channel.edit.assert_not_awaited()


def test_memo_change_still_works_when_bot_not_ready(client, party_message_id):
    bot_ref.set_bot(None)
    resp = client.patch(
        f"/api/parties/{party_message_id}/memo",
        json={"memo": "테스트"},
        headers={"X-API-Key": "test-admin-key"},
    )
    assert resp.status_code == 200
