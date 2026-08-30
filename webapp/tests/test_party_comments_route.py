"""파티 스레드 댓글(디스코드 ↔ 웹) 웹 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

PARTY_DETAIL_URL = "http://bot-server.internal/api/internal/parties/p1"
COMMENTS_URL = "http://bot-server.internal/api/internal/parties/p1/comments"
RAIDS_URL = "http://bot-server.internal/api/internal/raids"
SUPPORT_CLASSES_URL = "http://bot-server.internal/api/internal/support-classes"
ELIGIBILITY_URL = "http://bot-server.internal/api/internal/parties/p1/eligibility"
WAITLIST_STATUS_URL = "http://bot-server.internal/api/internal/parties/p1/waitlist-status"
INVITABLE_USERS_URL = "http://bot-server.internal/api/internal/parties/p1/invitable-users"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스",
        "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}

PARTY = {
    "message_id": "p1", "channel_id": "555", "guild_id": "test-guild-id", "leader_id": "111",
    "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
    "scheduled_time": "05/20 20:00", "scheduled_datetime": "2026-05-20T20:00:00+09:00",
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": None,
    "slots": [
        {"slot_number": 1, "discord_id": "111", "character_name": "리더캐릭",
         "character_class": "워로드", "role": "dps"},
    ],
}

COMMENTS = [
    {"id": 1, "discord_id": "111", "author_name": "리더캐릭", "content": "필요하면 불러주십쇼", "source": "discord", "created_at": "2026-05-19T19:02:00"},
    {"id": 2, "discord_id": "222", "author_name": "댓글러", "content": "저녁 8시가 낫겠네요", "source": "web", "created_at": "2026-05-19T20:27:00"},
]


def _mock_base(client, discord_id="111", party=None, comments=None):
    log_in(client, discord_id=discord_id)
    respx.get(PARTY_DETAIL_URL).mock(return_value=httpx.Response(200, json=party or PARTY))
    respx.get(COMMENTS_URL).mock(return_value=httpx.Response(200, json=comments if comments is not None else []))
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(SUPPORT_CLASSES_URL).mock(return_value=httpx.Response(200, json=["홀리나이트"]))
    respx.get(INVITABLE_USERS_URL).mock(return_value=httpx.Response(200, json={"success": True, "users": [], "available_slots": []}))


def test_party_detail_shows_comment_list(client):
    with respx.mock:
        _mock_base(client, comments=COMMENTS)
        resp = client.get("/parties/p1")

    body = resp.text
    assert "필요하면 불러주십쇼" in body
    assert "저녁 8시가 낫겠네요" in body
    assert "리더캐릭" in body
    assert "댓글러" in body


def test_party_detail_shows_empty_comment_state(client):
    with respx.mock:
        _mock_base(client, comments=[])
        resp = client.get("/parties/p1")

    assert "아직 댓글이 없습니다" in resp.text


def test_party_detail_shows_comment_form_when_active(client):
    with respx.mock:
        _mock_base(client)
        resp = client.get("/parties/p1")

    assert 'action="/parties/p1/comments"' in resp.text


def test_party_detail_hides_comment_form_when_disbanded(client):
    with respx.mock:
        _mock_base(client, party={**PARTY, "status": "disbanded"})
        resp = client.get("/parties/p1")

    assert 'action="/parties/p1/comments"' not in resp.text


def test_post_comment_calls_bot_with_session_identity(client):
    with respx.mock:
        log_in(client, discord_id="111", username="댓글러")
        comment_route = respx.post(COMMENTS_URL).mock(return_value=httpx.Response(200, json={"success": True, "relayed": True}))

        resp = client.post("/parties/p1/comments", data={"content": "안녕하세요"})

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert comment_route.called
    import json as _json
    payload = _json.loads(comment_route.calls[0].request.content)
    assert payload["discord_id"] == "111"
    assert payload["display_name"] == "댓글러"
    assert payload["content"] == "안녕하세요"
    assert "avatar_url" in payload


def test_post_comment_shows_error_on_failure(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(COMMENTS_URL).mock(
            return_value=httpx.Response(200, json={"success": False, "reason": "이미 종료된 공대라 댓글을 남길 수 없습니다."})
        )
        resp = client.post("/parties/p1/comments", data={"content": "안녕하세요"})

    assert resp.status_code == 303
    assert "join_error=" in resp.headers["location"]


def test_party_detail_shows_delete_button_only_for_own_web_comment(client):
    with respx.mock:
        _mock_base(client, discord_id="222", comments=COMMENTS)
        respx.get(ELIGIBILITY_URL).mock(return_value=httpx.Response(200, json={"can_join": False, "reason": "이미 마감된 공대입니다."}))
        respx.get(WAITLIST_STATUS_URL).mock(return_value=httpx.Response(200, json={"on_waitlist": False}))
        resp = client.get("/parties/p1")

    body = resp.text
    assert 'action="/parties/p1/comments/2/delete"' in body
    assert 'action="/parties/p1/comments/1/delete"' not in body


def test_party_detail_hides_delete_button_for_others_web_comment(client):
    with respx.mock:
        _mock_base(client, discord_id="111", comments=COMMENTS)
        resp = client.get("/parties/p1")

    assert "/comments/2/delete" not in resp.text
    assert "/comments/1/delete" not in resp.text


def test_delete_comment_calls_bot_with_session_identity(client):
    with respx.mock:
        log_in(client, discord_id="222")
        delete_route = respx.post(f"{COMMENTS_URL}/2/delete").mock(
            return_value=httpx.Response(200, json={"success": True})
        )

        resp = client.post("/parties/p1/comments/2/delete")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/parties/p1"
    assert delete_route.called
    import json as _json
    payload = _json.loads(delete_route.calls[0].request.content)
    assert payload["discord_id"] == "222"


def test_delete_comment_shows_error_on_failure(client):
    with respx.mock:
        log_in(client, discord_id="222")
        respx.post(f"{COMMENTS_URL}/2/delete").mock(return_value=httpx.Response(200, json={"success": False}))

        resp = client.post("/parties/p1/comments/2/delete")

    assert resp.status_code == 303
    assert "join_error=" in resp.headers["location"]
