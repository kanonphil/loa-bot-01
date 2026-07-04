"""원정대 관리 웹 페이지 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters"
ADD_URL = "http://bot-server.internal/api/internal/characters/add"
REMOVE_URL = "http://bot-server.internal/api/internal/characters/remove"
SYNC_URL = "http://bot-server.internal/api/internal/characters/sync"

CHARACTERS = [
    {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0},
]


def test_expedition_requires_login(client):
    resp = client.get("/expedition")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_expedition_page_lists_characters(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "발키리" in resp.text
    assert "홀리나이트" in resp.text


def test_expedition_page_empty_state(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "등록된 캐릭터가 없습니다" in resp.text


def test_add_character_success_shows_confirmation(client):
    with respx.mock:
        log_in(client)
        respx.post(ADD_URL).mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0},
            )
        )
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))

        resp = client.post("/expedition/add", data={"character_name": "발키리"})

    assert resp.status_code == 200
    assert "등록 완료" in resp.text


def test_add_character_failure_shows_reason(client):
    with respx.mock:
        log_in(client)
        respx.post(ADD_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "이미 등록된 캐릭터입니다."})
        )
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))

        resp = client.post("/expedition/add", data={"character_name": "발키리"})

    assert resp.status_code == 200
    assert "이미 등록된 캐릭터입니다" in resp.text


def test_remove_character_calls_bot(client):
    with respx.mock:
        log_in(client)
        remove_route = respx.post(REMOVE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))

        resp = client.post("/expedition/remove", data={"character_name": "발키리"})

    assert resp.status_code == 200
    assert remove_route.called


def test_sync_shows_result(client):
    with respx.mock:
        log_in(client)
        respx.post(SYNC_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "updated": 2, "total": 2})
        )
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))

        resp = client.post("/expedition/sync")

    assert resp.status_code == 200
    assert "2/2개 캐릭터 동기화 완료" in resp.text
