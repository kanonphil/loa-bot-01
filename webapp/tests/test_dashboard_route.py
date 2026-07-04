"""메인 대시보드 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

RAIDS_URL = "http://bot-server.internal/api/internal/raids"
CATEGORIES_URL = "http://bot-server.internal/api/internal/raid-categories"
COMPLETIONS_URL = "http://bot-server.internal/api/internal/completions"
CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters"
PARTIES_URL = "http://bot-server.internal/api/internal/parties"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스",
        "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}
CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": 0}]
CHARACTERS = [{"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0}]

PARTY_RECRUITING = {
    "message_id": "p1", "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
    "scheduled_time": "05/20 20:00", "scheduled_datetime": "2026-05-20T20:00:00+09:00",
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": None,
    "slots": [{"slot_number": 1, "discord_id": "222", "character_name": "워로드",
               "character_class": "워로드", "role": "dps"}],
}
PARTY_CLOSED = {**PARTY_RECRUITING, "message_id": "p2", "status": "closed"}


def _mock_common(completions=None, parties=None):
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
    respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=CHARACTERS))
    respx.get(COMPLETIONS_URL).mock(
        return_value=httpx.Response(200, json={"week_key": "2026-01-07", "completions": completions or []})
    )
    respx.get(PARTIES_URL).mock(return_value=httpx.Response(200, json=parties or []))


def test_dashboard_requires_login(client):
    resp = client.get("/main")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_dashboard_shows_progress_and_characters(client):
    with respx.mock:
        log_in(client)
        _mock_common(completions=["아르모체(4막)_노말"], parties=[PARTY_RECRUITING, PARTY_CLOSED])
        resp = client.get("/main")

    assert resp.status_code == 200
    body = resp.text
    assert "발키리" in body
    assert "홀리나이트" in body
    assert "1/1" in body  # 원정대 전체 진행률


def test_dashboard_only_shows_recruiting_parties(client):
    with respx.mock:
        log_in(client)
        _mock_common(parties=[PARTY_RECRUITING, PARTY_CLOSED])
        resp = client.get("/main")

    assert resp.status_code == 200
    assert resp.text.count("아르모체(4막) 노말") == 1  # 모집중인 p1만, 마감된 p2는 제외


def test_dashboard_no_characters_shows_notice(client):
    with respx.mock:
        log_in(client)
        respx.get(CHARACTERS_URL).mock(return_value=httpx.Response(200, json=[]))
        respx.get(PARTIES_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/main")

    assert resp.status_code == 200
    assert "/api등록" in resp.text


def test_dashboard_no_recruiting_parties_shows_notice(client):
    with respx.mock:
        log_in(client)
        _mock_common(parties=[])
        resp = client.get("/main")

    assert resp.status_code == 200
    assert "모집 중인 공대가 없습니다" in resp.text
