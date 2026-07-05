"""bot/api/routes/internal.py의 GET /guild-info 엔드포인트 검증.
웹앱 사이드바 로고/길드명 표시에 쓰인다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from bot.api import bot_ref

HEADERS = {"X-Webapp-Key": "test-webapp-key"}


@pytest.fixture()
def client():
    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot_with_guild():
    fake_icon = MagicMock()
    fake_icon.url = "https://cdn.discordapp.com/icons/123/abc.png"

    fake_guild = MagicMock()
    fake_guild.name = "동물롱장"
    fake_guild.icon = fake_icon

    fake_bot = MagicMock()
    fake_bot.get_guild = MagicMock(return_value=fake_guild)

    bot_ref.set_bot(fake_bot)
    yield fake_bot
    bot_ref.set_bot(None)


def test_guild_info_returns_name_and_icon(client, fake_bot_with_guild):
    resp = client.get(
        "/api/internal/guild-info", params={"guild_id": "123"}, headers=HEADERS
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "name": "동물롱장",
        "icon_url": "https://cdn.discordapp.com/icons/123/abc.png",
    }


def test_guild_info_no_icon_returns_none(client):
    fake_guild = MagicMock()
    fake_guild.name = "동물롱장"
    fake_guild.icon = None
    fake_bot = MagicMock()
    fake_bot.get_guild = MagicMock(return_value=fake_guild)
    bot_ref.set_bot(fake_bot)
    try:
        resp = client.get(
            "/api/internal/guild-info", params={"guild_id": "123"}, headers=HEADERS
        )
    finally:
        bot_ref.set_bot(None)

    assert resp.json() == {"name": "동물롱장", "icon_url": None}


def test_guild_info_bot_not_ready_returns_none(client):
    bot_ref.set_bot(None)
    resp = client.get(
        "/api/internal/guild-info", params={"guild_id": "123"}, headers=HEADERS
    )
    assert resp.json() == {"name": None, "icon_url": None}


def test_guild_info_requires_webapp_key(client):
    resp = client.get("/api/internal/guild-info", params={"guild_id": "123"})
    assert resp.status_code == 401
