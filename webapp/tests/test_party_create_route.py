"""공대 개설(/parties/create) 웹 라우트 검증 — 봇 서버는 respx로 모킹."""
import json

import httpx
import respx

from webapp.tests.conftest import log_in

RAIDS_URL = "http://bot-server.internal/api/internal/raids"
PROFICIENCY_URL = "http://bot-server.internal/api/internal/parties/proficiency-options"
CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters-grouped"
SUPPORT_CLASSES_URL = "http://bot-server.internal/api/internal/support-classes"
CREATE_URL = "http://bot-server.internal/api/internal/parties/create"
JOIN_URL = "http://bot-server.internal/api/internal/parties/12345/join"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스",
        "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    "비활성레이드": {
        "short_name": "비활성", "icon": "💤", "category": "카제로스",
        "is_extreme": False, "is_active": False,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1600, "total_slots": 4, "party_split": None, "gates": 1}},
    },
}
PROFICIENCY = [
    {"value": "숙련", "label": "숙련", "description": "이 레이드를 완전 숙지"},
    {"value": "트라이", "label": "트라이", "description": "처음 도전하는 단계"},
]
CHARACTERS = [
    {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "account_label": "본계정"},
    {"character_name": "워로드둘째", "character_class": "워로드", "item_level": 1710.0, "account_label": "본계정"},
]


def _mock_form_deps():
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(PROFICIENCY_URL).mock(return_value=httpx.Response(200, json=PROFICIENCY))
    respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
    respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트", "바드", "도화가"]))


def test_create_form_requires_login(client):
    resp = client.get("/parties/create")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_create_form_shows_only_active_raids_and_own_characters(client):
    with respx.mock:
        log_in(client)
        _mock_form_deps()
        resp = client.get("/parties/create")

    assert resp.status_code == 200
    assert "4막" in resp.text
    assert "💤 비활성" not in resp.text
    assert "숙련" in resp.text
    assert "트라이" in resp.text
    assert "발키리" in resp.text
    assert "워로드둘째" in resp.text
    assert "선택 안 함" in resp.text
    # 홀리나이트(서포터)는 true, 워로드(딜러 전용)는 false로 JS에 전달돼야 한다
    assert '"발키리": true' in resp.text
    assert '"워로드둘째": false' in resp.text


def _post_create(client, **overrides):
    data = {
        "raid_name": "아르모체(4막)",
        "difficulty": "노말",
        "proficiency": "숙련",
        "scheduled_datetime": "2026-05-20T20:00",
        "memo": "음성 필수",
        "character_name": "",
        "role": "dps",
    }
    data.update(overrides)
    respx.post(CREATE_URL).mock(
        return_value=httpx.Response(200, json={"success": True, "message_id": "12345"})
    )
    return client.post("/parties/create", data=data)


def test_create_submit_redirects_on_success_without_character_selected(client):
    with respx.mock:
        log_in(client)
        resp = _post_create(client)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/12345"


def test_create_submit_joins_with_explicitly_selected_character_and_role(client):
    """공대장이 개설 폼에서 직접 캐릭터와 역할을 골랐으면, 그 값 그대로 참여 API에 전달돼야 한다
    (봇이 임의로 캐릭터나 역할을 자동 판정하지 않음)."""
    with respx.mock:
        log_in(client, discord_id="111")
        join_route = respx.post(JOIN_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = _post_create(client, character_name="발키리", role="support")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/12345"
    assert join_route.called
    sent = json.loads(join_route.calls.last.request.content)
    assert sent["discord_id"] == "111"
    assert sent["character_name"] == "발키리"
    assert sent["role"] == "support"


def test_create_submit_does_not_call_join_when_no_character_selected(client):
    with respx.mock:
        log_in(client, discord_id="111")
        join_route = respx.post(JOIN_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = _post_create(client, character_name="")

    assert resp.status_code == 303
    assert not join_route.called


def test_create_submit_redirects_with_join_error_when_join_fails(client):
    """선택한 캐릭터로 참여가 실패해도(레벨 미달 등) 공대는 이미 개설된 상태이니,
    실패 사유를 상세 페이지에 표시하며 그대로 이동한다."""
    from urllib.parse import parse_qs, urlparse

    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(JOIN_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "레벨이 부족합니다."})
        )
        resp = _post_create(client, character_name="발키리", role="support")

    assert resp.status_code == 303
    parsed = urlparse(resp.headers["location"])
    assert parsed.path == "/parties/12345"
    assert parse_qs(parsed.query)["join_error"] == ["레벨이 부족합니다."]


def test_create_submit_shows_error_on_failure(client):
    with respx.mock:
        log_in(client)
        respx.post(CREATE_URL).mock(
            return_value=httpx.Response(
                200, json={"success": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."}
            )
        )
        _mock_form_deps()
        resp = client.post(
            "/parties/create",
            data={
                "raid_name": "아르모체(4막)",
                "difficulty": "노말",
                "proficiency": "숙련",
                "scheduled_datetime": "2026-05-20T20:00",
                "memo": "",
                "character_name": "",
                "role": "dps",
            },
        )

    assert resp.status_code == 200
    assert "/api등록" in resp.text
