"""공대 개설(/parties/create) 웹 라우트 검증 — 봇 서버는 respx로 모킹."""
import json

import httpx
import respx

from webapp.tests.conftest import log_in

RAIDS_URL = "http://bot-server.internal/api/internal/raids"
PROFICIENCY_URL = "http://bot-server.internal/api/internal/parties/proficiency-options"
CREATE_URL = "http://bot-server.internal/api/internal/parties/create"
ELIGIBILITY_URL = "http://bot-server.internal/api/internal/parties/12345/eligibility"
JOIN_URL = "http://bot-server.internal/api/internal/parties/12345/join"

NOT_ELIGIBLE = {"can_join": False, "reason": "이미 파티에 참여 중입니다."}

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


def test_create_form_requires_login(client):
    resp = client.get("/parties/create")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_create_form_shows_only_active_raids(client):
    with respx.mock:
        log_in(client)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(PROFICIENCY_URL).mock(return_value=httpx.Response(200, json=PROFICIENCY))
        resp = client.get("/parties/create")

    assert resp.status_code == 200
    assert "4막" in resp.text
    assert "비활성" not in resp.text
    assert "숙련" in resp.text
    assert "트라이" in resp.text


def _post_create(client, **overrides):
    data = {
        "raid_name": "아르모체(4막)",
        "difficulty": "노말",
        "proficiency": "숙련",
        "scheduled_datetime": "2026-05-20T20:00",
        "memo": "음성 필수",
    }
    data.update(overrides)
    respx.post(CREATE_URL).mock(
        return_value=httpx.Response(200, json={"success": True, "message_id": "12345"})
    )
    return client.post("/parties/create", data=data)


def test_create_submit_redirects_on_success(client):
    with respx.mock:
        log_in(client)
        respx.get(ELIGIBILITY_URL).mock(return_value=httpx.Response(200, json=NOT_ELIGIBLE))
        resp = _post_create(client)

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/12345"


def test_create_submit_auto_joins_when_exactly_one_qualifying_character(client):
    """공대장이 조건을 만족하는 캐릭터가 하나뿐이면, 개설 직후 참여 버튼을 따로 안 눌러도
    자동으로 참여돼야 한다."""
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "can_join": True,
                    "qualifying": [{"name": "발키리", "level": 1720.0, "class": "발키리"}],
                    "party_split": None,
                    "total_slots": 8,
                },
            )
        )
        join_route = respx.post(JOIN_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = _post_create(client)

    assert resp.status_code == 303
    assert join_route.called
    sent = json.loads(join_route.calls.last.request.content)
    assert sent["discord_id"] == "111"
    assert sent["character_name"] == "발키리"
    assert "role" not in sent  # role은 생략 — 봇이 직업 기준으로 자동 판정


def test_create_submit_does_not_auto_join_when_multiple_qualifying_characters(client):
    """어느 캐릭터로 참여할지 애매하면(부계정 등 여러 개 조건 만족) 자동 참여하지 않는다."""
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "can_join": True,
                    "qualifying": [
                        {"name": "발키리", "level": 1720.0, "class": "발키리"},
                        {"name": "워로드", "level": 1710.0, "class": "워로드"},
                    ],
                    "party_split": None,
                    "total_slots": 8,
                },
            )
        )
        join_route = respx.post(JOIN_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = _post_create(client)

    assert resp.status_code == 303
    assert not join_route.called


def test_create_submit_does_not_auto_join_when_party_group_choice_required(client):
    """레이드가 하위 그룹(party_split)으로 나뉘면 어느 그룹에 갈지 직접 골라야 하므로
    자동 참여하지 않는다."""
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "can_join": True,
                    "qualifying": [{"name": "발키리", "level": 1720.0, "class": "발키리"}],
                    "party_split": 4,
                    "total_slots": 8,
                },
            )
        )
        join_route = respx.post(JOIN_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = _post_create(client)

    assert resp.status_code == 303
    assert not join_route.called


def test_create_submit_does_not_auto_join_when_not_eligible(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(ELIGIBILITY_URL).mock(return_value=httpx.Response(200, json=NOT_ELIGIBLE))
        join_route = respx.post(JOIN_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = _post_create(client)

    assert resp.status_code == 303
    assert not join_route.called


def test_create_submit_shows_error_on_failure(client):
    with respx.mock:
        log_in(client)
        respx.post(CREATE_URL).mock(
            return_value=httpx.Response(
                200, json={"success": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."}
            )
        )
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(PROFICIENCY_URL).mock(return_value=httpx.Response(200, json=PROFICIENCY))
        resp = client.post(
            "/parties/create",
            data={
                "raid_name": "아르모체(4막)",
                "difficulty": "노말",
                "proficiency": "숙련",
                "scheduled_datetime": "2026-05-20T20:00",
                "memo": "",
            },
        )

    assert resp.status_code == 200
    assert "/api등록" in resp.text
