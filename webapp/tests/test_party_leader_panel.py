"""공대 상세 페이지의 파티장 관리 패널 노출/동작 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

PARTY_DETAIL_URL = "http://bot-server.internal/api/internal/parties/p1"
RAIDS_URL = "http://bot-server.internal/api/internal/raids"
SUPPORT_CLASSES_URL = "http://bot-server.internal/api/internal/support-classes"
ELIGIBILITY_URL = "http://bot-server.internal/api/internal/parties/p1/eligibility"
INVITABLE_USERS_URL = "http://bot-server.internal/api/internal/parties/p1/invitable-users"
CLOSE_URL = "http://bot-server.internal/api/internal/parties/p1/close"
CLEAR_URL = "http://bot-server.internal/api/internal/parties/p1/clear"
KICK_URL = "http://bot-server.internal/api/internal/parties/p1/kick"
RESCHEDULE_URL = "http://bot-server.internal/api/internal/parties/p1/reschedule"
TRANSFER_URL = "http://bot-server.internal/api/internal/parties/p1/transfer-leader"
CANCEL_URL = "http://bot-server.internal/api/internal/parties/p1/cancel"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스",
        "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}

PARTY = {
    "message_id": "p1", "channel_id": "555", "guild_id": "test-guild-id",
    "leader_id": "111", "raid_name": "아르모체(4막)", "difficulty": "노말",
    "proficiency": "숙련", "scheduled_time": "05/20 20:00",
    "scheduled_datetime": "2026-05-20T20:00:00+09:00",
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": None,
    "slots": [
        {"slot_number": 1, "discord_id": "111", "character_name": "리더캐릭",
         "character_class": "워로드", "role": "dps"},
        {"slot_number": 2, "discord_id": "222", "character_name": "멤버캐릭",
         "character_class": "홀리나이트", "role": "support"},
    ],
}


def test_leader_sees_management_panel(client):
    with respx.mock:
        log_in(client, discord_id="111")  # 리더
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트"]))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "파티장 관리" in resp.text
    assert "멤버캐릭" in resp.text  # 강제퇴장/위임 대상 목록에 다른 멤버가 보임


def test_leader_sees_invite_form_with_candidates(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트"]))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(
            200, json={"success": True, "users": [{"discord_id": "333", "representative": "초대후보"}], "available_slots": [3, 4]}
        ))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "초대후보" in resp.text
    assert "/parties/p1/invite" in resp.text
    assert "3번 슬롯" in resp.text


def test_leader_invite_form_hidden_when_no_candidates(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트"]))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "/parties/p1/invite" not in resp.text


def test_invite_submit_posts_to_bot_and_redirects(client):
    INVITE_URL = "http://bot-server.internal/api/internal/parties/p1/invite"
    with respx.mock:
        log_in(client, discord_id="111")
        invite_route = respx.post(INVITE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/parties/p1/invite", data={"target_discord_id": "333", "slot_number": "3"})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert invite_route.called
    import json as _json
    payload = _json.loads(invite_route.calls[0].request.content)
    assert payload == {"discord_id": "111", "target_discord_id": "333", "slot_number": 3}


def test_invite_submit_shows_error_on_failure(client):
    INVITE_URL = "http://bot-server.internal/api/internal/parties/p1/invite"
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(INVITE_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "이미 초대된 유저입니다."})
        )
        resp = client.post("/parties/p1/invite", data={"target_discord_id": "333", "slot_number": "3"})

    assert resp.status_code == 303
    assert "join_error=" in resp.headers["location"]


def test_non_leader_does_not_see_management_panel(client):
    with respx.mock:
        log_in(client, discord_id="222")  # 일반 멤버
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "파티장 관리" not in resp.text


def test_close_action_calls_bot(client):
    with respx.mock:
        log_in(client, discord_id="111")
        close_route = respx.post(CLOSE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json={**PARTY, "status": "closed"}))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post("/parties/p1/close")

    assert resp.status_code == 303  # redirect-after-POST — 뒤로가기 시 폼 재제출 방지
    assert resp.headers["location"] == "/parties/p1"
    assert close_route.called


def test_clear_action_shows_success(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(CLEAR_URL).mock(return_value=httpx.Response(200, json={"success": True, "cleared_count": 2}))
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json={**PARTY, "status": "disbanded"}))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post("/parties/p1/clear")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"


def test_kick_action_shows_error_reason(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(KICK_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "파티원을 찾을 수 없습니다."})
        )
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트"]))

        resp = client.post("/parties/p1/kick", data={"target_discord_id": "222"})

    assert resp.status_code == 303  # 실패도 렌더하지 않고 에러 사유를 쿼리파라미터로 redirect
    assert "join_error=" in resp.headers["location"]

    with respx.mock:
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트"]))
        respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))
        resp2 = client.get(resp.headers["location"])
    assert "파티원을 찾을 수 없습니다" in resp2.text


def test_reschedule_action_calls_bot_with_datetime(client):
    with respx.mock:
        log_in(client, discord_id="111")
        reschedule_route = respx.post(RESCHEDULE_URL).mock(
            return_value=httpx.Response(200, json={"success": True, "scheduled_time": "05/21 21:00"})
        )
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post(
            "/parties/p1/reschedule",
            data={"scheduled_datetime": "2026-05-21T21:00", "memo": "새 공지"},
        )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert reschedule_route.called


def test_transfer_leader_action_calls_bot(client):
    with respx.mock:
        log_in(client, discord_id="111")
        transfer_route = respx.post(TRANSFER_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json={**PARTY, "leader_id": "222"}))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post("/parties/p1/transfer-leader", data={"new_leader_discord_id": "222"})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert transfer_route.called


def test_cancel_action_calls_bot_with_reason(client):
    with respx.mock:
        log_in(client, discord_id="111")
        cancel_route = respx.post(CANCEL_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json={**PARTY, "status": "disbanded"}))
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))

        resp = client.post("/parties/p1/cancel", data={"reason": "인원 부족"})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1?cancelled=1"


def test_cancel_success_shows_styled_confirmation_when_party_purged(client):
    """실제 취소 처리(db.purge_party)는 파티를 통째로 지우므로, 조회 시 null이 온다.
    이때 밋밋한 "찾을 수 없습니다"가 아니라 취소 완료를 알리는 카드가 떠야 한다."""
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(CANCEL_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, text="null"))

        resp = client.post("/parties/p1/cancel", data={"reason": "인원 부족"})
        assert resp.status_code == 303
        assert resp.headers["location"] == "/parties/p1?cancelled=1"

        resp2 = client.get(resp.headers["location"])

    assert resp2.status_code == 200
    assert "공대가 취소되었습니다" in resp2.text
    assert "party-empty-card" in resp2.text


def test_visiting_unknown_party_shows_not_found_not_cancelled_message(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, text="null"))

        resp = client.get("/parties/p1")

    assert resp.status_code == 200
    assert "공대를 찾을 수 없습니다" in resp.text
    assert "취소되었습니다" not in resp.text
