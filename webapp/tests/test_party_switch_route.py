"""공대 참여 캐릭터 변경(파티를 나갔다 재참여하지 않고 캐릭터만 교체) 웹 라우트 검증
— 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

PARTY_DETAIL_URL = "http://bot-server.internal/api/internal/parties/p1"
RAIDS_URL = "http://bot-server.internal/api/internal/raids"
SWITCH_ELIGIBILITY_URL = "http://bot-server.internal/api/internal/parties/p1/switch-eligibility"
SWITCH_URL = "http://bot-server.internal/api/internal/parties/p1/switch-character"

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

PARTY = {
    "message_id": "p1",
    "channel_id": "555",
    "guild_id": "test-guild-id",
    "leader_id": "222",
    "raid_name": "아르모체(4막)",
    "difficulty": "노말",
    "proficiency": "숙련",
    "scheduled_time": "05/20 20:00",
    "scheduled_datetime": "2026-05-20T20:00:00+09:00",
    "total_slots": 8,
    "min_level": 1700,
    "status": "recruiting",
    "memo": "음성 필수",
    "slots": [
        {"slot_number": 1, "discord_id": "222", "character_name": "워로드캐릭",
         "character_class": "워로드", "role": "dps"},
    ],
}

ELIGIBILITY = {
    "can_switch": True,
    "current_character": "워로드캐릭",
    "candidates": [
        {"name": "부캐1", "level": 1710.0, "class": "홀리나이트", "in_other_party": None},
        {"name": "부캐2", "level": 1720.0, "class": "바드",
         "in_other_party": {"message_id": "p2", "raid_name": "아르모체(4막)"}},
    ],
    "gold_done": ["골드완료캐릭"],
    "level_too_low": [{"name": "저레벨캐릭", "level": 1500.0}],
    "no_cache": ["캐시없는캐릭"],
}


def test_party_detail_shows_switch_button_when_joined(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "party-switch-btn" in resp.text
    assert "/parties/p1/switch" in resp.text


def test_switch_form_lists_candidates_and_marks_other_party(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(SWITCH_ELIGIBILITY_URL).mock(return_value=httpx.Response(200, json=ELIGIBILITY))
        resp = client.get("/parties/p1/switch")

    assert resp.status_code == 200
    body = resp.text
    assert "워로드캐릭" in body  # 현재 참여 캐릭터 안내
    assert "부캐1" in body
    assert "부캐2" in body
    assert "타 공대 참여중" in body
    # 부적격 캐릭터는 선택 불가 안내로만 노출
    assert "골드완료캐릭" in body
    assert "저레벨캐릭" in body
    assert "캐시없는캐릭" in body


def test_switch_form_redirects_to_detail_when_cannot_switch(client):
    with respx.mock:
        log_in(client, discord_id="999")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(SWITCH_ELIGIBILITY_URL).mock(
            return_value=httpx.Response(
                200, json={"can_switch": False, "reason": "이 파티에 참여하고 있지 않습니다."}
            )
        )
        resp = client.get("/parties/p1/switch")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"


def test_switch_submit_posts_to_bot_and_redirects_on_success(client):
    with respx.mock:
        log_in(client, discord_id="222")
        switch_route = respx.post(SWITCH_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "left_other_party": None})
        )
        resp = client.post("/parties/p1/switch", data={"character_name": "부캐1"})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert switch_route.called
    sent = switch_route.calls.last.request
    import json as _json

    payload = _json.loads(sent.content)
    assert payload == {"discord_id": "222", "character_name": "부캐1"}


def test_switch_submit_shows_error_on_failure(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.post(SWITCH_URL).mock(
            return_value=httpx.Response(
                200, json={"success": False, "reason": "선택한 캐릭터는 참여 조건을 만족하지 않습니다."}
            )
        )
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post("/parties/p1/switch", data={"character_name": "부캐1"})

    assert resp.status_code == 303
    assert "/parties/p1?join_error=" in resp.headers["location"]
