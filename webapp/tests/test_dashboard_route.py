"""메인 대시보드 라우트 검증 — 봇 서버는 respx로 모킹.

진행률 계산 자체는 봇의 /api/internal/raid-progress로 옮겼다(캐릭터마다 왕복하던
N+1 호출 제거). "레이드 단위로 센다", "레이드 체크 선택을 존중한다" 같은 규칙은
tests/test_raid_progress_endpoint.py가 검증한다. 여기서는 화면 구성만 본다 —
급한 것(내 공대) → 내 진행 → 기회(들어갈 만한 공대) 순.
"""
import httpx
import respx

from webapp.tests.conftest import log_in

CHARACTERS_URL = "http://bot-server.internal/api/internal/user-characters"
PARTIES_URL = "http://bot-server.internal/api/internal/parties"
PROGRESS_URL = "http://bot-server.internal/api/internal/raid-progress"

ME = "111"  # conftest.log_in이 심는 discord_id

CHARACTERS = [{"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0}]

PROGRESS = {
    "week_key": "2026-01-07",
    "done": 1,
    "total": 2,
    "characters": [
        {"character_name": "발키리", "character_class": "홀리나이트",
         "item_level": 1720.0, "done_count": 1, "total_slots": 2, "remaining": 1},
    ],
}

# 일정은 항상 미래여야 "임박/기회"에 잡힌다 — 고정 날짜를 쓰면 시간이 지나 테스트가 썩는다.
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
SOON = (datetime.now(KST) + timedelta(hours=3)).isoformat()
LATER = (datetime.now(KST) + timedelta(days=2)).isoformat()
PAST = (datetime.now(KST) - timedelta(days=1)).isoformat()

PARTY_MINE = {
    "message_id": "p1", "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
    "leader_id": ME, "scheduled_time": "곧", "scheduled_datetime": SOON,
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": None,
    "slots": [{"slot_number": 1, "discord_id": ME, "character_name": "발키리",
               "character_class": "홀리나이트", "role": "support"}],
}
PARTY_OPPORTUNITY = {
    "message_id": "p2", "raid_name": "종막", "difficulty": "하드", "proficiency": "트라이",
    "leader_id": "999", "scheduled_time": "나중", "scheduled_datetime": LATER,
    "total_slots": 8, "min_level": 1710, "status": "recruiting", "memo": None,
    "slots": [{"slot_number": 1, "discord_id": "222", "character_name": "워로드",
               "character_class": "워로드", "role": "dps"}],
}
PARTY_TOO_HIGH = {**PARTY_OPPORTUNITY, "message_id": "p3", "raid_name": "미래레이드", "min_level": 9999}
PARTY_PAST = {**PARTY_OPPORTUNITY, "message_id": "p4", "raid_name": "지난레이드", "scheduled_datetime": PAST}


def _mock(parties=None, progress=None, characters=None):
    respx.get(CHARACTERS_URL).mock(
        return_value=httpx.Response(200, json=CHARACTERS if characters is None else characters)
    )
    respx.get(PARTIES_URL).mock(return_value=httpx.Response(200, json=parties or []))
    respx.get(PROGRESS_URL).mock(return_value=httpx.Response(200, json=progress or PROGRESS))


def test_dashboard_requires_login(client):
    resp = client.get("/main")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_dashboard_shows_progress(client):
    with respx.mock:
        log_in(client)
        _mock()
        resp = client.get("/main")

    assert resp.status_code == 200
    assert "1/2" in resp.text
    assert "발키리" in resp.text  # 남은 레이드가 있는 캐릭터를 칩으로 보여준다


def test_my_party_appears_above_opportunities(client):
    """내가 속한 임박 공대가 '들어갈 만한 공대'보다 위에 온다."""
    with respx.mock:
        log_in(client)
        _mock(parties=[PARTY_OPPORTUNITY, PARTY_MINE])
        resp = client.get("/main")

    body = resp.text
    assert body.index("아르모체(4막)") < body.index("종막")
    assert "내가 파티장" in body


def test_opportunity_excludes_parties_i_joined(client):
    with respx.mock:
        log_in(client)
        _mock(parties=[PARTY_MINE])
        resp = client.get("/main")

    assert "지금 들어갈 수 있는 모집이 없습니다" in resp.text


def test_opportunity_excludes_too_high_level(client):
    with respx.mock:
        log_in(client)
        _mock(parties=[PARTY_TOO_HIGH])
        resp = client.get("/main")

    assert "미래레이드" not in resp.text


def test_past_parties_are_dropped(client):
    with respx.mock:
        log_in(client)
        _mock(parties=[PARTY_PAST])
        resp = client.get("/main")

    assert "지난레이드" not in resp.text


def test_dashboard_no_characters_shows_next_action(client):
    """빈 상태는 '없다'로 끝내지 않고 다음 행동을 준다."""
    with respx.mock:
        log_in(client)
        _mock(characters=[], progress={"week_key": "w", "done": 0, "total": 0, "characters": []})
        resp = client.get("/main")

    assert resp.status_code == 200
    assert "등록된 캐릭터가 없습니다" in resp.text
    assert "/expedition" in resp.text


def test_nav_badges(client):
    with respx.mock:
        log_in(client)
        _mock(parties=[PARTY_MINE, PARTY_OPPORTUNITY])
        resp = client.get("/nav-badges")

    assert resp.status_code == 200
    assert resp.json() == {"parties": 2, "raid_check": 1}


def test_nav_badges_requires_login(client):
    resp = client.get("/nav-badges")
    assert resp.status_code in (302, 307)
