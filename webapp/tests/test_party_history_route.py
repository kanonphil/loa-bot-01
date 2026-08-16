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
            return_value=httpx.Response(
                200, json={"entries": ENTRIES, "has_more": False, "total_count": 2}
            )
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
            return_value=httpx.Response(
                200, json={"entries": [], "has_more": False, "total_count": 0}
            )
        )
        resp = client.get("/parties/history")

    assert resp.status_code == 200
    assert "참여 이력이 없습니다" in resp.text


def test_history_page_shows_next_button_and_forwards_offset(client):
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(
                200, json={"entries": ENTRIES, "has_more": True, "total_count": 15}
            )
        )
        resp = client.get("/parties/history")

    assert 'href="/parties/history?page=2"' in resp.text
    assert route.calls[0].request.url.params["offset"] == "0"
    assert route.calls[0].request.url.params["limit"] == "10"


def test_history_page_2_forwards_offset_and_shows_prev(client):
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(
                200, json={"entries": ENTRIES, "has_more": False, "total_count": 15}
            )
        )
        resp = client.get("/parties/history?page=2")

    assert 'href="/parties/history?page=1"' in resp.text
    assert route.calls[0].request.url.params["offset"] == "10"


def test_history_page_shows_at_most_5_numbered_pages_centered_on_current(client):
    """전체 10페이지 중 5페이지에 있으면, 번호는 3~7(5개)만 보이고 양 끝(1, 10)은
    말줄임(…)으로 따로 붙어야 한다 — 페이지가 많아져도 번호 목록이 한없이 안 길어지게."""
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(
                200, json={"entries": ENTRIES, "has_more": True, "total_count": 100}
            )
        )
        resp = client.get("/parties/history?page=5")

    body = resp.text
    for n in (3, 4, 5, 6, 7):
        assert f'href="/parties/history?page={n}"' in body
    assert 'href="/parties/history?page=2"' not in body
    assert 'href="/parties/history?page=8"' not in body
    assert 'href="/parties/history?page=1"' in body  # 맨 앞 페이지는 항상 따로 노출
    assert 'href="/parties/history?page=10"' in body  # 맨 뒤 페이지도 항상 따로 노출
    assert body.count("&hellip;") == 2  # 앞뒤 양쪽에 말줄임


def test_history_page_1_shows_1_to_5_without_leading_ellipsis(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(HISTORY_URL).mock(
            return_value=httpx.Response(
                200, json={"entries": ENTRIES, "has_more": True, "total_count": 100}
            )
        )
        resp = client.get("/parties/history")

    body = resp.text
    for n in (1, 2, 3, 4, 5):
        assert f'href="/parties/history?page={n}"' in body
    assert 'href="/parties/history?page=6"' not in body
    assert body.count("&hellip;") == 1  # 뒤쪽에만 말줄임(맨 앞 페이지라 앞쪽엔 없음)
