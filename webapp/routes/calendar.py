"""일정 캘린더 — 월간/주간 보기로 공대 일정을 보여준다. 취소된 파티는 봇 서버에서 완전
삭제되므로 자연히 빠지고, 클리어된 파티(status=disbanded)는 행이 남아있어 그대로 보인다.
칸은 그날 일정 개수에 맞춰 늘어나며(관리자 앱과 동일), 개수를 잘라서 숨기지 않는다."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request

from webapp import config
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()

KST = timezone(timedelta(hours=9))

STATUS_LABELS = {
    "recruiting": "모집중",
    "full": "파티완성",
    "closed": "마감",
    "disbanded": "클리어",
}

# Python datetime.weekday(): 월=0, 화=1, 수=2, 목=3, 금=4, 토=5, 일=6
_WEEKDAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


def _weekday_labels(start_weekday: int) -> list[dict]:
    """start_weekday(월=0...일=6)부터 7일치 요일 헤더 라벨. 일/토에는 강조 클래스를 붙인다."""
    labels = []
    for i in range(7):
        wd = (start_weekday + i) % 7
        css_class = "sun" if wd == 6 else ("sat" if wd == 5 else "")
        labels.append({"label": _WEEKDAY_NAMES[wd], "css_class": css_class})
    return labels


def _month_bounds(year: int, month: int) -> tuple[datetime, datetime]:
    first = datetime(year, month, 1, tzinfo=KST)
    if month == 12:
        next_first = datetime(year + 1, 1, 1, tzinfo=KST)
    else:
        next_first = datetime(year, month + 1, 1, tzinfo=KST)
    return first, next_first


def _build_weeks(year: int, month: int) -> list[list[int]]:
    """일요일 시작 주 단위 그리드. 이번 달에 속하지 않는 칸은 0."""
    first, _ = _month_bounds(year, month)
    days_in_month = (_month_bounds(year, month)[1] - first).days
    # Python weekday(): 월=0 ... 일=6 → 일요일 시작 그리드용으로 변환 (일=0 ... 토=6)
    lead_blanks = (first.weekday() + 1) % 7

    days = list(range(1, days_in_month + 1))
    cells = [0] * lead_blanks + days
    while len(cells) % 7 != 0:
        cells.append(0)

    return [cells[i : i + 7] for i in range(0, len(cells), 7)]


def _week_start_of(dt: datetime) -> datetime:
    """dt가 속한 주의 수요일(00:00) — 로스트아크 주간 레이드 리셋(수요일)과 같은
    기준으로 "이번 주"를 정의한다. bot.database.manager.get_week_key()가 쓰는
    수요일 기준과 동일하게 맞춰서, 길드원이 인지하는 "이번 주"와 어긋나지 않게 한다."""
    days_since_wed = (dt.weekday() - 2) % 7
    return (dt - timedelta(days=days_since_wed)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )


def _make_party_entry(p: dict, dt: datetime) -> dict:
    return {
        **p,
        "status_label": STATUS_LABELS.get(p["status"], p["status"]),
        "time_label": dt.strftime("%H:%M"),
        "is_active": p["status"] != "disbanded",
    }


@router.get("/calendar")
async def calendar_view(
    request: Request,
    view: str = "month",
    year: int | None = None,
    month: int | None = None,
    week_start: str | None = None,
    user: dict = Depends(get_current_user),
):
    now = datetime.now(KST)
    if view not in ("month", "week"):
        view = "month"

    if view == "week":
        try:
            ref = datetime.fromisoformat(week_start).replace(tzinfo=KST) if week_start else now
        except ValueError:
            ref = now
        w_start = _week_start_of(ref)
        w_end = w_start + timedelta(days=7)

        parties = await bot_client.get_calendar_parties(
            config.DISCORD_GUILD_ID,
            w_start.strftime("%Y-%m-%dT%H:%M:%S"),
            w_end.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        parties_by_date: dict[str, list[dict]] = {}
        for p in parties:
            dt = datetime.fromisoformat(p["scheduled_datetime"])
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=KST)
            key = dt.strftime("%Y-%m-%d")
            parties_by_date.setdefault(key, []).append(_make_party_entry(p, dt))

        today_key = now.strftime("%Y-%m-%d")
        week_days = []
        for i in range(7):
            d = w_start + timedelta(days=i)
            key = d.strftime("%Y-%m-%d")
            week_days.append(
                {
                    "date": key,
                    "day": d.day,
                    "month": d.month,
                    "is_today": key == today_key,
                    "parties": parties_by_date.get(key, []),
                }
            )

        w_last = w_end - timedelta(days=1)
        week_label = (
            f"{w_start.year}년 {w_start.month}월 {w_start.day}일 – "
            f"{w_last.month}월 {w_last.day}일"
        )

        return templates.TemplateResponse(
            request,
            "calendar.html",
            {
                "user": user,
                "active": "calendar",
                "view": "week",
                "weekday_labels": _weekday_labels(2),  # 수요일 시작
                "week_days": week_days,
                "week_label": week_label,
                "prev_week_start": (w_start - timedelta(days=7)).strftime("%Y-%m-%d"),
                "next_week_start": (w_start + timedelta(days=7)).strftime("%Y-%m-%d"),
            },
        )

    # ── 월간 보기(기본) ──────────────────────────────────
    y = year or now.year
    m = month or now.month
    if m < 1 or m > 12:
        y, m = now.year, now.month

    first, next_first = _month_bounds(y, m)
    parties = await bot_client.get_calendar_parties(
        config.DISCORD_GUILD_ID,
        first.strftime("%Y-%m-%dT%H:%M:%S"),
        next_first.strftime("%Y-%m-%dT%H:%M:%S"),
    )

    parties_by_day: dict[int, list[dict]] = {}
    for p in parties:
        dt = datetime.fromisoformat(p["scheduled_datetime"])
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        parties_by_day.setdefault(dt.day, []).append(_make_party_entry(p, dt))

    prev_last = first - timedelta(days=1)
    today = now.date()

    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "user": user,
            "active": "calendar",
            "view": "month",
            "weekday_labels": _weekday_labels(6),  # 일요일 시작
            "year": y,
            "month": m,
            "weeks": _build_weeks(y, m),
            "parties_by_day": parties_by_day,
            "today_day": today.day if (today.year, today.month) == (y, m) else None,
            "prev_year": prev_last.year,
            "prev_month": prev_last.month,
            "next_year": next_first.year,
            "next_month": next_first.month,
        },
    )
