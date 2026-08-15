"""내 공대 이력(/parties/history) 웹 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

HISTORY_URL = "http://bot-server.internal/api/internal/user-party-history"

ENTRIES = [
    {
        "message_id": "p1", "raid_name": "카멘", "difficulty": "노말", "proficiency": "숙련",
        "scheduled_time": "05/20 20:00", "status": "disbanded",
        "character_name": "워로드캐릭", "role": "dps", "created_at": "2026-05-20T10:00:00",
    },
    {
        "message_id": "p2", "raid_name": "아브렐슈드", "difficulty": "하드", "proficiency": "숙련",
        "scheduled_time": "05/10 21:00", "status": "cancelled",
        "character_name": "홀나캐릭", "role": "support", "created_at": "2026-05-10T09:00:00",
    },
]


def test_history_page_shows_entries_with_status_labels(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(200, json={"entries": ENTRIES, "has_more": False})
        )
        resp = client.get("/parties/history")

    assert resp.status_code == 200
    body = resp.text
    assert "카멘" in body
    assert "워로드캐릭" in body
    assert "클리어" in body  # disbanded → 클리어
    assert "취소" in body  # cancelled → 취소
    assert "서포터" in body
    assert "다음" not in body  # has_more=False면 다음 버튼 없음


def test_history_page_requires_login(client):
    resp = client.get("/parties/history")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_history_page_shows_empty_state(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(200, json={"entries": [], "has_more": False})
        )
        resp = client.get("/parties/history")

    assert resp.status_code == 200
    assert "참여 이력이 없습니다" in resp.text


def test_history_page_shows_next_button_and_forwards_offset(client):
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(200, json={"entries": ENTRIES, "has_more": True})
        )
        resp = client.get("/parties/history")

    assert 'href="/parties/history?page=2"' in resp.text
    assert route.calls[0].request.url.params["offset"] == "0"
    assert route.calls[0].request.url.params["limit"] == "10"


def test_history_page_2_forwards_offset_and_shows_prev(client):
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(200, json={"entries": ENTRIES, "has_more": False})
        )
        resp = client.get("/parties/history?page=2")

    assert 'href="/parties/history?page=1"' in resp.text
    assert route.calls[0].request.url.params["offset"] == "10"
