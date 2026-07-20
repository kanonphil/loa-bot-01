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

    assert "/calendar?view=month&year=2026&month=4" in resp.text
    assert "/calendar?view=month&year=2026&month=6" in resp.text


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


def test_calendar_shows_all_parties_without_truncation(client, monkeypatch):
    """관리자 앱처럼 칸이 일정 개수에 맞춰 늘어나야 하므로, 한 칸에 일정이 몰려도
    자르지 않고 전부 보여줘야 한다(이전에는 최대 3개 + "+N개 더"로 잘랐음)."""
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

    assert resp.text.count("calendar-party-name") == 4
    assert "calendar-party-more" not in resp.text


def test_calendar_week_view_shows_current_week_by_default(client, monkeypatch):
    """view=week 파라미터만 주면(week_start 없이) "오늘"이 속한 주가 기본으로 보여야 한다.
    주는 로스트아크 레이드 리셋과 동일하게 수요일 시작 — 2026-05-15(금)이 속한 주는
    2026-05-13(수)~05-19(화)라 그 안의 p2(5/15)만 포함되고, 그 전 주인 p1(5/10)은
    빠져야 한다(전에는 일요일 시작이라 둘 다 같은 주에 잡혀 헷갈렸다)."""
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=PARTIES))
        resp = client.get("/calendar", params={"view": "week"})

    assert resp.status_code == 200
    assert "5월 13일" in resp.text
    assert "아르모체(4막) 노말" in resp.text
    assert "카멘 노말" not in resp.text  # 5/10은 이전 주(수요일 기준)라 이 뷰엔 없어야 함


def test_calendar_week_view_highlights_today(client, monkeypatch):
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/calendar", params={"view": "week"})

    assert '<div class="calendar-cell today">' in resp.text


def test_calendar_week_navigation_stays_within_seven_days(client, monkeypatch):
    """2026-05-15(금)이 속한 수요일 시작 주는 5/13~5/19 — 이전/다음 주 링크는
    각각 7일 전인 5/6, 7일 후인 5/20이어야 한다."""
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/calendar", params={"view": "week"})

    assert "week_start=2026-05-06" in resp.text
    assert "week_start=2026-05-20" in resp.text


def test_calendar_toggle_from_other_month_always_targets_today(client, monkeypatch):
    """회귀 테스트: 6월을 보고 있다가 "주간"을 누르면 6월 기준 주가 아니라 오늘(5/15)이
    속한 주(5/13~5/19)로 가야 한다 — 이전에는 링크에 현재 보고 있던 달의 1일이 속한
    주가 박혀 있어서, 주간↔월간을 오갈 때마다 날짜가 계속 밀렸다."""
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[]))
        june_resp = client.get("/calendar", params={"year": 2026, "month": 6})
        assert 'href="/calendar?view=week"' in june_resp.text

        week_resp = client.get("/calendar", params={"view": "week"})

    assert "5월 13일" in week_resp.text  # 6월이 아니라 오늘이 속한 주


def test_calendar_toggle_from_other_week_always_targets_today(client, monkeypatch):
    """회귀 테스트: 6월 첫째 주를 보고 있다가 "월간"을 누르면 그 주가 속한 6월이 아니라
    오늘(5/15)이 속한 5월로 가야 한다."""
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[]))
        other_week_resp = client.get(
            "/calendar", params={"view": "week", "week_start": "2026-06-03"}
        )
        assert 'href="/calendar?view=month"' in other_week_resp.text

        month_resp = client.get("/calendar", params={"view": "month"})

    assert "2026년 5월" in month_resp.text  # 6월이 아니라 오늘이 속한 달


def test_calendar_view_toggle_links_present_in_both_views(client, monkeypatch):
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=[]))
        month_resp = client.get("/calendar")
        week_resp = client.get("/calendar", params={"view": "week"})

    assert 'class="calendar-view-btn is-active">월간' in month_resp.text
    assert 'href="/calendar?view=week' in month_resp.text
    assert 'class="calendar-view-btn is-active">주간' in week_resp.text
    assert 'href="/calendar?view=month' in week_resp.text


def test_calendar_party_names_are_wrapped_for_marquee(client, monkeypatch):
    """레이드명 슬라이드(마퀴)를 위해 이름이 .marquee-inner로 감싸져 있고,
    잘림 여부를 측정해 애니메이션을 붙이는 스크립트가 포함돼야 한다."""
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=PARTIES))
        resp = client.get("/calendar")

    assert '<span class="marquee-inner">카멘 노말</span>' in resp.text
    assert "/static/calendar-marquee.js" in resp.text


def test_calendar_week_shows_all_parties_without_truncation(client, monkeypatch):
    many_parties = [
        {
            "message_id": f"day-{i}", "raid_name": f"레이드{i}", "difficulty": "노말", "proficiency": "숙련",
            "scheduled_time": "2026/05/15 오후 9시 정각", "scheduled_datetime": "2026-05-15T21:00:00+09:00",
            "status": "recruiting", "total_slots": 8, "slot_count": 1,
        }
        for i in range(5)
    ]
    _freeze_today(monkeypatch)
    with respx.mock:
        log_in(client)
        respx.get(CALENDAR_URL).mock(return_value=httpx.Response(200, json=many_parties))
        resp = client.get("/calendar", params={"view": "week"})

    assert resp.text.count("calendar-party-name") == 5
