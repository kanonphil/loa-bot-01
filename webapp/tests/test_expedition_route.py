"""원정대 관리 웹 페이지 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters-grouped"
ADD_URL = "http://bot-server.internal/api/internal/characters/add"
REMOVE_URL = "http://bot-server.internal/api/internal/characters/remove"
SYNC_URL = "http://bot-server.internal/api/internal/characters/sync"
ADD_ACCOUNT_URL = "http://bot-server.internal/api/internal/accounts/add"

CHARACTERS = [
    {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "account_label": "발키리"},
]

TWO_ACCOUNT_CHARACTERS = [
    {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "account_label": "발키리"},
    {"character_name": "워로드부캐", "character_class": "워로드", "item_level": 1700.0, "account_label": "발키리"},
    {"character_name": "슬레이어", "character_class": "슬레이어", "item_level": 1690.0, "account_label": "슬레이어부계정"},
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


def test_expedition_page_groups_by_account_when_multiple_accounts(client):
    """부계정이 있는 유저는 계정 라벨별로 캐릭터가 묶여 표시돼야 한다."""
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=TWO_ACCOUNT_CHARACTERS))
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "발키리" in resp.text
    assert "슬레이어부계정" in resp.text
    assert "워로드부캐" in resp.text
    assert "슬레이어" in resp.text
    # 계정 그룹 제목이 실제로 렌더링됐는지 확인
    assert "expedition-account-title" in resp.text


def test_expedition_page_single_account_has_no_group_title(client):
    """계정이 1개뿐이면 그룹 제목 없이 기존처럼 단순 목록으로 보여준다."""
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "expedition-account-title" not in resp.text


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


def test_add_account_success_shows_confirmation(client):
    with respx.mock:
        log_in(client)
        respx.post(ADD_ACCOUNT_URL).mock(
            return_value=httpx.Response(
                200, json={"success": True, "label": "슬레이어부계정", "added": 3, "total": 3}
            )
        )
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))

        resp = client.post(
            "/expedition/add-account",
            data={"api_key": "dummy-key", "character_name": "슬레이어부계정"},
        )

    assert resp.status_code == 200
    assert "슬레이어부계정" in resp.text
    assert "3/3개" in resp.text


def test_add_account_failure_shows_reason(client):
    with respx.mock:
        log_in(client)
        respx.post(ADD_ACCOUNT_URL).mock(
            return_value=httpx.Response(
                200, json={"success": False, "reason": "동물롱장 길드 소속이 아닙니다."}
            )
        )
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))

        resp = client.post(
            "/expedition/add-account",
            data={"api_key": "dummy-key", "character_name": "발키리"},
        )

    assert resp.status_code == 200
    assert "동물롱장 길드 소속이 아닙니다" in resp.text
