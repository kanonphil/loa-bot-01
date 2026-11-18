"""레이드 체크 — 화면은 홈(/main)의 숙제표로 옮겼다. 여기에는 숙제표가 부르는 체크 동작과
홈에서 이어지는 보조 화면(레이드 고르기·지난 주 기록)이 남아 있다.

체크 토글·익스트림 체크/해제는 홈의 home.js가 `Accept: application/json`으로 부르면 JSON
(`{success, reason, ...}`)을 돌려주고, 그냥 폼으로 부르면 기존처럼 303 + 토스트로 홈에 돌려보낸다.
레이드가 계속 늘어날 예정이라(4개 → 7개 이상), 캐릭터마다 "레이드 고르기" 화면에서
숙제표에 표시할 레이드를 직접 고를 수 있다 — 한 번도 고른 적 없으면 입장 가능한 레이드 전체를 보여준다."""
import asyncio

from datetime import datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from starlette.responses import JSONResponse, RedirectResponse

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.flash import redirect_result
from webapp.raid_check import (
    applicable_raids, extreme_raids, filter_groups_by_selection, group_by_category,
)
from webapp.templating import templates

router = APIRouter()


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def _json_error(exc: Exception):
    """JSON 모드에서 검증 실패·봇 오류를 화면용 {success: false, reason}으로 바꾼다."""
    if isinstance(exc, HTTPException):
        return JSONResponse({"success": False, "reason": str(exc.detail)}, status_code=exc.status_code)
    return JSONResponse({"success": False, "reason": "봇 서버와 통신하지 못했습니다. 잠시 후 다시 시도해주세요."}, status_code=502)


async def _find_own_character(discord_id: str, character_name: str) -> dict | None:
    characters = await bot_client.get_user_characters_grouped(discord_id)
    return next((c for c in characters if c["character_name"] == character_name), None)


async def _character_progress(discord_id: str, character: dict, raids: dict, categories: list[dict]) -> dict:
    """이 캐릭터의 이번 주 완료 키 집합과 (완료, 전체) 레이드 수 — 홈 숙제표 한 행을 다시 그리는 데 필요한 값."""
    item_level = character.get("item_level") or 0
    completion_data, selection = await asyncio.gather(
        bot_client.get_completions(discord_id, character["character_name"]),
        bot_client.get_raid_selection(discord_id, character["character_name"]),
    )
    all_groups = group_by_category(raids, categories, applicable_raids(raids, item_level))
    groups = filter_groups_by_selection(all_groups, selection)
    done = set(completion_data["completions"])
    # 진행률은 "레이드 단위" — 한 레이드에서 어느 난이도든 하나만 완료하면 끝난 것이고,
    # 숙제표에 실제로 보이는(선택된) 레이드만 센다.
    total = sum(len(g["raids"]) for g in groups)
    done_count = sum(
        1
        for g in groups
        for r in g["raids"]
        if any(f"{r['raid_name']}_{diff_name}" in done for diff_name, _ in r["difficulties"])
    )
    return {"completions": sorted(done), "done": done_count, "total": total}


async def _toggle(discord_id: str, raid_name: str, difficulty: str, character_name: str) -> dict:
    character = await _find_own_character(discord_id, character_name)
    if character is None:
        # 본인이 등록한 캐릭터가 아니면 거부 (폼 조작으로 남의 캐릭터 체크 방지)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 체크할 수 있습니다.")
    raids, categories = await asyncio.gather(bot_client.get_raids(), bot_client.get_raid_categories())
    # 이 캐릭터가 실제로 입장할 수 있는 (레이드, 난이도)만 — 익스트림은 applicable_raids가 기본 제외한다.
    # 폼을 조작해 임의 레이드/난이도(익스트림 포함)를 봇에 보내 주간 제한을 우회하지 못하게.
    allowed = {(r, d) for r, d, _ in applicable_raids(raids, character.get("item_level") or 0)}
    if (raid_name, difficulty) not in allowed:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="체크할 수 없는 레이드입니다.")

    result = await bot_client.toggle_completion(discord_id, character_name, raid_name, difficulty)
    short = (raids.get(raid_name) or {}).get("short_name") or raid_name
    if not result["success"]:
        return {"success": False, "reason": result.get("reason") or "체크하지 못했습니다.", "short": short}
    progress = await _character_progress(discord_id, character, raids, categories)
    return {"success": True, "completed": result["completed"], "short": short, **progress}


@router.post("/raid-check/toggle")
async def toggle_raid_check(
    request: Request,
    raid_name: str = Form(...),
    difficulty: str = Form(...),
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    as_json = _wants_json(request)
    try:
        result = await _toggle(user["discord_id"], raid_name, difficulty, character_name)
    except (HTTPException, httpx.HTTPError) as exc:
        if not as_json:
            raise
        return _json_error(exc)

    if as_json:
        return {
            "success": result["success"],
            "completed": result.get("completed", False),
            "reason": result.get("reason"),
            "done": result.get("done"),
            "total": result.get("total"),
            "completions": result.get("completions"),
        }
    if not result["success"]:
        return redirect_result("/main", {"success": False, "reason": result["reason"]}, None)
    label = "완료 체크" if result["completed"] else "체크 해제"
    return redirect_result("/main", {"success": True}, f"{character_name} · {result['short']} {difficulty} {label}")


async def _extreme_set(discord_id: str, raid_name: str, difficulty: str, character_name: str) -> dict:
    characters, raids = await asyncio.gather(
        bot_client.get_user_characters_grouped(discord_id), bot_client.get_raids()
    )
    if not any(c["character_name"] == character_name for c in characters):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 체크할 수 있습니다.")
    # 지금 운영 중인 익스트림 레이드의 실제 난이도만 받는다 — 폼 조작으로 일반 레이드·없는 난이도를 보내지 못하게.
    live = {r["raid_name"]: r for r in extreme_raids(raids)}
    if raid_name not in live or difficulty not in dict(live[raid_name]["difficulties"]):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="체크할 수 없는 레이드입니다.")
    result = await bot_client.set_extreme_completion(discord_id, raid_name, difficulty, character_name)
    short = (raids.get(raid_name) or {}).get("short_name") or raid_name
    return {**result, "short": short}


@router.post("/raid-check/extreme/set")
async def set_extreme(
    request: Request,
    raid_name: str = Form(...),
    difficulty: str = Form(...),
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    as_json = _wants_json(request)
    try:
        result = await _extreme_set(user["discord_id"], raid_name, difficulty, character_name)
    except (HTTPException, httpx.HTTPError) as exc:
        if not as_json:
            raise
        return _json_error(exc)
    if as_json:
        return {
            "success": bool(result.get("success")),
            "reason": None if result.get("success") else (result.get("reason") or "체크하지 못했습니다."),
        }
    return redirect_result(
        "/main", result, f"{result['short']} {difficulty} 원정대 클리어 — {character_name}", "체크하지 못했습니다.",
    )


@router.post("/raid-check/extreme/clear")
async def clear_extreme(
    request: Request, raid_name: str = Form(...), user: dict = Depends(get_current_user),
):
    as_json = _wants_json(request)
    try:
        result = await bot_client.clear_extreme_completion(user["discord_id"], raid_name)
    except httpx.HTTPError as exc:
        if not as_json:
            raise
        return _json_error(exc)
    if as_json:
        return {
            "success": bool(result.get("success")),
            "reason": None if result.get("success") else (result.get("reason") or "해제하지 못했습니다."),
        }
    return redirect_result("/main", result, "클리어 기록을 해제했습니다.", "해제하지 못했습니다.")


@router.get("/raid-check")
async def raid_check_page():
    """레이드 체크 화면은 홈의 숙제표로 합쳤다 — 옛 주소·북마크는 홈으로."""
    return RedirectResponse("/main", status_code=303)


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
            "active": "main",
            "weeks": [{"key": w, "label": _week_label(w), "is_current": w == weeks_info["current_week"]} for w in weeks],
            "selected_week": selected,
            "selected_label": _week_label(selected),
            "is_current": selected == weeks_info["current_week"],
            "characters": data["characters"],
        },
    )


@router.get("/raid-check/select/{character_name}")
async def raid_select_page(
    request: Request, character_name: str, account: str | None = None,
    user: dict = Depends(get_current_user),
):
    character = await _find_own_character(user["discord_id"], character_name)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 설정할 수 있습니다."
        )
    raids, categories, selection = await asyncio.gather(
        bot_client.get_raids(),
        bot_client.get_raid_categories(),
        bot_client.get_raid_selection(user["discord_id"], character_name),
    )
    item_level = character.get("item_level") or 0
    groups = group_by_category(raids, categories, applicable_raids(raids, item_level))

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
            "active": "main",
            "character_name": character_name,
            "groups": groups,
            "selected_raids": selected_raids,
            "account": account or "",
        },
    )


@router.post("/raid-check/select/{character_name}")
async def raid_select_save(
    character_name: str,
    raid_names: list[str] = Form(default=[]),
    account: str = Form(""),
    user: dict = Depends(get_current_user),
):
    character = await _find_own_character(user["discord_id"], character_name)
    if character is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="본인 캐릭터만 설정할 수 있습니다."
        )

    result = await bot_client.set_raid_selection(user["discord_id"], character_name, raid_names)
    return redirect_result("/main", result, f"{character_name}의 레이드 선택을 저장했습니다.", "레이드 선택을 저장하지 못했습니다.")
