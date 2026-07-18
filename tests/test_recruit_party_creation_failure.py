"""회귀 테스트: 공대 생성 중 스레드 생성이 discord.HTTPException으로 실패하면,
사용자가 "생성합니다" 메시지만 보고 방치되지 않고 실패 안내를 받아야 한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import discord

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.ui import views

LEADER_ID = "222"


def test_post_party_reports_failure_when_thread_creation_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    interaction = MagicMock()
    interaction.user.id = int(LEADER_ID)
    interaction.guild_id = 1
    interaction.response.edit_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()

    fake_forum = MagicMock()
    fake_forum.create_thread = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(status=403, reason="Forbidden"), "권한 없음")
    )
    interaction.client.get_channel = MagicMock(return_value=fake_forum)

    asyncio.run(
        views._post_party(
            interaction, "아르모체(4막)", "노말", "숙련",
            "05/20 오후 8시 정각", "2026-05-20T20:00:00+09:00", "999",
        )
    )

    interaction.response.edit_message.assert_awaited_once()
    interaction.edit_original_response.assert_awaited_once()
    content = interaction.edit_original_response.call_args.kwargs["content"]
    assert "실패" in content
    assert asyncio.run(db.get_guild_parties("1")) == []
