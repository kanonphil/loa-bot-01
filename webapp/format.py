"""화면에 그대로 뿌릴 표시 문자열을 만드는 순수 함수들.

공대 목록·메인·캘린더가 같은 일정을 서로 다른 문장으로 보여주던 걸 한 곳으로 모은다.
템플릿에서 날짜 계산을 하지 않기 위한 것이라 datetime을 인자로 받을 수 있게 해서
테스트에서 "지금"을 고정할 수 있다.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# 이 시간 안으로 다가온 일정은 "임박"으로 본다(경고색).
URGENT_HOURS = 6


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    return dt.replace(tzinfo=KST) if dt.tzinfo is None else dt


def relative_days(target: datetime, now: datetime) -> str:
    """오늘/내일/모레 — 그 외는 월/일(요일)."""
    delta_days = (target.date() - now.date()).days
    if delta_days == 0:
        return "오늘"
    if delta_days == 1:
        return "내일"
    if delta_days == 2:
        return "모레"
    if delta_days == -1:
        return "어제"
    return f"{target.month}/{target.day}({_WEEKDAYS[target.weekday()]})"


def countdown(target: datetime, now: datetime) -> str:
    """남은 시간을 한 덩어리로 — '3시간 뒤', '25분 뒤', '2일 뒤'."""
    delta = target - now
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "시작함"
    if seconds < 60:
        return "곧 시작"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}분 뒤"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}시간 뒤"
    return f"{hours // 24}일 뒤"


def schedule_view(
    scheduled_datetime: str | None,
    fallback: str | None = None,
    now: datetime | None = None,
) -> dict:
    """공대 일정 한 건을 화면 표시용으로 변환.

    when       — '오늘 21:00'처럼 사람이 쓰는 말
    countdown  — '3시간 뒤' (지난 일정이면 None)
    tone       — 'warn'(임박) / 'past'(지남) / '' (그 외)
    """
    now = now or datetime.now(KST)
    target = _parse(scheduled_datetime)
    if target is None:
        return {"when": fallback or "일정 미정", "countdown": None, "tone": "", "is_past": False}

    when = f"{relative_days(target, now)} {target.strftime('%H:%M')}"
    if target < now:
        return {"when": when, "countdown": None, "tone": "past", "is_past": True}

    remaining = countdown(target, now)
    urgent = target - now <= timedelta(hours=URGENT_HOURS)
    return {
        "when": when,
        "countdown": remaining,
        "tone": "warn" if urgent else "",
        "is_past": False,
    }


def next_reset(now: datetime | None = None) -> datetime:
    """다음 주간 리셋 시각 — 매주 수요일 06:00 KST (봇의 get_week_key와 같은 기준)."""
    now = now or datetime.now(KST)
    days_until_wed = (2 - now.weekday()) % 7
    reset = (now + timedelta(days=days_until_wed)).replace(
        hour=6, minute=0, second=0, microsecond=0
    )
    if reset <= now:
        reset += timedelta(days=7)
    return reset


def reset_view(now: datetime | None = None) -> dict:
    """레이드 초기화까지 남은 시간. 하루 안으로 들어오면 경고색."""
    now = now or datetime.now(KST)
    reset = next_reset(now)
    remaining = reset - now
    return {
        "when": f"{relative_days(reset, now)} 06:00",
        "countdown": countdown(reset, now),
        "tone": "warn" if remaining <= timedelta(days=1) else "",
    }


def party_view(party: dict, now: datetime | None = None) -> dict:
    """공대 카드가 필요로 하는 표시 정보를 한 번에 붙여준다."""
    filled = len(party.get("slots") or [])
    total = party.get("total_slots") or 0
    status = party.get("status")
    if status == "recruiting":
        tone, status_label = ("accent", "모집중")
    elif status == "full":
        tone, status_label = ("ok", "파티완성")
    else:
        tone, status_label = ("", "마감")
    return {
        **party,
        "schedule": schedule_view(party.get("scheduled_datetime"), party.get("scheduled_time"), now),
        "filled": filled,
        "pct": round(filled / total * 100) if total else 0,
        "is_full": bool(total) and filled >= total,
        "status_tone": tone,
        "status_label": status_label,
    }
