"""캐릭터 상세 정보 — 스킬/트라이포드/룬, 아크패시브, 장신구 품질/연마, 보석."""
from fastapi import APIRouter, Depends, Request

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()


@router.get("/characters/{character_name}")
async def character_detail(
    request: Request, character_name: str, user: dict = Depends(get_current_user)
):
    detail = await bot_client.get_armory_detail(user["discord_id"], character_name)
    return templates.TemplateResponse(
        request,
        "character_detail.html",
        {"user": user, "active": "expedition", "character_name": character_name, "detail": detail},
    )
