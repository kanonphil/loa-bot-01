"""공대 모집 페이지 — 목록/상세/참여/나가기/개설/파티장 관리."""
import json

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse

from webapp import config
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()


@router.get("/parties")
async def party_list(request: Request, user: dict = Depends(get_current_user)):
    parties = await bot_client.list_parties(config.DISCORD_GUILD_ID)
    return templates.TemplateResponse(
        request, "party_list.html", {"user": user, "active": "parties", "parties": parties}
    )


@router.get("/parties/create")
async def create_party_form(
    request: Request, error: str | None = None, user: dict = Depends(get_current_user)
):
    raids = await bot_client.get_raids()
    proficiency_options = await bot_client.get_proficiency_options()
    active_raids = {name: info for name, info in raids.items() if info.get("is_active", True)}
    # 레이드 선택에 따라 난이도 select를 채우는 용도 (서버 왕복 없이 JS로 처리)
    difficulties_by_raid = {
        name: list(info["difficulties"].keys()) for name, info in active_raids.items()
    }
    characters = await bot_client.get_user_characters_grouped(user["discord_id"])
    support_classes = set(await bot_client.get_support_classes())
    # 캐릭터 직업이 서포터가 아니면 "서포터" 역할을 고를 수 없다 — 참여 API도 동일하게 검증한다.
    character_is_support = {
        c["character_name"]: c["character_class"] in support_classes for c in characters
    }
    return templates.TemplateResponse(
        request,
        "party_create.html",
        {
            "user": user,
            "active": "parties",
            "raids": active_raids,
            "difficulties_by_raid_json": json.dumps(difficulties_by_raid, ensure_ascii=False),
            "proficiency_options": proficiency_options,
            "characters": characters,
            "character_is_support_json": json.dumps(character_is_support, ensure_ascii=False),
            "error": error,
        },
    )


@router.post("/parties/create")
async def create_party_submit(
    request: Request,
    raid_name: str = Form(...),
    difficulty: str = Form(...),
    proficiency: str = Form(...),
    scheduled_datetime: str = Form(...),
    memo: str = Form(""),
    character_name: str = Form(""),
    role: str = Form("dps"),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.create_party(
        user["discord_id"], config.DISCORD_GUILD_ID, raid_name, difficulty,
        proficiency, scheduled_datetime, memo.strip() or None,
    )
    if not result["success"]:
        return await create_party_form(request, error=result["reason"], user=user)

    message_id = result["message_id"]
    character_name = character_name.strip()
    if character_name:
        join_result = await bot_client.join_party(message_id, user["discord_id"], character_name, role)
        if not join_result.get("success"):
            from urllib.parse import quote

            reason = quote(join_result.get("reason") or "선택한 캐릭터로 자동 참여하지 못했습니다.")
            return RedirectResponse(f"/parties/{message_id}?join_error={reason}", status_code=303)

    return RedirectResponse(f"/parties/{message_id}", status_code=303)


async def _detail_context(message_id: str, discord_id: str) -> dict:
    party = await bot_client.get_party(message_id)
    if not party:
        return {"party": None}

    joined = any(s["discord_id"] == discord_id for s in party["slots"])
    is_leader = party["leader_id"] == discord_id
    other_members = [s for s in party["slots"] if s["discord_id"] != discord_id]
    eligibility = None
    if not joined and party["status"] != "disbanded":
        eligibility = await bot_client.get_party_eligibility(message_id, discord_id)

    raids = await bot_client.get_raids()
    raid_info = raids.get(party["raid_name"], {})
    diff_info = (raid_info.get("difficulties") or {}).get(party["difficulty"], {})
    party_split = diff_info.get("party_split")
    is_split = bool(party_split and party["total_slots"] > party_split)

    slot_by_number = {s["slot_number"]: s for s in party["slots"]}

    sub_parties = None
    party_groups = None
    all_slots = None

    if is_split:
        # 분할 파티는 "1파티/2파티" 별로 나란히, 각 파티 내부는 1번부터 다시 매기는 상대 번호로 보여준다.
        num_groups = party["total_slots"] // party_split
        sub_parties = list(range(1, num_groups + 1))
        party_groups = []
        for g in sub_parties:
            start = (g - 1) * party_split + 1
            slots = []
            filled_count = 0
            for local_number in range(1, party_split + 1):
                absolute_number = start + local_number - 1
                slot = slot_by_number.get(absolute_number)
                if slot:
                    filled_count += 1
                    slots.append({**slot, "local_number": local_number, "filled": True})
                else:
                    slots.append({"local_number": local_number, "filled": False})
            party_groups.append(
                {"group_number": g, "slots": slots, "filled_count": filled_count, "total": party_split}
            )
    else:
        # 슬롯은 연속으로 채워지지 않을 수 있다 — 번호 순으로 병합해서 표시용 목록을 만든다
        all_slots = [
            slot_by_number.get(n, {"slot_number": n, "filled": False})
            for n in range(1, party["total_slots"] + 1)
        ]
        for s in all_slots:
            s.setdefault("filled", True)

    return {
        "party": party,
        "joined": joined,
        "is_leader": is_leader,
        "other_members": other_members,
        "eligibility": eligibility,
        "sub_parties": sub_parties,
        "party_groups": party_groups,
        "all_slots": all_slots,
    }


@router.get("/parties/{message_id}")
async def party_detail(
    request: Request,
    message_id: str,
    join_error: str | None = None,
    user: dict = Depends(get_current_user),
):
    ctx = await _detail_context(message_id, user["discord_id"])
    action_result = {"success": False, "reason": join_error} if join_error else None
    return templates.TemplateResponse(
        request,
        "party_detail.html",
        {"user": user, "active": "parties", "action_result": action_result, **ctx},
    )


@router.post("/parties/{message_id}/join")
async def join(
    request: Request,
    message_id: str,
    character_name: str = Form(...),
    role: str = Form("dps"),
    party_group: int | None = Form(None),
    user: dict = Depends(get_current_user),
):
    action_result = await bot_client.join_party(
        message_id, user["discord_id"], character_name, role, party_group
    )
    ctx = await _detail_context(message_id, user["discord_id"])
    return templates.TemplateResponse(
        request,
        "party_detail.html",
        {"user": user, "active": "parties", "action_result": action_result, **ctx},
    )


@router.post("/parties/{message_id}/leave")
async def leave(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    action_result = await bot_client.leave_party(message_id, user["discord_id"])
    ctx = await _detail_context(message_id, user["discord_id"])
    return templates.TemplateResponse(
        request,
        "party_detail.html",
        {"user": user, "active": "parties", "action_result": action_result, **ctx},
    )


async def _manage_response(request, message_id, user, action_result):
    ctx = await _detail_context(message_id, user["discord_id"])
    return templates.TemplateResponse(
        request,
        "party_detail.html",
        {"user": user, "active": "parties", "action_result": action_result, **ctx},
    )


@router.post("/parties/{message_id}/close")
async def close_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.close_party(message_id, user["discord_id"])
    return await _manage_response(request, message_id, user, result)


@router.post("/parties/{message_id}/reopen")
async def reopen_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.reopen_party(message_id, user["discord_id"])
    return await _manage_response(request, message_id, user, result)


@router.post("/parties/{message_id}/clear")
async def clear_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.clear_party(message_id, user["discord_id"])
    return await _manage_response(request, message_id, user, result)


@router.post("/parties/{message_id}/cancel")
async def cancel_party(
    request: Request,
    message_id: str,
    reason: str = Form(""),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.cancel_party(message_id, user["discord_id"], reason.strip() or None)
    return await _manage_response(request, message_id, user, result)


@router.post("/parties/{message_id}/kick")
async def kick_member(
    request: Request,
    message_id: str,
    target_discord_id: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.kick_member(message_id, user["discord_id"], target_discord_id)
    return await _manage_response(request, message_id, user, result)


@router.post("/parties/{message_id}/reschedule")
async def reschedule_party(
    request: Request,
    message_id: str,
    scheduled_datetime: str = Form(...),
    memo: str = Form(""),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.reschedule_party(
        message_id, user["discord_id"], scheduled_datetime, memo.strip() or None
    )
    return await _manage_response(request, message_id, user, result)


@router.post("/parties/{message_id}/transfer-leader")
async def transfer_leader(
    request: Request,
    message_id: str,
    new_leader_discord_id: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.transfer_leader(
        message_id, user["discord_id"], new_leader_discord_id
    )
    return await _manage_response(request, message_id, user, result)
