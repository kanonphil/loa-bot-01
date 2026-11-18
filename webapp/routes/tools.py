"""부가 도구 — 경매 분배금 계산기 등. 계산은 브라우저에서 하고, 시세는 봇이 모아 둔 값을 불러와 채울 뿐이다."""
from fastapi import APIRouter, Depends, Request

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_exp
from webapp.templating import templates
from webapp.utils import time_ago

router = APIRouter()


def _price_items(prices: dict | None) -> list[dict]:
    """시세 응답에서 계산기에 쓸 수 있는 항목만(이름·현재가가 있는 것). 봇이 안 주거나 비었으면 빈 목록."""
    if not prices or prices.get("available") is False:
        return []
    items = []
    for raw in prices.get("items") or []:
        try:
            name, current = str(raw["name"]), int(raw["current"])
        except (KeyError, TypeError, ValueError):
            continue
        if not name or current <= 0:
            continue
        change = raw.get("change_pct")
        items.append({"name": name, "current": current, "change_pct": change if isinstance(change, (int, float)) else None})
    return items


@router.get("/tools/auction-calculator")
async def auction_calculator(request: Request, user: dict = Depends(get_current_user)):
    prices = await bot_exp.get_loa_prices()
    return templates.TemplateResponse(
        request,
        "auction_calculator.html",
        {
            "user": user,
            "active": "auction_calculator",
            "price_items": _price_items(prices),
            "prices_ago": time_ago((prices or {}).get("fetched_at")),
        },
    )
