"""메인 대시보드 — "지금 뭘 해야 하나"를 위에서부터 보여준다.

예전에는 카드 세 장(진행률/모집중 공대/내 캐릭터)이 전부 현황만 나열했다.
급한 것 → 내 진행 → 기회 순으로 바꾸고, 진행률은 봇이 한 번에 계산해 준
/raid-progress를 쓴다(캐릭터마다 왕복하던 N+1 호출 제거).
"""
import asyncio

from fastapi import APIRouter, Depends, Request

from webapp import config
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.format import party_view, reset_view
from webapp.templating import templates

router = APIRouter()

URGENT_LIMIT = 3        # 내 임박 공대는 최대 몇 개까지 위에 띄울지
OPPORTUNITY_LIMIT = 3   # "들어갈 만한 공대" 추천 개수


def split_parties(parties: list[dict], discord_id: str, max_level: float) -> tuple[list, list]:
    """내가 이미 속한 공대(임박순)와, 아직 안 들어갔지만 입장 가능한 공대를 나눈다."""
    mine, opportunities = [], []
    for p in parties:
        joined = p.get("leader_id") == discord_id or any(
            s["discord_id"] == discord_id for s in p.get("slots") or []
        )
        view = party_view(p)
        if joined:
            if not view["schedule"]["is_past"]:
                mine.append(view)
        elif (
            p["status"] == "recruiting"
            and (p.get("min_level") or 0) <= max_level
            and not view["schedule"]["is_past"]
        ):
            opportunities.append(view)

    key = lambda p: p.get("scheduled_datetime") or "9999"
    mine.sort(key=key)
    opportunities.sort(key=key)
    return mine, opportunities


async def _dashboard_context(discord_id: str) -> dict:
    characters, all_parties, progress = await asyncio.gather(
        bot_client.get_user_characters(discord_id),
        bot_client.list_parties(config.DISCORD_GUILD_ID),
        bot_client.get_raid_progress(discord_id),
    )

    max_level = max((c.get("item_level") or 0) for c in characters) if characters else 0
    mine, opportunities = split_parties(all_parties, discord_id, max_level)

    # 아직 남은 캐릭터만, 많이 남은 순으로 — "어디부터 돌면 되나"에 바로 답하도록.
    remaining = sorted(
        (c for c in progress["characters"] if c["remaining"] > 0),
        key=lambda c: -c["remaining"],
    )

    total = progress["total"]
    return {
        "characters": characters,
        "urgent_parties": mine[:URGENT_LIMIT],
        "my_party_count": len(mine),
        "opportunities": opportunities[:OPPORTUNITY_LIMIT],
        "opportunity_count": len(opportunities),
        "progress": progress,
        "progress_pct": round(progress["done"] / total * 100) if total else 0,
        "remaining_characters": remaining,
        "reset": reset_view(),
        "recruiting_count": sum(1 for p in all_parties if p["status"] == "recruiting"),
    }


@router.get("/main")
async def main_dashboard(request: Request, user: dict = Depends(get_current_user)):
    ctx = await _dashboard_context(user["discord_id"])
    return templates.TemplateResponse(
        request, "main.html", {"user": user, "active": "main", **ctx}
    )


@router.get("/nav-badges")
async def nav_badges(user: dict = Depends(get_current_user)):
    """사이드바 메뉴 옆 숫자. 페이지 렌더를 막지 않도록 로드 후 따로 가져간다."""
    parties, progress = await asyncio.gather(
        bot_client.list_parties(config.DISCORD_GUILD_ID),
        bot_client.get_raid_progress(user["discord_id"]),
    )
    return {
        "parties": sum(1 for p in parties if p["status"] == "recruiting"),
        "raid_check": max(progress["total"] - progress["done"], 0),
    }
