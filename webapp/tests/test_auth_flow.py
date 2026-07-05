"""webapp의 Discord OAuth 로그인 게이트가 실제로 동작하는지 검증.
Discord와 봇 서버 내부 API는 respx로 모킹 — 실제 네트워크/실제 계정 없이 전체 흐름을 확인한다.
"""
from urllib.parse import parse_qs, urlparse

import respx

from webapp.tests.conftest import extract_state, log_in


def test_login_redirects_to_discord_with_expected_params(client):
    resp = client.get("/login")
    assert resp.status_code in (302, 307)
    location = resp.headers["location"]
    parsed = urlparse(location)
    assert parsed.netloc == "discord.com"
    qs = parse_qs(parsed.query)
    assert qs["client_id"] == ["test-client-id"]
    assert qs["redirect_uri"] == ["http://localhost:8001/callback"]
    assert qs["response_type"] == ["code"]
    assert qs["scope"] == ["identify"]
    assert "state" in qs


def test_home_without_session_redirects_to_login(client):
    resp = client.get("/ai-chat")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_callback_mismatched_state_denied(client):
    client.get("/login")  # 세션에 oauth_state 저장
    resp = client.get("/callback", params={"code": "abc", "state": "wrong-state"})
    assert resp.status_code in (302, 307)
    assert "error=invalid_state" in resp.headers["location"]


def test_unregistered_user_denied_full_flow(client):
    import httpx

    with respx.mock:
        login_resp = client.get("/login")
        state = extract_state(login_resp.headers["location"])

        respx.post("https://discord.com/api/v10/oauth2/token").mock(
            return_value=httpx.Response(200, json={"access_token": "fake-token"})
        )
        respx.get("https://discord.com/api/v10/users/@me").mock(
            return_value=httpx.Response(
                200, json={"id": "999999", "username": "outsider"}
            )
        )
        respx.get("http://bot-server.internal/api/internal/verify-user").mock(
            return_value=httpx.Response(
                200, json={"discord_id": "999999", "registered": False}
            )
        )

        callback_resp = client.get("/callback", params={"code": "abc", "state": state})
        assert callback_resp.status_code in (302, 307)
        assert "error=not_registered" in callback_resp.headers["location"]

        # 세션에 user가 안 심겼으니 /ai-chat는 여전히 막혀야 한다
        home_resp = client.get("/ai-chat")
    assert home_resp.headers["location"] == "/login"


def test_registered_user_full_login_flow(client):
    with respx.mock:
        callback_resp = log_in(client)
        assert callback_resp.status_code in (302, 307)
        assert callback_resp.headers["location"] == "/main"  # 로그인 성공 후 메인 대시보드로 이동

        home_resp = client.get("/ai-chat")

    assert home_resp.status_code == 200
    assert "tester" in home_resp.text  # 환영 문구에 username이 들어감
    from webapp.content.greetings import _TEMPLATES

    assert any(t.format(username="tester") in home_resp.text for t in _TEMPLATES)


def test_root_redirects_logged_in_user_to_main(client):
    with respx.mock:
        log_in(client)
        resp = client.get("/")

    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/main"


def test_root_shows_landing_page_when_not_logged_in(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "디스코드로 로그인" in resp.text
