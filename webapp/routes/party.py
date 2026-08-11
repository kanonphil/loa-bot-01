"""공대 모집 페이지 — 목록/상세/참여/나가기/개설/파티장 관리."""
import asyncio
import json
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse

from webapp import config
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.format import party_view
from webapp.raids import picker_groups
from webapp.templating import templates

router = APIRouter()

# 목록 상단 필터 — 라벨과 순서를 한 곳에서 관리한다.
PARTY_FILTERS = [
    ("all", "전체"),
    ("recruiting", "모집중"),
    ("mine", "내 공대"),
    ("eligible", "입장 가능"),
]


def _max_item_level(characters: list[dict]) -> float:
    return max((c.get("item_level") or 0) for c in characters) if characters else 0


_HISTORY_STATUS = {
    "recruiting": ("모집중", "accent"),
    "full": ("파티완성", "ok"),
    "closed": ("마감", ""),
    "disbanded": ("클리어", "ok"),
    "cancelled": ("취소", "danger"),
}


def _history_view(entry: dict) -> dict:
    label, tone = _HISTORY_STATUS.get(entry["status"], (entry["status"], ""))
    return {**entry, "status_label": label, "status_tone": tone}


def filter_parties(parties: list[dict], key: str, discord_id: str, max_level: float) -> list[dict]:
    """목록 필터. '입장 가능'은 내 캐릭터 중 가장 높은 레벨 기준으로,
    아직 자리가 남아 있고 이미 참여하지 않은 공대만 남긴다."""
    if key == "recruiting":
        return [p for p in parties if p["status"] == "recruiting"]
    if key == "mine":
        return [
            p for p in parties
            if p.get("leader_id") == discord_id
            or any(s["discord_id"] == discord_id for s in p.get("slots") or [])
        ]
    if key == "eligible":
        return [
            p for p in parties
            if p["status"] == "recruiting"
            and (p.get("min_level") or 0) <= max_level
            and not any(s["discord_id"] == discord_id for s in p.get("slots") or [])
        ]
    return parties


@router.get("/parties")
async def party_list(
    request: Request, filter: str = "all", user: dict = Depends(get_current_user)
):
    if filter not in dict(PARTY_FILTERS):
        filter = "all"
    parties, characters = await asyncio.gather(
        bot_client.list_parties(config.DISCORD_GUILD_ID),
        bot_client.get_user_characters(user["discord_id"]),
    )
    max_level = _max_item_level(characters)
    discord_id = user["discord_id"]

    counts = {
        key: len(filter_parties(parties, key, discord_id, max_level))
        for key, _ in PARTY_FILTERS
    }
    visible = [party_view(p) for p in filter_parties(parties, filter, discord_id, max_level)]
    # 가까운 일정부터 — 일정이 없는 공대는 뒤로.
    visible.sort(key=lambda p: (p.get("scheduled_datetime") is None, p.get("scheduled_datetime") or ""))

    return templates.TemplateResponse(
        request,
        "party_list.html",
        {
            "user": user,
            "active": "parties",
            "parties": visible,
            "filters": PARTY_FILTERS,
            "active_filter": filter,
            "counts": counts,
            "has_any": bool(parties),
        },
    )


_HISTORY_PAGE_SIZE = 20


@router.get("/parties/history")
async def party_history(
    request: Request, page: int = 1, user: dict = Depends(get_current_user),
):
    page = max(page, 1)
    offset = (page - 1) * _HISTORY_PAGE_SIZE
    result = await bot_client.get_user_party_history(
        user["discord_id"], limit=_HISTORY_PAGE_SIZE, offset=offset,
    )
    visible = [_history_view(e) for e in result["entries"]]  # 이미 최근순(created_at DESC)으로 옴
    return templates.TemplateResponse(
        request,
        "party_history.html",
        {
            "user": user,
            "active": "parties",
            "entries": visible,
            "page": page,
            "has_more": result["has_more"],
        },
    )


@router.get("/parties/create")
async def create_party_form(
    request: Request, error: str | None = None, user: dict = Depends(get_current_user)
):
    raids, proficiency_options, characters, support_classes = await asyncio.gather(
        bot_client.get_raids(),
        bot_client.get_proficiency_options(),
        bot_client.get_user_characters_grouped(user["discord_id"]),
        bot_client.get_support_classes(),
    )
    # 관리자가 정한 순서(카테고리 → sort_order → 상단 고정) 그대로 보여준다.
    groups = picker_groups(raids, _max_item_level(characters) or None)
    character_levels = {
        c["character_name"]: c.get("item_level") or 0 for c in characters
    }
    # 캐릭터 직업이 서포터가 아니면 "서포터" 역할을 고를 수 없다 — 참여 API도 동일하게 검증한다.
    support_set = set(support_classes)
    character_is_support = {
        c["character_name"]: c["character_class"] in support_set for c in characters
    }
    return templates.TemplateResponse(
        request,
        "party_create.html",
        {
            "user": user,
            "active": "parties",
            "groups": groups,
            "groups_json": json.dumps(groups, ensure_ascii=False),
            "proficiency_options": proficiency_options,
            "characters": characters,
            "character_levels_json": json.dumps(character_levels, ensure_ascii=False),
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
    my_slot = next((s for s in party["slots"] if s["discord_id"] == discord_id), None)
    can_switch_to_support = False
    if joined and my_slot and my_slot["role"] != "support":
        support_classes = set(await bot_client.get_support_classes())
        can_switch_to_support = my_slot["character_class"] in support_classes
    eligibility = None
    character_is_support_json = "{}"
    if not joined and party["status"] != "disbanded":
        eligibility = await bot_client.get_party_eligibility(message_id, discord_id)
        if eligibility and eligibility.get("qualifying"):
            support_classes = set(await bot_client.get_support_classes())
            character_is_support_json = json.dumps(
                {q["name"]: q["class"] in support_classes for q in eligibility["qualifying"]},
                ensure_ascii=False,
            )

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
            has_support = any(s.get("filled") and s.get("role") == "support" for s in slots)
            party_groups.append(
                {
                    "group_number": g, "slots": slots, "filled_count": filled_count,
                    "total": party_split, "has_support": has_support,
                }
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
        "my_slot": my_slot,
        "can_switch_to_support": can_switch_to_support,
        "eligibility": eligibility,
        "character_is_support_json": character_is_support_json,
        "sub_parties": sub_parties,
        "party_groups": party_groups,
        "all_slots": all_slots,
    }


@router.get("/parties/{message_id}")
async def party_detail(
    request: Request,
    message_id: str,
    join_error: str | None = None,
    cancelled: bool = False,
    user: dict = Depends(get_current_user),
):
    ctx = await _detail_context(message_id, user["discord_id"])
    if join_error:
        action_result = {"success": False, "reason": join_error}
    elif cancelled:
        action_result = {"success": True}
    else:
        action_result = None
    return templates.TemplateResponse(
        request,
        "party_detail.html",
        {"user": user, "active": "parties", "action_result": action_result, **ctx},
    )


def _redirect_with_result(message_id: str, result: dict, fallback_reason: str) -> RedirectResponse:
    """액션 결과를 렌더링 대신 redirect로 돌려준다 — POST 응답을 그대로 렌더하면
    뒤로가기 시 브라우저가 "이 페이지를 다시 표시하려면..." 폼 재제출 경고를 띄우고,
    실수로 뒤로 갔다 앞으로 오면 같은 액션(참여/퇴장/강제퇴장 등)이 다시 전송될 수 있다."""
    if not result.get("success"):
        reason = quote(result.get("reason") or fallback_reason)
        return RedirectResponse(f"/parties/{message_id}?join_error={reason}", status_code=303)
    return RedirectResponse(f"/parties/{message_id}", status_code=303)


@router.post("/parties/{message_id}/join")
async def join(
    request: Request,
    message_id: str,
    character_name: str = Form(...),
    role: str = Form("dps"),
    party_group: int | None = Form(None),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.join_party(
        message_id, user["discord_id"], character_name, role, party_group
    )
    return _redirect_with_result(message_id, result, "참여하지 못했습니다.")


@router.post("/parties/{message_id}/leave")
async def leave(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.leave_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "나가지 못했습니다.")


@router.get("/parties/{message_id}/switch")
async def switch_character_form(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    """파티를 나갔다 재참여하지 않고 참여 캐릭터만 바꾸는 폼 — 참여 중인 사람만 접근 가능."""
    party = await bot_client.get_party(message_id)
    if not party:
        return RedirectResponse("/parties", status_code=303)
    eligibility = await bot_client.get_switch_eligibility(message_id, user["discord_id"])
    if not eligibility["can_switch"]:
        return RedirectResponse(f"/parties/{message_id}", status_code=303)
    return templates.TemplateResponse(
        request,
        "party_switch_character.html",
        {"user": user, "active": "parties", "party": party, "eligibility": eligibility},
    )


@router.post("/parties/{message_id}/switch")
async def switch_character_submit(
    request: Request,
    message_id: str,
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.switch_character(message_id, user["discord_id"], character_name)
    return _redirect_with_result(message_id, result, "캐릭터를 변경하지 못했습니다.")


@router.post("/parties/{message_id}/switch-role")
async def switch_role_submit(
    request: Request,
    message_id: str,
    new_role: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.switch_role(message_id, user["discord_id"], new_role)
    return _redirect_with_result(message_id, result, "역할을 변경하지 못했습니다.")


@router.post("/parties/{message_id}/close")
async def close_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.close_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "마감하지 못했습니다.")


@router.post("/parties/{message_id}/reopen")
async def reopen_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.reopen_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "재개하지 못했습니다.")


@router.post("/parties/{message_id}/clear")
async def clear_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.clear_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "클리어 처리하지 못했습니다.")


@router.post("/parties/{message_id}/cancel")
async def cancel_party(
    request: Request,
    message_id: str,
    reason: str = Form(""),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.cancel_party(message_id, user["discord_id"], reason.strip() or None)
    if not result.get("success"):
        error = quote(result.get("reason") or "취소하지 못했습니다.")
        return RedirectResponse(f"/parties/{message_id}?join_error={error}", status_code=303)
    # 취소 성공 후에는 party 자체가 없어지므로(디스코드 파티와 동일하게), 빈 상태 화면에
    # "취소되었습니다" 안내를 보여주도록 신호만 넘긴다.
    return RedirectResponse(f"/parties/{message_id}?cancelled=1", status_code=303)


@router.post("/parties/{message_id}/kick")
async def kick_member(
    request: Request,
    message_id: str,
    target_discord_id: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.kick_member(message_id, user["discord_id"], target_discord_id)
    return _redirect_with_result(message_id, result, "강제 퇴장시키지 못했습니다.")


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
    return _redirect_with_result(message_id, result, "일정을 변경하지 못했습니다.")


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
    return _redirect_with_result(message_id, result, "파티장을 위임하지 못했습니다.")
