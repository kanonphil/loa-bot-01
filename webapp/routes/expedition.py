"""원정대 관리 — 웹에서 캐릭터 등록/삭제/아이템레벨 동기화.
Discord의 /캐릭터등록, /캐릭터삭제, "동기화" 버튼과 동일한 봇 내부 로직을 그대로 호출한다."""
from fastapi import APIRouter, Depends, Form, Request

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()


async def _page_context(discord_id: str) -> dict:
    characters = await bot_client.get_user_characters(discord_id)
    return {"characters": characters}


@router.get("/expedition")
async def expedition_page(request: Request, user: dict = Depends(get_current_user)):
    ctx = await _page_context(user["discord_id"])
    return templates.TemplateResponse(
        request, "expedition.html", {"user": user, "active": "expedition", **ctx}
    )


@router.post("/expedition/add")
async def add_character(
    request: Request,
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    action_result = await bot_client.add_character(user["discord_id"], character_name)
    ctx = await _page_context(user["discord_id"])
    return templates.TemplateResponse(
        request,
        "expedition.html",
        {"user": user, "active": "expedition", "action_result": action_result, **ctx},
    )


@router.post("/expedition/remove")
async def remove_character(
    request: Request,
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    action_result = await bot_client.remove_character(user["discord_id"], character_name)
    ctx = await _page_context(user["discord_id"])
    return templates.TemplateResponse(
        request,
        "expedition.html",
        {"user": user, "active": "expedition", "action_result": action_result, **ctx},
    )


@router.post("/expedition/sync")
async def sync_characters(request: Request, user: dict = Depends(get_current_user)):
    sync_result = await bot_client.sync_characters(user["discord_id"])
    ctx = await _page_context(user["discord_id"])
    return templates.TemplateResponse(
        request,
        "expedition.html",
        {"user": user, "active": "expedition", "sync_result": sync_result, **ctx},
    )
