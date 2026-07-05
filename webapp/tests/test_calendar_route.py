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
