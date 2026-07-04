"""공대 모집 웹 페이지 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

PARTIES_URL = "http://bot-server.internal/api/internal/parties"
PARTY_DETAIL_URL = "http://bot-server.internal/api/internal/parties/p1"
ELIGIBILITY_URL = "http://bot-server.internal/api/internal/parties/p1/eligibility"
JOIN_URL = "http://bot-server.internal/api/internal/parties/p1/join"
LEAVE_URL = "http://bot-server.internal/api/internal/parties/p1/leave"
RAIDS_URL = "http://bot-server.internal/api/internal/raids"

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


def test_party_list_requires_login(client):
    resp = client.get("/parties")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_party_list_renders_cards(client):
    with respx.mock:
        log_in(client)
        respx.get(PARTIES_URL).mock(return_value=httpx.Response(200, json=[PARTY]))
        resp = client.get("/parties")

    assert resp.status_code == 200
    body = resp.text
    assert "아르모체(4막)" in body
    assert "1/8" in body


def test_party_detail_shows_join_form_when_eligible(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "can_join": True,
                    "qualifying": [{"name": "발키리", "level": 1710.0, "class": "홀리나이트"}],
                    "party_split": 4,
                    "total_slots": 8,
                    "gold_done": [], "in_other_party": [], "level_too_low": [], "no_cache": [],
                    "min_level": 1700,
                },
            )
        )
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    body = resp.text
    assert "party-join-form" in body
    assert "발키리" in body
    assert "1파티" in body and "2파티" in body  # party_split=4, total_slots=8 → 2개 하위 파티


def test_party_detail_shows_leave_when_already_joined(client):
    # eligibility 엔드포인트는 일부러 mock 안 함 — 이미 참여자면 호출 자체가 없어야 하고,
    # 만약 코드가 실수로 호출한다면 respx가 AllMockedAssertionError를 던져 이 테스트가 실패한다.
    with respx.mock:
        log_in(client, discord_id="222")  # PARTY의 기존 슬롯 주인
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "party-leave-btn" in resp.text


def test_party_detail_shows_reason_when_cannot_join(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(
                200, json={"can_join": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."}
            )
        )
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "/api등록" in resp.text


def test_join_posts_to_bot_and_shows_error_on_failure(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(
                200,
                json={
                    "can_join": True,
                    "qualifying": [{"name": "발키리", "level": 1710.0, "class": "홀리나이트"}],
                    "party_split": 4, "total_slots": 8,
                    "gold_done": [], "in_other_party": [], "level_too_low": [], "no_cache": [],
                    "min_level": 1700,
                },
            )
        )
        join_route = respx.post(JOIN_URL).mock(
            return_value=httpx.Response(
                200, json={"success": False, "reason": "다른 유저가 동시에 참여해 슬롯이 찼습니다."}
            )
        )

        resp = client.post(
            "/parties/p1/join",
            data={"character_name": "발키리", "role": "support", "party_group": "1"},
        )

    assert resp.status_code == 200
    assert join_route.called
    assert "동시에 참여" in resp.text


def test_leave_posts_to_bot(client):
    with respx.mock:
        log_in(client, discord_id="222")
        leave_route = respx.post(LEAVE_URL).mock(
            return_value=httpx.Response(200, json={"success": True})
        )
        after_leave_party = {**PARTY, "slots": []}
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=after_leave_party))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(200, json={"can_join": False, "reason": "파티가 존재하지 않습니다."})
        )

        resp = client.post("/parties/p1/leave")

    assert resp.status_code == 200
    assert leave_route.called


def test_split_party_groups_show_relative_numbers_per_group(monkeypatch):
    """회귀 테스트: 8인(4+4 분할) 파티는 1파티/2파티로 나뉘고, 각 파티 내부는
    절대 슬롯 번호가 아니라 1번부터 다시 매겨진 상대 번호로 표시되어야 한다.
    이전 버그: 절대 슬롯 5번이 '채워짐'과 '빈 자리'로 중복 표시됨.
    """
    import asyncio

    import webapp.routes.party as party_module

    async def fake_get_party(message_id):
        return {
            **PARTY,
            "slots": [
                {"slot_number": 1, "discord_id": "222", "character_name": "워로드캐릭",
                 "character_class": "워로드", "role": "dps"},
                {"slot_number": 5, "discord_id": "333", "character_name": "홀나힐러",
                 "character_class": "홀리나이트", "role": "support"},
            ],
        }

    async def fake_get_raids():
        return RAIDS

    async def fake_get_eligibility(message_id, discord_id):
        return {"can_join": False, "reason": "이미 참여 중입니다."}

    monkeypatch.setattr(party_module.bot_client, "get_party", fake_get_party)
    monkeypatch.setattr(party_module.bot_client, "get_raids", fake_get_raids)
    monkeypatch.setattr(party_module.bot_client, "get_party_eligibility", fake_get_eligibility)

    ctx = asyncio.run(party_module._detail_context("p1", "999999"))

    assert ctx["all_slots"] is None
    groups = ctx["party_groups"]
    assert [g["group_number"] for g in groups] == [1, 2]

    group1, group2 = groups
    assert [s["local_number"] for s in group1["slots"]] == [1, 2, 3, 4]
    assert group1["slots"][0]["filled"] is True
    assert group1["slots"][0]["character_name"] == "워로드캐릭"
    assert group1["filled_count"] == 1
    assert all(not s["filled"] for s in group1["slots"][1:])

    # 절대 슬롯 5번 = 2파티의 상대 1번 — "5번"이 아니라 "1번"으로 표시되어야 함
    assert [s["local_number"] for s in group2["slots"]] == [1, 2, 3, 4]
    assert group2["slots"][0]["filled"] is True
    assert group2["slots"][0]["character_name"] == "홀나힐러"
    assert group2["filled_count"] == 1


def test_non_split_party_still_uses_flat_slot_list(monkeypatch):
    """party_split이 없는(또는 total_slots<=party_split인) 파티는 기존처럼 단일 목록으로."""
    import asyncio

    import webapp.routes.party as party_module

    four_person_raids = {
        "세르카": {
            "short_name": "세르카", "icon": "🔔", "category": "그림자",
            "is_extreme": False, "is_active": True,
            "available_from": None, "available_until": None,
            "difficulties": {"노말": {"min_level": 1700, "total_slots": 4, "party_split": None, "gates": 2}},
        },
    }

    async def fake_get_party(message_id):
        return {
            **PARTY,
            "raid_name": "세르카",
            "total_slots": 4,
            "slots": [
                {"slot_number": 2, "discord_id": "222", "character_name": "워로드캐릭",
                 "character_class": "워로드", "role": "dps"},
            ],
        }

    async def fake_get_raids():
        return four_person_raids

    async def fake_get_eligibility(message_id, discord_id):
        return {"can_join": False, "reason": "이미 참여 중입니다."}

    monkeypatch.setattr(party_module.bot_client, "get_party", fake_get_party)
    monkeypatch.setattr(party_module.bot_client, "get_raids", fake_get_raids)
    monkeypatch.setattr(party_module.bot_client, "get_party_eligibility", fake_get_eligibility)

    ctx = asyncio.run(party_module._detail_context("p1", "999999"))

    assert ctx["party_groups"] is None
    numbers = [s["slot_number"] for s in ctx["all_slots"]]
    assert numbers == [1, 2, 3, 4]
    assert ctx["all_slots"][1]["filled"] is True
    assert ctx["all_slots"][1]["character_name"] == "워로드캐릭"
