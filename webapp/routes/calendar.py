"""일정 캘린더 — 월별로 공대 일정을 보여준다. 취소된 파티는 봇 서버에서 완전
삭제되므로 자연히 빠지고, 클리어된 파티(status=disbanded)는 행이 남아있어 그대로 보인다."""
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


@router.get("/calendar")
async def calendar_view(
    request: Request,
    year: int | None = None,
    month: int | None = None,
    user: dict = Depends(get_current_user),
):
    now = datetime.now(KST)
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
        parties_by_day.setdefault(dt.day, []).append(
            {**p, "status_label": STATUS_LABELS.get(p["status"], p["status"])}
        )

    prev_last = first - timedelta(days=1)
    today = now.date()

    return templates.TemplateResponse(
        request,
        "calendar.html",
        {
            "user": user,
            "active": "calendar",
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
