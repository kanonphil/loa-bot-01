"""webapp/format.py — 화면 표시 문자열 생성 규칙."""
from datetime import datetime, timedelta

from webapp.format import KST, countdown, next_reset, party_view, relative_days, reset_view, schedule_view

NOW = datetime(2026, 8, 5, 14, 0, tzinfo=KST)  # 수요일 14:00


def _iso(**delta):
    return (NOW + timedelta(**delta)).isoformat()


def test_relative_days_uses_everyday_words():
    assert relative_days(NOW, NOW) == "오늘"
    assert relative_days(NOW + timedelta(days=1), NOW) == "내일"
    assert relative_days(NOW + timedelta(days=2), NOW) == "모레"
    assert relative_days(NOW - timedelta(days=1), NOW) == "어제"


def test_relative_days_falls_back_to_date():
    assert relative_days(NOW + timedelta(days=5), NOW) == "8/10(월)"


def test_countdown_units():
    assert countdown(NOW + timedelta(seconds=30), NOW) == "곧 시작"
    assert countdown(NOW + timedelta(minutes=25), NOW) == "25분 뒤"
    assert countdown(NOW + timedelta(hours=3), NOW) == "3시간 뒤"
    assert countdown(NOW + timedelta(days=2), NOW) == "2일 뒤"
    assert countdown(NOW - timedelta(minutes=1), NOW) == "시작함"


def test_schedule_view_marks_urgent():
    view = schedule_view(_iso(hours=3), now=NOW)
    assert view["when"] == "오늘 17:00"
    assert view["countdown"] == "3시간 뒤"
    assert view["tone"] == "warn"


def test_schedule_view_not_urgent_when_far():
    view = schedule_view(_iso(days=2), now=NOW)
    assert view["tone"] == ""
    assert view["countdown"] == "2일 뒤"


def test_schedule_view_past():
    view = schedule_view(_iso(hours=-2), now=NOW)
    assert view["is_past"] is True
    assert view["countdown"] is None
    assert view["tone"] == "past"


def test_schedule_view_falls_back_when_unparsable():
    view = schedule_view(None, fallback="05/20 20:00", now=NOW)
    assert view["when"] == "05/20 20:00"
    assert schedule_view("나중에", now=NOW)["when"] == "일정 미정"


def test_schedule_view_treats_naive_datetime_as_kst():
    """봇이 저장하는 scheduled_datetime은 타임존 없는 KST 문자열이다."""
    view = schedule_view("2026-08-05T17:00:00", now=NOW)
    assert view["when"] == "오늘 17:00"


# ── 주간 리셋 ────────────────────────────────────────────

def test_next_reset_is_wednesday_six_am():
    reset = next_reset(NOW)  # 수요일 14시 → 다음 주 수요일 06시
    assert reset.weekday() == 2
    assert (reset.hour, reset.day) == (6, 12)


def test_next_reset_same_day_before_six():
    early = datetime(2026, 8, 5, 3, 0, tzinfo=KST)
    assert next_reset(early).day == 5


def test_reset_view_warns_within_a_day():
    tuesday_evening = datetime(2026, 8, 11, 20, 0, tzinfo=KST)
    assert reset_view(tuesday_evening)["tone"] == "warn"
    assert reset_view(NOW)["tone"] == ""


# ── 공대 카드용 파생값 ───────────────────────────────────

def _party(**over):
    return {
        "message_id": "p1", "raid_name": "종막", "difficulty": "하드",
        "scheduled_datetime": _iso(hours=3), "scheduled_time": "곧",
        "total_slots": 8, "status": "recruiting",
        "slots": [{"discord_id": "1", "character_name": "발키리", "character_class": "홀리나이트"}],
        **over,
    }


def test_party_view_fills_display_fields():
    view = party_view(_party(), now=NOW)
    assert view["filled"] == 1
    assert view["pct"] == 12  # 1/8 = 12.5 → round()는 짝수로 내린다
    assert view["is_full"] is False
    assert (view["status_label"], view["status_tone"]) == ("모집중", "accent")


def test_party_view_full():
    slots = [{"discord_id": str(i), "character_name": "캐릭", "character_class": "직업"} for i in range(8)]
    view = party_view(_party(slots=slots, status="full"), now=NOW)
    assert view["is_full"] is True
    assert view["pct"] == 100
    assert (view["status_label"], view["status_tone"]) == ("파티완성", "warn")


def test_party_view_closed():
    view = party_view(_party(status="closed"), now=NOW)
    assert view["status_label"] == "마감"
    assert view["status_tone"] == ""


def test_party_view_handles_zero_total():
    view = party_view(_party(total_slots=0), now=NOW)
    assert view["pct"] == 0
    assert view["is_full"] is False
