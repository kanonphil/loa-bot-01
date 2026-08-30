"""댓글 웹훅 브릿지(bot/services/comment_bridge.py) 단위 테스트 —
메시지 전송 시 ID 캡처, 릴레이된 메시지 삭제."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord

from bot.services import comment_bridge

PARTY = {"channel_id": "600"}


def _make_bot_with_webhook(webhook):
    parent = MagicMock()
    parent.webhooks = AsyncMock(return_value=[])
    parent.create_webhook = AsyncMock(return_value=webhook)

    thread = MagicMock()
    thread.parent = parent

    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=thread)
    return bot


def setup_function():
    comment_bridge._webhook_cache.clear()


def test_relay_comment_to_discord_captures_sent_message_id():
    sent_message = MagicMock()
    sent_message.id = 123456789
    webhook = MagicMock()
    webhook.send = AsyncMock(return_value=sent_message)

    bot = _make_bot_with_webhook(webhook)

    success, reason, discord_message_id = asyncio.run(
        comment_bridge.relay_comment_to_discord(bot, PARTY, "댓글러", "https://example.com/a.png", "안녕하세요")
    )

    assert success is True
    assert reason is None
    assert discord_message_id == "123456789"
    _, kwargs = webhook.send.call_args
    assert kwargs["wait"] is True


def test_relay_comment_to_discord_returns_none_id_on_failure():
    webhook = MagicMock()
    webhook.send = AsyncMock(side_effect=discord.HTTPException(MagicMock(), "실패"))

    bot = _make_bot_with_webhook(webhook)

    success, reason, discord_message_id = asyncio.run(
        comment_bridge.relay_comment_to_discord(bot, PARTY, "댓글러", "https://example.com/a.png", "안녕하세요")
    )

    assert success is False
    assert discord_message_id is None
    assert reason is not None


def test_delete_relayed_message_calls_webhook_delete_with_thread():
    webhook = MagicMock()
    webhook.delete_message = AsyncMock()

    bot = _make_bot_with_webhook(webhook)

    success, reason = asyncio.run(comment_bridge.delete_relayed_message(bot, PARTY, "123456789"))

    assert success is True
    assert reason is None
    args, kwargs = webhook.delete_message.call_args
    assert args[0] == 123456789
    assert isinstance(kwargs["thread"], discord.Object)
    assert kwargs["thread"].id == 600


def test_delete_relayed_message_swallows_not_found():
    """이미 지워진 메시지를 다시 지우려 해도 예외를 던지지 않고 실패만 알린다."""
    webhook = MagicMock()
    webhook.delete_message = AsyncMock(side_effect=discord.NotFound(MagicMock(), "메시지 없음"))

    bot = _make_bot_with_webhook(webhook)

    success, reason = asyncio.run(comment_bridge.delete_relayed_message(bot, PARTY, "123456789"))

    assert success is False
    assert reason is not None
