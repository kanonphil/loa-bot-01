"""원정대 관리 웹 페이지 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in, toast_of, without_toast

CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters-grouped"
ADD_URL = "http://bot-server.internal/api/internal/characters/add"
REMOVE_URL = "http://bot-server.internal/api/internal/characters/remove"
SYNC_URL = "http://bot-server.internal/api/internal/characters/sync"
ADD_ACCOUNT_URL = "http://bot-server.internal/api/internal/accounts/add"
LIST_ACCOUNTS_URL = "http://bot-server.internal/api/internal/accounts/list"
REMOVE_ACCOUNT_URL = "http://bot-server.internal/api/internal/accounts/remove"

CHARACTERS = [
    {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "account_label": "발키리"},
]

ACCOUNTS = [
    {"id": 1, "label": "발키리", "added_at": "2026-01-01T00:00:00", "masked_key": "abcd1234****wxyz"},
]

TWO_ACCOUNT_CHARACTERS = [
    {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "account_label": "발키리"},
    {"character_name": "워로드부캐", "character_class": "워로드", "item_level": 1700.0, "account_label": "발키리"},
    {"character_name": "슬레이어", "character_class": "슬레이어", "item_level": 1690.0, "account_label": "슬레이어부계정"},
]


def _mock_accounts(accounts=None):
    respx.get(LIST_ACCOUNTS_URL).mock(return_value=httpx.Response(200, json=accounts if accounts is not None else []))


def test_expedition_requires_login(client):
    resp = client.get("/expedition")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_expedition_page_lists_characters(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        _mock_accounts()
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "발키리" in resp.text
    assert "홀리나이트" in resp.text


def test_expedition_page_empty_state(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        _mock_accounts()
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "등록된 캐릭터가 없습니다" in resp.text


def test_expedition_page_groups_by_account_when_multiple_accounts(client):
    """부계정이 있는 유저는 계정 라벨별로 캐릭터가 묶여 표시돼야 한다."""
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=TWO_ACCOUNT_CHARACTERS))
        _mock_accounts()
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
        _mock_accounts()
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "expedition-account-title" not in resp.text


def test_expedition_page_lists_my_accounts_with_masked_key(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        _mock_accounts(ACCOUNTS)
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "abcd1234****wxyz" in resp.text
    assert 'name="key_id" value="1"' in resp.text


def test_expedition_page_hides_account_section_when_no_accounts(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        _mock_accounts([])
        resp = client.get("/expedition")

    assert resp.status_code == 200
    assert "내 계정" not in resp.text


def test_add_character_success_redirects_with_toast(client):
    """POST가 페이지를 직접 렌더하면 뒤로가기가 그 응답으로 돌아가고 F5가 동작을 재실행한다 —
    전부 303 redirect + 1회성 토스트로."""
    with respx.mock:
        log_in(client)
        respx.post(ADD_URL).mock(
            return_value=httpx.Response(
                200,
                json={"success": True, "character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0},
            )
        )
        resp = client.post("/expedition/add", data={"character_name": "발키리"})

    assert resp.status_code == 303
    assert without_toast(resp.headers["location"]) == "/expedition"
    text, kind = toast_of(resp.headers["location"])
    assert kind == "success" and "발키리" in text and "등록 완료" in text


def test_add_character_failure_redirects_with_error_toast(client):
    with respx.mock:
        log_in(client)
        respx.post(ADD_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "이미 등록된 캐릭터입니다."})
        )
        resp = client.post("/expedition/add", data={"character_name": "발키리"})

    assert resp.status_code == 303
    assert toast_of(resp.headers["location"]) == ("이미 등록된 캐릭터입니다.", "error")


def test_failure_without_reason_still_shows_a_toast(client):
    """봇이 reason 없이 실패를 주면 예전엔 빈 토스트(=아무 표시 없음)였다."""
    with respx.mock:
        log_in(client)
        respx.post(ADD_URL).mock(return_value=httpx.Response(200, json={"success": False}))
        resp = client.post("/expedition/add", data={"character_name": "발키리"})
    text, kind = toast_of(resp.headers["location"])
    assert kind == "error" and text


def test_remove_character_calls_bot_and_redirects(client):
    with respx.mock:
        log_in(client)
        remove_route = respx.post(REMOVE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/expedition/remove", data={"character_name": "발키리"})

    assert resp.status_code == 303 and remove_route.called
    assert without_toast(resp.headers["location"]) == "/expedition"


def test_sync_redirects_with_result_toast(client):
    with respx.mock:
        log_in(client)
        respx.post(SYNC_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "updated": 2, "total": 2})
        )
        resp = client.post("/expedition/sync")

    assert resp.status_code == 303
    assert toast_of(resp.headers["location"])[0] == "2/2개 캐릭터 동기화 완료"


def test_sync_can_return_to_caller_page(client):
    with respx.mock:
        log_in(client)
        respx.post(SYNC_URL).mock(return_value=httpx.Response(200, json={"success": True, "updated": 1, "total": 1}))
        resp = client.post("/expedition/sync", data={"next": "/main"})
        evil = client.post("/expedition/sync", data={"next": "//evil.example"})
    assert without_toast(resp.headers["location"]) == "/main"
    assert without_toast(evil.headers["location"]) == "/expedition"  # 외부 리다이렉트 금지


def test_add_account_success_redirects_with_toast(client):
    with respx.mock:
        log_in(client)
        respx.post(ADD_ACCOUNT_URL).mock(
            return_value=httpx.Response(
                200, json={"success": True, "label": "슬레이어부계정", "added": 3, "total": 3}
            )
        )
        resp = client.post(
            "/expedition/add-account",
            data={"api_key": "dummy-key", "character_name": "슬레이어부계정"},
        )

    assert resp.status_code == 303
    text, _ = toast_of(resp.headers["location"])
    assert "슬레이어부계정" in text and "3/3개" in text


def test_add_account_failure_redirects_with_reason(client):
    with respx.mock:
        log_in(client)
        respx.post(ADD_ACCOUNT_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "동물롱장 길드 소속이 아닙니다."})
        )
        resp = client.post("/expedition/add-account", data={"api_key": "dummy-key", "character_name": "발키리"})

    assert toast_of(resp.headers["location"]) == ("동물롱장 길드 소속이 아닙니다.", "error")


def test_remove_account_redirects(client):
    with respx.mock:
        log_in(client)
        remove_route = respx.post(REMOVE_ACCOUNT_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        ok = client.post("/expedition/remove-account", data={"key_id": "1"})
        respx.post(REMOVE_ACCOUNT_URL).mock(return_value=httpx.Response(200, json={"success": False}))
        bad = client.post("/expedition/remove-account", data={"key_id": "999"})

    assert remove_route.called
    assert toast_of(ok.headers["location"])[0] == "계정이 삭제되었습니다."
    assert toast_of(bad.headers["location"]) == ("계정을 찾을 수 없습니다.", "error")


def test_expedition_page_renders_toast_from_query(client):
    """base.html이 ?toast= 를 flash-data로 바꿔 어떤 페이지든 1회 토스트를 띄운다."""
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
        _mock_accounts()
        resp = client.get("/expedition?toast=%EB%93%B1%EB%A1%9D%20%EC%99%84%EB%A3%8C&toast_type=success")
    assert 'data-message="등록 완료"' in resp.text and 'data-strip-url="1"' in resp.text
    assert 'type="password"' in resp.text  # API 키는 비밀 입력
    assert "삭제할까요" in resp.text  # 캐릭터 삭제 confirm
