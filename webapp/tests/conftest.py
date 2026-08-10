import os

os.environ.setdefault("DISCORD_CLIENT_ID", "test-client-id")
os.environ.setdefault("DISCORD_CLIENT_SECRET", "test-client-secret")
os.environ.setdefault("DISCORD_REDIRECT_URI", "http://localhost:8001/callback")
os.environ.setdefault("BOT_API_BASE_URL", "http://bot-server.internal")
os.environ.setdefault("BOT_API_WEBAPP_KEY", "test-webapp-key")
os.environ.setdefault("DISCORD_GUILD_ID", "test-guild-id")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
# 로컬 실제 .env에 SESSION_HTTPS_ONLY=true가 있어도 테스트는 항상 http로 도니 강제로 false —
# 안 그러면 세션 쿠키에 Secure가 붙어서 TestClient가 로그인 쿠키를 안 돌려보내 전부 로그아웃 상태로 보인다.
os.environ["SESSION_HTTPS_ONLY"] = "false"

import asyncio
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from webapp import config, notification_store
from webapp.main import app

TOKEN_URL = "https://discord.com/api/v10/oauth2/token"
USER_URL = "https://discord.com/api/v10/users/@me"
VERIFY_URL = "http://bot-server.internal/api/internal/verify-user"
USER_CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters"


@pytest.fixture(autouse=True)
def _reset_bot_client_cache():
    """bot_client.get_raids/get_raid_categories/get_support_classes에 붙은 TTL 캐시가
    테스트 간에 새어나가면, 어떤 테스트가 먼저 캐시를 채우느냐에 따라 respx 목킹값이
    무시되고 다른 테스트의 값이 튀어나올 수 있다 — 매 테스트 전후로 비운다."""
    from webapp.clients import bot_client

    bot_client._cache.clear()
    yield
    bot_client._cache.clear()


@pytest.fixture()
def notification_db(tmp_path, monkeypatch):
    """앱의 lifespan(startup)에 기대지 않고, 테스트가 직접 알림 DB를 준비한다."""
    path = str(tmp_path / "notification_test.db")
    monkeypatch.setattr(config, "NOTIFICATION_DB_PATH", path)
    asyncio.run(notification_store.init_db())
    return path


@pytest.fixture()
def client(notification_db):
    return TestClient(app, follow_redirects=False)


def extract_state(location: str) -> str:
    return parse_qs(urlparse(location).query)["state"][0]


def log_in(client: TestClient, discord_id: str = "111", username: str = "tester"):
    """respx.mock 컨텍스트 안에서 호출 — Discord/봇서버를 모킹해 로그인 상태로 만든다."""
    login_resp = client.get("/login")
    state = extract_state(login_resp.headers["location"])

    respx.post(TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"access_token": "fake-token"})
    )
    respx.get(USER_URL).mock(
        return_value=httpx.Response(200, json={"id": discord_id, "username": username})
    )
    respx.get(VERIFY_URL).mock(
        return_value=httpx.Response(200, json={"discord_id": discord_id, "registered": True})
    )
    respx.get(USER_CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
    return client.get("/callback", params={"code": "abc", "state": state})
