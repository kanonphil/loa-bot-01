"""봇 서버 오류가 원시 500 대신 안내 페이지로 떨어지는지(webapp/main.py의
httpx.HTTPError 핸들러) 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp import config
from webapp.tests.conftest import log_in

PARTIES_URL = "http://bot-server.internal/api/internal/parties"
USER_CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters"
ADMIN_PARTIES_URL = "http://bot-server.internal/api/internal/admin/parties"


def test_bot_server_error_shows_friendly_page(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTIES_URL).mock(return_value=httpx.Response(500, text="boom"))
        respx.get(USER_CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/parties")

    assert resp.status_code == 502
    assert "봇 서버와 통신하지 못했습니다" in resp.text
    assert "/main" in resp.text


def test_bot_server_connection_error_shows_friendly_page(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTIES_URL).mock(side_effect=httpx.ConnectError("refused"))
        respx.get(USER_CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/parties")

    assert resp.status_code == 502
    assert "봇 서버와 통신하지 못했습니다" in resp.text


def test_bot_403_explains_admin_revoked(client, monkeypatch):
    """로그인 뒤 관리자 목록에서 빠진 세션 — 봇이 403을 주면 재로그인을 안내한다."""
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(ADMIN_PARTIES_URL).mock(return_value=httpx.Response(403, json={"detail": "관리자 권한이 없습니다."}))
        respx.get("http://bot-server.internal/api/internal/admin/status").mock(return_value=httpx.Response(403, json={"detail": "관리자 권한이 없습니다."}))
        respx.get("http://bot-server.internal/api/internal/admin/forum-channel").mock(return_value=httpx.Response(403, json={"detail": "관리자 권한이 없습니다."}))
        resp = client.get("/admin/parties")

    assert resp.status_code == 403
    assert "관리자 권한이 없습니다" in resp.text
    assert "다시 로그인" in resp.text


def test_htmx_request_gets_plain_text(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTIES_URL).mock(return_value=httpx.Response(500, text="boom"))
        respx.get(USER_CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/parties", headers={"HX-Request": "true"})

    assert resp.status_code == 502
    assert resp.text == "봇 서버와 통신하지 못했습니다"
