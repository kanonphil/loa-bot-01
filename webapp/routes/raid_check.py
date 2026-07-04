"""레이드 체크 페이지 — 길드원이 본인 캐릭터의 이번 주 레이드 완료 여부를 확인/체크."""
import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.raid_check import applicable_raids, group_by_category
from webapp.templating import templates

router = APIRouter()


async def _page_context(discord_id: str, character_name: str | None) -> dict:
    characters = await bot_client.get_user_characters(discord_id)
    if not characters:
        return {
            "characters": [],
            "selected_character": None,
            "groups": [],
            "done": set(),
            "done_count": 0,
            "total_slots": 0,
        }

    names = [c["character_name"] for c in characters]
    selected_character = character_name if character_name in names else names[0]
    selected_info = next(c for c in characters if c["character_name"] == selected_character)

    raids, categories, completion_data = await asyncio.gather(
        bot_client.get_raids(),
        bot_client.get_raid_categories(),
        bot_client.get_completions(discord_id, selected_character),
    )

    item_level = selected_info.get("item_level") or 0
    groups = group_by_category(raids, categories, applicable_raids(raids, item_level))
    done = set(completion_data["completions"])
    # 레이드 하나당 난이도는 여러 개지만, 진행률은 "레이드 단위"로 센다 —
    # 한 레이드에서 어느 난이도든 하나만 완료하면 그 레이드는 끝난 것으로 취급.
    total_raids = sum(len(g["raids"]) for g in groups)
    done_count = sum(
        1
        for g in groups
        for r in g["raids"]
        if any(f"{r['raid_name']}_{diff_name}" in done for diff_name, _ in r["difficulties"])
    )

    return {
        "characters": characters,
        "selected_character": selected_character,
        "groups": groups,
        "done": done,
        "done_count": done_count,
        "total_slots": total_raids,
    }


@router.get("/raid-check")
async def raid_check_page(
    request: Request, character: str | None = None, user: dict = Depends(get_current_user)
):
    ctx = await _page_context(user["discord_id"], character)
    return templates.TemplateResponse(
        request, "raid_check.html", {"user": user, "active": "raid_check", **ctx}
    )


@router.post("/raid-check/toggle")
async def toggle_raid_check(
    request: Request,
    raid_name: str = Form(...),
    difficulty: str = Form(...),
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    characters = await bot_client.get_user_characters(user["discord_id"])
    if character_name not in [c["character_name"] for c in characters]:
        # 본인이 등록한 캐릭터가 아니면 거부 (폼 조작으로 남의 캐릭터 체크 방지)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 체크할 수 있습니다."
        )

    await bot_client.toggle_completion(user["discord_id"], character_name, raid_name, difficulty)

    ctx = await _page_context(user["discord_id"], character_name)
    return templates.TemplateResponse(request, "_raid_checklist.html", ctx)
