"""파티 스레드 댓글(디스코드 ↔ 웹) 검증 — db.add_party_comment/get_party_comments,
_post_comment_core, LoABot.on_message 핸들러."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

import bot.database.manager as db
from bot.ui.views import _post_comment_core

LEADER_ID = "111"
COMMENTER_ID = "222"
MESSAGE_ID = "700"


@pytest.fixture()
def party(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(
        db.create_party(
            message_id=MESSAGE_ID, channel_id="600", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    return MESSAGE_ID


# ── db.add_party_comment / get_party_comments ────────────────

def test_add_and_get_comments_in_order(party):
    asyncio.run(db.add_party_comment(party, LEADER_ID, "리더캐릭", "필요하면 불러주십쇼", source="discord", discord_message_id="9001"))
    asyncio.run(db.add_party_comment(party, COMMENTER_ID, "댓글러", "저녁 8시가 낫겠네요", source="web"))

    comments = asyncio.run(db.get_party_comments(party))
    assert [c["content"] for c in comments] == ["필요하면 불러주십쇼", "저녁 8시가 낫겠네요"]
    assert comments[0]["source"] == "discord"
    assert comments[1]["source"] == "web"


def test_get_comments_empty_when_none(party):
    assert asyncio.run(db.get_party_comments(party)) == []


# ── _post_comment_core ───────────────────────────────────────

def _make_bot(relay_result=(True, None)):
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=None)
    bot.fetch_channel = AsyncMock()
    return bot


def test_post_comment_core_saves_and_relays(party, monkeypatch):
    relay_mock = AsyncMock(return_value=(True, None))
    monkeypatch.setattr("bot.services.comment_bridge.relay_comment_to_discord", relay_mock)

    bot = _make_bot()
    result = asyncio.run(
        _post_comment_core(bot, party, COMMENTER_ID, "댓글러", "https://example.com/a.png", "안녕하세요")
    )

    assert result["success"] is True
    assert result["relayed"] is True
    comments = asyncio.run(db.get_party_comments(party))
    assert len(comments) == 1
    assert comments[0]["content"] == "안녕하세요"
    assert comments[0]["source"] == "web"
    relay_mock.assert_awaited_once()


def test_post_comment_core_saves_even_if_relay_fails(party, monkeypatch):
    """릴레이(디스코드 전송)가 실패해도(스레드 잠김 등) 웹 화면용 저장은 남아야 한다."""
    relay_mock = AsyncMock(return_value=(False, "스레드가 잠겨 있습니다"))
    monkeypatch.setattr("bot.services.comment_bridge.relay_comment_to_discord", relay_mock)

    bot = _make_bot()
    result = asyncio.run(
        _post_comment_core(bot, party, COMMENTER_ID, "댓글러", "https://example.com/a.png", "안녕하세요")
    )

    assert result["success"] is True
    assert result["relayed"] is False
    assert result["relay_reason"] == "스레드가 잠겨 있습니다"
    assert len(asyncio.run(db.get_party_comments(party))) == 1


def test_post_comment_core_rejects_disbanded_party(party, monkeypatch):
    asyncio.run(db.disband_party(party))
    relay_mock = AsyncMock()
    monkeypatch.setattr("bot.services.comment_bridge.relay_comment_to_discord", relay_mock)

    bot = _make_bot()
    result = asyncio.run(
        _post_comment_core(bot, party, COMMENTER_ID, "댓글러", "https://example.com/a.png", "안녕하세요")
    )

    assert result["success"] is False
    assert "종료된" in result["reason"]
    assert asyncio.run(db.get_party_comments(party)) == []
    relay_mock.assert_not_called()


def test_post_comment_core_rejects_missing_party(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    bot = _make_bot()
    result = asyncio.run(
        _post_comment_core(bot, "nonexistent", COMMENTER_ID, "댓글러", "https://example.com/a.png", "안녕")
    )
    assert result["success"] is False
    assert "찾을 수 없습니다" in result["reason"]


# ── LoABot.on_message ─────────────────────────────────────────

def _make_message(discord_id: str, channel_id: str, content: str, is_bot=False, webhook_id=None, message_id="9999"):
    message = MagicMock()
    message.author.id = int(discord_id)
    message.author.bot = is_bot
    message.author.display_name = "메시지작성자"
    message.channel.id = int(channel_id)
    message.content = content
    message.webhook_id = webhook_id
    message.id = int(message_id)
    return message


def test_on_message_stores_comment_for_matching_party_channel(party, monkeypatch):
    from bot.bot import LoABot

    monkeypatch.setattr(db, "DB_PATH", db.DB_PATH)  # keep same tmp db from `party` fixture
    bot = LoABot()
    bot.process_commands = AsyncMock()

    message = _make_message(COMMENTER_ID, "600", "8시 어때요")
    asyncio.run(bot.on_message(message))

    comments = asyncio.run(db.get_party_comments(party))
    assert len(comments) == 1
    assert comments[0]["content"] == "8시 어때요"
    assert comments[0]["source"] == "discord"
    bot.process_commands.assert_awaited_once()


def test_on_message_ignores_bot_and_webhook_messages(party, monkeypatch):
    from bot.bot import LoABot

    bot = LoABot()
    bot.process_commands = AsyncMock()

    bot_message = _make_message(COMMENTER_ID, "600", "봇 메시지", is_bot=True)
    asyncio.run(bot.on_message(bot_message))
    webhook_message = _make_message(COMMENTER_ID, "600", "웹훅 릴레이 메시지", webhook_id="123")
    asyncio.run(bot.on_message(webhook_message))

    assert asyncio.run(db.get_party_comments(party)) == []
    assert bot.process_commands.await_count == 2


def test_on_message_ignores_channel_not_matching_any_party(tmp_path, monkeypatch):
    from bot.bot import LoABot

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    bot = LoABot()
    bot.process_commands = AsyncMock()

    message = _make_message(COMMENTER_ID, "999999", "상관없는 채널 메시지")
    asyncio.run(bot.on_message(message))

    bot.process_commands.assert_awaited_once()  # 그냥 아무 일 없이 통과만 확인


def test_on_message_ignores_disbanded_party(party, monkeypatch):
    from bot.bot import LoABot

    asyncio.run(db.disband_party(party))
    bot = LoABot()
    bot.process_commands = AsyncMock()

    message = _make_message(COMMENTER_ID, "600", "이미 끝난 파티에 메시지")
    asyncio.run(bot.on_message(message))

    assert asyncio.run(db.get_party_comments(party)) == []
