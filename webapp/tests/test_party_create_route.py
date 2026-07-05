"""공대 개설(/parties/create) 웹 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

RAIDS_URL = "http://bot-server.internal/api/internal/raids"
PROFICIENCY_URL = "http://bot-server.internal/api/internal/parties/proficiency-options"
CREATE_URL = "http://bot-server.internal/api/internal/parties/create"

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


def test_create_submit_redirects_on_success(client):
    with respx.mock:
        log_in(client)
        respx.post(CREATE_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "message_id": "12345"})
        )
        resp = client.post(
            "/parties/create",
            data={
                "raid_name": "아르모체(4막)",
                "difficulty": "노말",
                "proficiency": "숙련",
                "scheduled_datetime": "2026-05-20T20:00",
                "memo": "음성 필수",
            },
        )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/12345"


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
