"""내게 온 초대(/invites) 웹 페이지 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

MY_INVITES_URL = "http://bot-server.internal/api/internal/my-invites"
ELIGIBILITY_URL = "http://bot-server.internal/api/internal/parties/700/eligibility"
SUPPORT_CLASSES_URL = "http://bot-server.internal/api/internal/support-classes"
ACCEPT_URL = "http://bot-server.internal/api/internal/invites/700/accept"
DECLINE_URL = "http://bot-server.internal/api/internal/invites/700/decline"

INVITE = {
    "message_id": "700", "slot_number": 3, "invited_at": "2026-05-20T10:00:00",
    "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
    "scheduled_time": "05/20 20:00", "scheduled_datetime": "2026-05-20T20:00:00+09:00",
    "leader_id": "111", "min_level": 1700, "status": "recruiting",
}

QUALIFYING = [{"name": "발키리", "class": "홀리나이트", "level": 1710.0}]


def test_invites_page_requires_login(client):
    resp = client.get("/invites")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_invites_page_shows_empty_state(client):
    with respx.mock:
        log_in(client)
        respx.get(MY_INVITES_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/invites")

    assert resp.status_code == 200
    assert "받은 초대가 없습니다" in resp.text


def test_invites_page_shows_pending_invite_with_accept_form(client):
    with respx.mock:
        log_in(client)
        respx.get(MY_INVITES_URL).mock(return_value=httpx.Response(200, json=[INVITE]))
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(200, json={"can_join": True, "qualifying": QUALIFYING})
        )
        respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트"]))
        resp = client.get("/invites")

    assert resp.status_code == 200
    body = resp.text
    assert "아르모체(4막)" in body
    assert "3번 슬롯" in body
    assert "발키리" in body
    assert "/invites/700/accept" in body
    assert "/invites/700/decline" in body


def test_invites_page_shows_reason_when_cannot_accept(client):
    with respx.mock:
        log_in(client)
        respx.get(MY_INVITES_URL).mock(return_value=httpx.Response(200, json=[INVITE]))
        respx.get(ELIGIBILITY_URL).mock(
            return_value=httpx.Response(200, json={"can_join": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."})
        )
        resp = client.get("/invites")

    assert resp.status_code == 200
    assert "/api등록" in resp.text
    assert "/invites/700/accept" not in resp.text
    assert "/invites/700/decline" in resp.text  # 거절은 참여 자격과 무관하게 항상 가능


def test_accept_invite_posts_to_bot(client):
    with respx.mock:
        log_in(client)
        accept_route = respx.post(ACCEPT_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(MY_INVITES_URL).mock(return_value=httpx.Response(200, json=[]))

        resp = client.post("/invites/700/accept", data={"character_name": "발키리", "role": "dps"})

    assert resp.status_code == 200
    assert accept_route.called
    import json as _json
    payload = _json.loads(accept_route.calls[0].request.content)
    assert payload == {"discord_id": "111", "character_name": "발키리", "role": "dps"}


def test_accept_invite_shows_error_on_failure(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(ACCEPT_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "이미 참여 중입니다."})
        )
        respx.get(MY_INVITES_URL).mock(return_value=httpx.Response(200, json=[]))

        resp = client.post("/invites/700/accept", data={"character_name": "발키리", "role": "dps"})

    assert resp.status_code == 200
    assert "이미 참여 중입니다" in resp.text


def test_decline_invite_posts_to_bot(client):
    with respx.mock:
        log_in(client, discord_id="111")
        decline_route = respx.post(DECLINE_URL).mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(MY_INVITES_URL).mock(return_value=httpx.Response(200, json=[]))

        resp = client.post("/invites/700/decline")

    assert resp.status_code == 200
    assert decline_route.called
