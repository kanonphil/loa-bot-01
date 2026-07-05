"""레이드 체크 페이지 — 길드원이 본인 캐릭터 전체를 카드 그리드로 보며
이번 주 레이드 완료 여부를 확인/체크. 캐릭터마다 카드가 하나씩이고,
체크 토글은 그 카드만 갱신한다(다른 카드에 영향 없음). 부계정이 여러 개면
로스트아크 계정 단위로 필터링해서 볼 수 있다."""
import asyncio

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.raid_check import applicable_raids, group_by_category
from webapp.templating import templates

router = APIRouter()


def _account_label(character: dict) -> str:
    return character.get("account_label") or "기타"


async def _character_card(discord_id: str, character: dict, raids: dict, categories: list[dict]) -> dict:
    item_level = character.get("item_level") or 0
    completion_data = await bot_client.get_completions(discord_id, character["character_name"])
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
        "character_name": character["character_name"],
        "character_class": character["character_class"],
        "item_level": character.get("item_level"),
        "groups": groups,
        "done": done,
        "done_count": done_count,
        "total_slots": total_raids,
    }


async def _page_context(discord_id: str, account: str | None) -> dict:
    characters = await bot_client.get_user_characters_grouped(discord_id)
    if not characters:
        return {"characters": [], "cards": [], "account_labels": [], "selected_account": None}

    account_labels: list[str] = []
    for c in characters:
        label = _account_label(c)
        if label not in account_labels:
            account_labels.append(label)

    selected_account = account if account in account_labels else None
    visible = [c for c in characters if not selected_account or _account_label(c) == selected_account]

    raids, categories = await asyncio.gather(
        bot_client.get_raids(), bot_client.get_raid_categories()
    )
    cards = await asyncio.gather(
        *[_character_card(discord_id, c, raids, categories) for c in visible]
    )
    return {
        "characters": characters,
        "cards": list(cards),
        "account_labels": account_labels,
        "selected_account": selected_account,
    }


@router.get("/raid-check")
async def raid_check_page(
    request: Request, account: str | None = None, user: dict = Depends(get_current_user)
):
    ctx = await _page_context(user["discord_id"], account)
    return templates.TemplateResponse(
        request, "raid_check.html", {"user": user, "active": "raid_check", **ctx}
    )


@router.post("/raid-check/toggle")
async def toggle_raid_check(
    request: Request,
    raid_name: str = Form(...),
    difficulty: str = Form(...),
    character_name: str = Form(...),
    card_index: int = Form(...),
    user: dict = Depends(get_current_user),
):
    characters = await bot_client.get_user_characters_grouped(user["discord_id"])
    character = next((c for c in characters if c["character_name"] == character_name), None)
    if character is None:
        # 본인이 등록한 캐릭터가 아니면 거부 (폼 조작으로 남의 캐릭터 체크 방지)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 체크할 수 있습니다."
        )

    await bot_client.toggle_completion(user["discord_id"], character_name, raid_name, difficulty)

    raids, categories = await asyncio.gather(
        bot_client.get_raids(), bot_client.get_raid_categories()
    )
    card = await _character_card(user["discord_id"], character, raids, categories)
    return templates.TemplateResponse(
        request, "_raid_card.html", {"card": card, "card_index": card_index}
    )
