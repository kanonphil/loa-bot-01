"""레이드 체크 페이지 — 길드원이 본인 캐릭터 전체를 카드 그리드로 보며
이번 주 레이드 완료 여부를 확인/체크. 캐릭터마다 카드가 하나씩이고,
체크 토글은 그 카드만 갱신한다(다른 카드에 영향 없음). 부계정이 여러 개면
로스트아크 계정 단위로 필터링해서 볼 수 있다.

레이드가 계속 늘어날 예정이라(4개 → 7개 이상), 캐릭터마다 "레이드 선택" 화면에서
카드에 표시할 레이드를 직접 고를 수 있다 — 한 번도 고른 적 없으면 기존처럼
입장 가능한 레이드 전체를 보여준다."""
import asyncio

from datetime import datetime, timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from starlette.responses import RedirectResponse

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.raid_check import applicable_raids, filter_groups_by_selection, group_by_category
from webapp.templating import templates

router = APIRouter()


def _account_label(character: dict) -> str:
    return character.get("account_label") or "기타"


async def _find_own_character(discord_id: str, character_name: str) -> dict | None:
    characters = await bot_client.get_user_characters_grouped(discord_id)
    return next((c for c in characters if c["character_name"] == character_name), None)


async def _character_card(discord_id: str, character: dict, raids: dict, categories: list[dict]) -> dict:
    item_level = character.get("item_level") or 0
    completion_data, selection = await asyncio.gather(
        bot_client.get_completions(discord_id, character["character_name"]),
        bot_client.get_raid_selection(discord_id, character["character_name"]),
    )
    all_groups = group_by_category(raids, categories, applicable_raids(raids, item_level))
    groups = filter_groups_by_selection(all_groups, selection)
    done = set(completion_data["completions"])
    # 레이드 하나당 난이도는 여러 개지만, 진행률은 "레이드 단위"로 센다 —
    # 한 레이드에서 어느 난이도든 하나만 완료하면 그 레이드는 끝난 것으로 취급.
    # 진행률은 카드에 실제로 보이는(선택된) 레이드 기준으로 센다.
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
    request: Request, account: str | None = None, saved: int | None = None,
    user: dict = Depends(get_current_user),
):
    ctx = await _page_context(user["discord_id"], account)
    return templates.TemplateResponse(
        request, "raid_check.html", {"user": user, "active": "raid_check", "saved": saved, **ctx}
    )


def _week_label(week_key: str) -> str:
    """'2026-05-06' → '5/6(수) ~ 5/12(화)' — 주차 키는 수요일 06:00 리셋 기준 시작일."""
    try:
        start = datetime.strptime(week_key, "%Y-%m-%d")
    except ValueError:
        return week_key
    end = start + timedelta(days=6)
    days = ["월", "화", "수", "목", "금", "토", "일"]
    return f"{start.month}/{start.day}({days[start.weekday()]}) ~ {end.month}/{end.day}({days[end.weekday()]})"


@router.get("/raid-check/history")
async def raid_check_history(
    request: Request, week: str | None = None, user: dict = Depends(get_current_user)
):
    """지난 주차 클리어 기록 — raid_completions는 주차별로 다 쌓이는데 웹은 이번 주만 보여줬다."""
    weeks_info = await bot_client.get_completion_weeks(user["discord_id"])
    weeks = weeks_info["weeks"]
    selected = week if week in weeks else weeks_info["current_week"]
    data = await bot_client.get_week_completions(user["discord_id"], selected)
    return templates.TemplateResponse(
        request,
        "raid_check_history.html",
        {
            "user": user,
            "active": "raid_check",
            "weeks": [{"key": w, "label": _week_label(w), "is_current": w == weeks_info["current_week"]} for w in weeks],
            "selected_week": selected,
            "selected_label": _week_label(selected),
            "is_current": selected == weeks_info["current_week"],
            "characters": data["characters"],
        },
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
    character = await _find_own_character(user["discord_id"], character_name)
    if character is None:
        # 본인이 등록한 캐릭터가 아니면 거부 (폼 조작으로 남의 캐릭터 체크 방지)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 체크할 수 있습니다."
        )

    completed = await bot_client.toggle_completion(user["discord_id"], character_name, raid_name, difficulty)

    raids, categories = await asyncio.gather(
        bot_client.get_raids(), bot_client.get_raid_categories()
    )
    card = await _character_card(user["discord_id"], character, raids, categories)
    short = (raids.get(raid_name) or {}).get("short_name") or raid_name
    toast = f"{character_name} · {short} {difficulty} {'완료 체크' if completed else '체크 해제'}"
    # htmx 부분 갱신이라 flash-data를 못 쓴다 — 헤더는 latin-1이어야 해서 percent-encoding으로 싣는다
    return templates.TemplateResponse(
        request, "_raid_card.html", {"card": card, "card_index": card_index},
        headers={"X-Toast": quote(toast), "X-Toast-Type": "success" if completed else "info"},
    )


@router.get("/raid-check/select/{character_name}")
async def raid_select_page(
    request: Request, character_name: str, user: dict = Depends(get_current_user)
):
    character = await _find_own_character(user["discord_id"], character_name)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 설정할 수 있습니다."
        )

    raids, categories = await asyncio.gather(
        bot_client.get_raids(), bot_client.get_raid_categories()
    )
    item_level = character.get("item_level") or 0
    groups = group_by_category(raids, categories, applicable_raids(raids, item_level))

    selection = await bot_client.get_raid_selection(user["discord_id"], character_name)
    if selection["customized"]:
        selected_raids = set(selection["selected_raids"])
    else:
        # 커스터마이즈 전이면 지금 보이는 전체가 기본으로 다 체크된 상태로 시작한다.
        selected_raids = {r["raid_name"] for g in groups for r in g["raids"]}

    return templates.TemplateResponse(
        request,
        "raid_select.html",
        {
            "user": user,
            "active": "raid_check",
            "character_name": character_name,
            "groups": groups,
            "selected_raids": selected_raids,
        },
    )


@router.post("/raid-check/select/{character_name}")
async def raid_select_save(
    character_name: str,
    raid_names: list[str] = Form(default=[]),
    user: dict = Depends(get_current_user),
):
    character = await _find_own_character(user["discord_id"], character_name)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 설정할 수 있습니다."
        )

    await bot_client.set_raid_selection(user["discord_id"], character_name, raid_names)
    return RedirectResponse("/raid-check?saved=1", status_code=303)
