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
    """dt가 속한 주의 일요일(00:00) — 월 그리드와 동일하게 일요일 시작 기준."""
    days_since_sunday = (dt.weekday() + 1) % 7
    return (dt - timedelta(days=days_since_sunday)).replace(
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
                "week_days": week_days,
                "week_label": week_label,
                "prev_week_start": (w_start - timedelta(days=7)).strftime("%Y-%m-%d"),
                "next_week_start": (w_start + timedelta(days=7)).strftime("%Y-%m-%d"),
                # "월간" 탭으로 전환할 때 이 주가 속한 달로 이동시키기 위함
                "month_toggle_year": w_start.year,
                "month_toggle_month": w_start.month,
                # "주간" 탭 자체 링크(현재 주 유지)에도 필요
                "current_week_start": w_start.strftime("%Y-%m-%d"),
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
            "year": y,
            "month": m,
            "weeks": _build_weeks(y, m),
            "parties_by_day": parties_by_day,
            "today_day": today.day if (today.year, today.month) == (y, m) else None,
            "prev_year": prev_last.year,
            "prev_month": prev_last.month,
            "next_year": next_first.year,
            "next_month": next_first.month,
            # "주간" 탭으로 전환할 때 이 달의 1일이 속한 주로 이동시키기 위함
            "week_toggle_start": first.strftime("%Y-%m-%d"),
        },
    )
