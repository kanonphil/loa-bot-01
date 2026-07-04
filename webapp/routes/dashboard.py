"""메인 대시보드 — 레이드 진행률 요약, 모집 중인 공대 목록, 내 캐릭터 요약을 한눈에."""
import asyncio

from fastapi import APIRouter, Depends, Request

from webapp import config
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.raid_check import applicable_raids, group_by_category
from webapp.templating import templates

router = APIRouter()


async def _character_progress(character: dict, raids: dict, categories: list[dict]) -> dict:
    item_level = character.get("item_level") or 0
    groups = group_by_category(raids, categories, applicable_raids(raids, item_level))
    total_slots = sum(len(r["difficulties"]) for g in groups for r in g["raids"])
    completion_data = await bot_client.get_completions(
        character["discord_id"], character["character_name"]
    )
    done_count = len(completion_data["completions"])
    return {
        "character_name": character["character_name"],
        "character_class": character.get("character_class"),
        "item_level": item_level,
        "done_count": done_count,
        "total_slots": total_slots,
    }


async def _dashboard_context(discord_id: str) -> dict:
    characters, all_parties = await asyncio.gather(
        bot_client.get_user_characters(discord_id),
        bot_client.list_parties(config.DISCORD_GUILD_ID),
    )

    raid_progress = []
    if characters:
        raids, categories = await asyncio.gather(
            bot_client.get_raids(), bot_client.get_raid_categories()
        )
        for c in characters:
            raid_progress.append(
                await _character_progress({**c, "discord_id": discord_id}, raids, categories)
            )

    overall_done = sum(c["done_count"] for c in raid_progress)
    overall_total = sum(c["total_slots"] for c in raid_progress)

    recruiting_parties = [p for p in all_parties if p["status"] == "recruiting"]
    recruiting_parties.sort(key=lambda p: p.get("scheduled_datetime") or "")

    return {
        "characters": characters,
        "raid_progress": raid_progress,
        "overall_done": overall_done,
        "overall_total": overall_total,
        "recruiting_parties": recruiting_parties[:5],
    }


@router.get("/main")
async def main_dashboard(request: Request, user: dict = Depends(get_current_user)):
    ctx = await _dashboard_context(user["discord_id"])
    return templates.TemplateResponse(
        request, "main.html", {"user": user, "active": "main", **ctx}
    )
