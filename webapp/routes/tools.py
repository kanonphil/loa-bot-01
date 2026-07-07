"""부가 도구 — 경매 분배금 계산기 등 (외부 API/DB 의존 없는 순수 계산 페이지)."""
from fastapi import APIRouter, Depends, Request

from webapp.auth.dependencies import get_current_user
from webapp.templating import templates

router = APIRouter()


@router.get("/tools/auction-calculator")
async def auction_calculator(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(
        request, "auction_calculator.html", {"user": user, "active": "auction_calculator"}
    )
