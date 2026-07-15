"""원정대 랭킹 — 전투력 / 아이템레벨 / 주간 클리어 3개 탭.
전체 원정대(모든 길드원의 모든 캐릭터)를 대상으로 하며, 봇 서버가 캐시한 값만 읽어
집계하므로 로스트아크 API를 호출하지 않는다(빠르고 한도 부담 없음)."""
from fastapi import APIRouter, Depends, Request

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()

_METRICS = ("combat_power", "item_level", "weekly_clears")
_METRIC_LABELS = {
    "combat_power": "전투력",
    "item_level": "아이템 레벨",
    "weekly_clears": "주간 클리어",
}


@router.get("/ranking")
async def ranking_page(
    request: Request, metric: str = "combat_power", user: dict = Depends(get_current_user)
):
    if metric not in _METRICS:
        metric = "combat_power"
    data = await bot_client.get_ranking(metric)
    entries = data.get("entries", [])
    for i, e in enumerate(entries):
        e["rank"] = i + 1
    return templates.TemplateResponse(
        request,
        "ranking.html",
        {
            "user": user,
            "active": "ranking",
            "metric": metric,
            "metrics": _METRICS,
            "metric_labels": _METRIC_LABELS,
            "entries": entries,
        },
    )
