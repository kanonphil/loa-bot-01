"""webapp/guild_info.py — 앱 시작 시 길드 아이콘을 봇 서버에서 한 번 가져와 캐시하는 로직 검증.
봇 서버가 응답하지 않아도(오프라인/재시작 중) 예외 없이 기본 로고로 대체되어야 한다."""
import asyncio

import pytest

from webapp import guild_info
from webapp.clients import bot_client


@pytest.fixture(autouse=True)
def _reset_cache():
    guild_info._icon_url = None
    yield
    guild_info._icon_url = None


def test_refresh_success_sets_icon_url(monkeypatch):
    async def _fake_get_guild_info(guild_id):
        return {"name": "동물롱장", "icon_url": "https://cdn.discordapp.com/icons/1/abc.png"}

    monkeypatch.setattr(bot_client, "get_guild_info", _fake_get_guild_info)

    asyncio.run(guild_info.refresh())

    assert guild_info.get_icon_url() == "https://cdn.discordapp.com/icons/1/abc.png"


def test_refresh_failure_falls_back_gracefully(monkeypatch):
    async def _fake_get_guild_info_raises(guild_id):
        raise RuntimeError("bot server unreachable")

    monkeypatch.setattr(bot_client, "get_guild_info", _fake_get_guild_info_raises)

    asyncio.run(guild_info.refresh())  # 예외를 던지면 안 됨

    assert guild_info.get_icon_url() is None


def test_get_name_always_returns_configured_guild_name():
    assert guild_info.get_name() == "동물롱장"
