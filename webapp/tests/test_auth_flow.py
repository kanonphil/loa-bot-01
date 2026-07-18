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


def test_login_with_error_shows_message_instead_of_looping_to_discord(client):
    """회귀 테스트: /login이 error 쿼리파라미터를 무시하고 곧장 Discord 인증 화면으로
    다시 보내던 버그 — 미등록 유저나 세션이 깨진 유저가 '승인'을 눌러도 똑같은 화면만
    반복되는 무한 루프였다. 이제는 Discord로 안 보내고 안내 문구를 보여줘야 한다."""
    resp = client.get("/login", params={"error": "not_registered"})
    assert resp.status_code == 200  # 302로 Discord에 다시 보내지 않음
    assert "/api등록" in resp.text

    resp2 = client.get("/login", params={"error": "invalid_state"})
    assert resp2.status_code == 200
    assert "다시 시도" in resp2.text

    resp3 = client.get("/login", params={"error": "unknown_code"})
    assert resp3.status_code == 200
    assert "로그인에 실패했습니다" in resp3.text


def test_unregistered_user_sees_guidance_after_full_redirect_chain(client):
    """미등록 유저가 승인 → 콜백(미등록 거부) → /login으로 이어지는 실제 흐름을 끝까지
    따라가도 Discord로 다시 튕기지 않고 안내 메시지에서 멈춰야 한다."""
    import httpx

    with respx.mock:
        login_resp = client.get("/login")
        state = extract_state(login_resp.headers["location"])

        respx.post("https://discord.com/api/v10/oauth2/token").mock(
            return_value=httpx.Response(200, json={"access_token": "fake-token"})
        )
        respx.get("https://discord.com/api/v10/users/@me").mock(
            return_value=httpx.Response(200, json={"id": "999999", "username": "outsider"})
        )
        respx.get("http://bot-server.internal/api/internal/verify-user").mock(
            return_value=httpx.Response(200, json={"discord_id": "999999", "registered": False})
        )

        callback_resp = client.get("/callback", params={"code": "abc", "state": state})
        redirect_target = callback_resp.headers["location"]
        final_resp = client.get(redirect_target)

    assert final_resp.status_code == 200  # Discord로 다시 리다이렉트(302)되지 않음
    assert "/api등록" in final_resp.text


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
