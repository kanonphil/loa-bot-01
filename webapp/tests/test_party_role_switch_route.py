"""공대 참여 역할(딜러/서포터) 변경 웹 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

PARTY_DETAIL_URL = "http://bot-server.internal/api/internal/parties/p1"
RAIDS_URL = "http://bot-server.internal/api/internal/raids"
SUPPORT_CLASSES_URL = "http://bot-server.internal/api/internal/support-classes"
SWITCH_ROLE_URL = "http://bot-server.internal/api/internal/parties/p1/switch-role"
INVITABLE_USERS_URL = "http://bot-server.internal/api/internal/parties/p1/invitable-users"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스",
        "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {
            "노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2},
        },
    },
}

PARTY_AS_SUPPORT = {
    "message_id": "p1", "channel_id": "555", "guild_id": "test-guild-id", "leader_id": "222",
    "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
    "scheduled_time": "05/20 20:00", "scheduled_datetime": "2026-05-20T20:00:00+09:00",
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": "",
    "slots": [
        {"slot_number": 1, "discord_id": "222", "character_name": "홀나캐릭",
         "character_class": "홀리나이트", "role": "support"},
    ],
}

PARTY_AS_DPS_SUPPORT_CLASS = {
    **PARTY_AS_SUPPORT,
    "slots": [
        {"slot_number": 1, "discord_id": "222", "character_name": "홀나캐릭",
         "character_class": "홀리나이트", "role": "dps"},
    ],
}

PARTY_AS_DPS_NON_SUPPORT_CLASS = {
    **PARTY_AS_SUPPORT,
    "slots": [
        {"slot_number": 1, "discord_id": "222", "character_name": "워로드캐릭",
         "character_class": "워로드", "role": "dps"},
    ],
}


def test_party_detail_shows_dps_button_when_currently_support(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY_AS_SUPPORT))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "딜러로 변경" in resp.text
    assert "/parties/p1/switch-role" in resp.text


def test_party_detail_shows_support_button_when_dps_with_support_class(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY_AS_DPS_SUPPORT_CLASS))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트", "바드"]))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "서포터로 변경" in resp.text


def test_party_detail_hides_role_switch_when_dps_with_non_support_class(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY_AS_DPS_NON_SUPPORT_CLASS))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트", "바드"]))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "서포터로 변경" not in resp.text
    assert "딜러로 변경" not in resp.text


def test_switch_role_submit_posts_to_bot_and_redirects_on_success(client):
    with respx.mock:
        log_in(client, discord_id="222")
        switch_route = respx.post(SWITCH_ROLE_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "reason": None})
        )
        resp = client.post("/parties/p1/switch-role", data={"new_role": "dps"})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert switch_route.called
    import json as _json

    payload = _json.loads(switch_route.calls.last.request.content)
    assert payload == {"discord_id": "222", "new_role": "dps"}


def test_switch_role_submit_shows_error_on_failure(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.post(SWITCH_ROLE_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "이미 서포터가 있는 파티입니다."})
        )
        resp = client.post("/parties/p1/switch-role", data={"new_role": "support"})

    assert resp.status_code == 303
    assert "/parties/p1?join_error=" in resp.headers["location"]
