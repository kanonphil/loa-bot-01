"""일정 캘린더 웹 페이지 검증 — 봇 서버는 respx로 모킹, "오늘" 판정은 datetime을 고정해서 검증."""
import datetime as dt_module

import httpx
import respx

import webapp.routes.calendar as calendar_route
from webapp.tests.conftest import log_in

CALENDAR_URL = "http://bot-server.internal/api/internal/parties/calendar"

PARTIES = [
    {
        "message_id": "p1", "raid_name": "카멘", "difficulty": "노말", "proficiency": "숙련",
        "scheduled_time": "05/10 20:00", "scheduled_datetime": "2026-05-10T20:00:00+09:00",
        "status": "recruiting", "total_slots": 8, "slot_count": 3,
    },
    {
        "message_id": "p2", "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
        "scheduled_time": "05/15 21:00", "scheduled_datetime": "2026-05-15T21:00:00+09:00",
        "status": "disbanded", "total_slots": 8, "slot_count": 8,
    },
]


class _FrozenDateTime(dt_module.datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 5, 15, 12, 0, tzinfo=tz)


def _freeze_today(monkeypatch):
    monkeypatch.setattr(calendar_route, "datetime", _FrozenDateTime)


def test_calendar_requires_login(client):
    resp = client.get("/calendar")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_calendar_shows_month_grid_with_parties(client, monkeypatch):
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=PARTIES))
        resp = client.get("/calendar")

    assert resp.status_code == 200
    assert "2026년 5월" in resp.text
    assert "카멘 노말" in resp.text
    assert "아르모체(4막) 노말" in resp.text


def test_calendar_includes_cleared_party_with_label(client, monkeypatch):
    """관리자 앱 캘린더에서는 클리어된(disbanded) 파티가 안 보이던 문제 — 웹 캘린더는 포함하고 라벨도 구분해야 한다."""
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=PARTIES))
        resp = client.get("/calendar")

    assert "클리어" in resp.text
    assert "모집중" in resp.text


def test_calendar_highlights_today(client, monkeypatch):
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=PARTIES))
        resp = client.get("/calendar")

    assert '<div class="calendar-cell today">' in resp.text


def test_calendar_does_not_highlight_today_in_other_month(client, monkeypatch):
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/calendar", params={"year": 2026, "month": 6})

    assert "2026년 6월" in resp.text
    assert '"calendar-cell today"' not in resp.text


def test_calendar_month_navigation_links(client, monkeypatch):
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/calendar")

    assert "/calendar?year=2026&month=4" in resp.text
    assert "/calendar?year=2026&month=6" in resp.text


def test_calendar_time_shown_is_derived_from_datetime_not_scheduled_time_text(client, monkeypatch):
    """scheduled_time은 "2026/07/05 오후 9시 정각"처럼 사람이 읽는 문자열이라 공백 기준으로
    자르면 "정각"/"30분" 같은 조각이 시간처럼 잘못 표시됐던 버그 — scheduled_datetime에서
    직접 시:분을 뽑아야 한다."""
    party = {
        "message_id": "p3", "raid_name": "세르카", "difficulty": "하드", "proficiency": "숙련",
        "scheduled_time": "2026/05/15 오후 9시 정각", "scheduled_datetime": "2026-05-15T21:00:00+09:00",
        "status": "recruiting", "total_slots": 8, "slot_count": 1,
    }
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[party]))
        resp = client.get("/calendar")

    assert '<span class="calendar-party-time">21:00</span>' in resp.text


def test_calendar_active_party_links_to_detail_page(client, monkeypatch):
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=PARTIES))
        resp = client.get("/calendar")

    assert 'href="/parties/p1"' in resp.text


def test_calendar_cleared_party_is_not_clickable(client, monkeypatch):
    """클리어된(disbanded) 파티는 이미 종료된 이력이라 모집글로 이동하는 링크를 만들지 않는다."""
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=PARTIES))
        resp = client.get("/calendar")

    assert 'href="/parties/p2"' not in resp.text


def test_calendar_caps_visible_parties_per_day_and_shows_more_count(client, monkeypatch):
    """한 칸에 일정이 몰려도 칸 높이가 안 밀리도록 최대 3개까지만 보여주고 나머지는 "+N개 더"로 표시."""
    many_parties = [
        {
            "message_id": f"day-{i}", "raid_name": f"레이드{i}", "difficulty": "노말", "proficiency": "숙련",
            "scheduled_time": "2026/05/15 오후 9시 정각", "scheduled_datetime": "2026-05-15T21:00:00+09:00",
            "status": "recruiting", "total_slots": 8, "slot_count": 1,
        }
        for i in range(4)
    ]
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=many_parties))
        resp = client.get("/calendar")

    assert resp.text.count("calendar-party-name") == 3
    assert "+1개 더" in resp.text
