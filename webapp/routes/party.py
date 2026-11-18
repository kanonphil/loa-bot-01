"""공대 모집 페이지 — 목록/상세/참여/나가기/개설/파티장 관리."""
import asyncio
import logging
from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import JSONResponse, RedirectResponse

from webapp import config, party_events, party_logic
from webapp.auth.dependencies import get_current_user, require_admin
from webapp.clients import bot_client, bot_party
from webapp.flash import redirect_with_toast
from webapp.format import KST, _parse, party_view, period_view
from webapp.raids import picker_groups
from webapp.templating import templates

logger = logging.getLogger("webapp.party")
router = APIRouter()

# 목록 상단 필터 — 라벨과 순서를 한 곳에서 관리한다. 기본은 "들어갈 수 있는".
PARTY_FILTERS = [
    ("eligible", "들어갈 수 있는"),
    ("all", "전체"),
    ("mine", "내 공대"),
]
DEFAULT_FILTER = "eligible"


async def _safe(coro, default=None):
    """보조 조회(추천 계산 재료)가 실패해도 화면은 떠야 한다 — 실패하면 기본값."""
    try:
        return await coro
    except Exception:
        logger.warning("공대 화면 보조 조회 실패", exc_info=True)
        return default


def _max_item_level(characters: list[dict]) -> float:
    return max((c.get("item_level") or 0) for c in characters) if characters else 0


def _history_view(entry: dict) -> dict:
    label, tone = party_logic.status_view(entry)
    return {**entry, "status_label": label, "status_tone": tone}


def _is_mine(party: dict, discord_id: str) -> bool:
    return party.get("leader_id") == discord_id or any(
        s.get("discord_id") == discord_id for s in party.get("slots") or []
    )


def _leader_name(party: dict) -> str | None:
    slot = next((s for s in party.get("slots") or [] if s.get("discord_id") == party.get("leader_id")), None)
    return slot["character_name"] if slot else None


def _row_view(party: dict, raids: dict, summary: dict | None, parties: list[dict], discord_id: str) -> dict:
    view = party_view(party)
    label, tone = party_logic.status_view(party)
    view["status_label"], view["status_tone"] = label, tone
    info = raids.get(party.get("raid_name")) or {}
    comp = party_logic.composition(party)
    sched = view["schedule"]
    active = party.get("status") in party_logic.ACTIVE_STATUSES
    view.update({
        "comp": comp,
        "period": period_view(info["available_until"]) if info.get("available_until") else None,
        "is_extreme": bool(info.get("is_extreme")),
        "is_mine": _is_mine(party, discord_id),
        "leader_name": _leader_name(party),
        "overdue": bool(sched.get("is_past") and active),
        "join": party_logic.list_row_join(party, summary, parties, discord_id, raids),
    })
    return view


@router.get("/parties")
async def party_list(
    request: Request, filter: str | None = None, user: dict = Depends(get_current_user)
):
    discord_id = user["discord_id"]
    parties, raids, summary = await asyncio.gather(
        bot_client.list_parties(config.DISCORD_GUILD_ID),
        bot_client.get_raids(),
        _safe(bot_party.get_raid_check_summary(discord_id)),
    )
    if filter not in dict(PARTY_FILTERS):
        # 기본은 "들어갈 수 있는" — 참여 가능 여부를 못 불러왔으면 빈 화면이 되지 않게 전체를 보여준다
        filter = DEFAULT_FILTER if summary is not None else "all"
    rows = [_row_view(p, raids, summary, parties, discord_id) for p in parties]
    counts = {
        "eligible": sum(1 for r in rows if r["join"]["state"] == "can"),
        "all": len(rows),
        "mine": sum(1 for r in rows if r["is_mine"]),
    }
    if filter == "eligible":
        visible = [r for r in rows if r["join"]["state"] == "can"]
    elif filter == "mine":
        visible = [r for r in rows if r["is_mine"]]
    else:
        visible = rows
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
            "summary_ok": summary is not None,
        },
    )


_HISTORY_PAGE_SIZE = 10


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
    total_pages = max(1, -(-result["total_count"] // _HISTORY_PAGE_SIZE))  # 올림 나눗셈
    # 최대 5개 번호만 보여준다 — 현재 페이지를 가운데 두되, 양 끝에서는 창을 안쪽으로 민다.
    window_start = max(1, min(page - 2, total_pages - 4))
    window_end = min(total_pages, window_start + 4)
    window_start = max(1, window_end - 4)
    page_numbers = list(range(window_start, window_end + 1))
    return templates.TemplateResponse(
        request,
        "party_history.html",
        {
            "user": user,
            "active": "parties",
            "entries": visible,
            "page": page,
            "has_more": result["has_more"],
            "total_pages": total_pages,
            "page_numbers": page_numbers,
        },
    )


# ── 공대 열기 ─────────────────────────────────────────────

_WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def _next_occurrence(weekday: int, hour: int, minute: int, now: datetime) -> datetime:
    """지금 이후 처음 오는 (요일, 시각)."""
    candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidate += timedelta(days=(weekday - candidate.weekday()) % 7)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def recent_openings(entries: list[dict], raids: dict, discord_id: str, now: datetime | None = None, limit: int = 3) -> list[dict]:
    """"다시 열기" 칩 — 내가 최근에 연 공대(같은 레이드·난이도는 한 번만). 요일·시각만 따라가고
    날짜는 다음 그 요일로 맞춘다. 지금 열 수 없는 레이드·난이도는 뺀다."""
    now = now or datetime.now(KST)
    seen: set[tuple] = set()
    out = []
    for e in entries:
        if e.get("leader_id") not in (None, discord_id):
            continue
        key = (e.get("raid_name"), e.get("difficulty"))
        info = raids.get(e.get("raid_name")) or {}
        if key in seen or not info.get("is_active", True) or e.get("difficulty") not in (info.get("difficulties") or {}):
            continue
        try:
            when = datetime.strptime(f"{now.year}/{e['scheduled_time']}", "%Y/%m/%d %H:%M").replace(tzinfo=KST)
        except (KeyError, TypeError, ValueError):
            continue
        seen.add(key)
        nxt = _next_occurrence(when.weekday(), when.hour, when.minute, now)
        out.append({
            "raid_name": e["raid_name"], "difficulty": e["difficulty"], "proficiency": e.get("proficiency") or "",
            "memo": e.get("memo") or "", "time": nxt.strftime("%Y-%m-%dT%H:%M"),
            "label": f"{info.get('short_name') or e['raid_name']} {e['difficulty']} · {_WEEKDAYS[when.weekday()]} {when:%H:%M}"
                     + (f" · {e['proficiency']}" if e.get("proficiency") else ""),
        })
        if len(out) >= limit:
            break
    return out


async def _create_check_data(
    discord_id: str, raid_name: str, difficulty: str, scheduled_datetime: str,
) -> dict:
    """개설 화면의 일정 안내·중복 경고·캐릭터 추천을 한 번에 계산한다 — 화면이 레이드·난이도·일정을 바꿀 때마다 부른다."""
    now = datetime.now(KST)
    target = _parse(scheduled_datetime) if scheduled_datetime else None

    async def _none():
        return None

    # 구독자 수: 레이드·난이도를 다 골랐을 때만 묻는다. 봇 오류면 None(화면은 줄을 숨긴다).
    subscribers_call = (
        _safe(bot_party.get_raid_subscribers_count(raid_name, difficulty, discord_id, scheduled_datetime))
        if raid_name and difficulty else _none()
    )
    parties, raids, summary, subscribers = await asyncio.gather(
        bot_client.list_parties(config.DISCORD_GUILD_ID),
        bot_client.get_raids(),
        _safe(bot_party.get_raid_check_summary(discord_id)),
        subscribers_call,
    )
    info = raids.get(raid_name) or {}
    diff = (info.get("difficulties") or {}).get(difficulty) or {}
    duplicates = [
        {
            "message_id": p["message_id"],
            "title": f"{p['raid_name']} {p['difficulty']}",
            "leader": _leader_name(p),
            "filled": len(p.get("slots") or []), "total": p.get("total_slots"),
            "when": party_view(p)["schedule"]["when"],
        }
        for p in party_logic.find_duplicates(parties, raid_name, difficulty, target)
    ]
    options = []
    if info and diff:
        options = party_logic.character_options(
            summary, raid_name=raid_name, difficulty=difficulty, min_level=diff.get("min_level") or 0,
            target=target, my_slots=party_logic.my_party_slots(parties, discord_id),
            lacks_support=True,  # 새 공대는 서포터가 비어 있다
            is_extreme=bool(info.get("is_extreme")), now=now,
        )
    return {
        "reset": party_logic.reset_info(target, now),
        "duplicates": duplicates,
        "options": options,
        "has_summary": summary is not None,
        # 열면 "새 공대" DM을 받을 구독자 수(int) — 레이드·난이도 미선택이거나 봇 오류면 None
        "subscribers": subscribers if (info and diff) else None,
    }


@router.get("/parties/create")
async def create_party_form(
    request: Request, error: str | None = None, user: dict = Depends(get_current_user),
):
    discord_id = user["discord_id"]
    raids, proficiency_options, summary, history = await asyncio.gather(
        bot_client.get_raids(),
        bot_client.get_proficiency_options(),
        _safe(bot_party.get_raid_check_summary(discord_id)),
        _safe(bot_client.get_user_party_history(discord_id, limit=20, offset=0), {"entries": []}),
    )
    if summary is not None:
        characters = [
            {"character_name": c["character_name"], "character_class": c.get("character_class"),
             "item_level": c.get("item_level") or 0, "is_support": bool(c.get("is_support"))}
            for c in summary.get("characters") or []
        ]
    else:  # 요약 조회가 안 되면 예전처럼 전체 나열(추천·불가 사유는 없음)
        grouped, support_classes = await asyncio.gather(
            bot_client.get_user_characters_grouped(discord_id), bot_client.get_support_classes(),
        )
        support_set = set(support_classes)
        characters = [
            {"character_name": c["character_name"], "character_class": c["character_class"],
             "item_level": c.get("item_level") or 0, "is_support": c["character_class"] in support_set}
            for c in grouped
        ]
    # 관리자가 정한 순서(카테고리 → sort_order → 상단 고정) 그대로 보여준다.
    groups = picker_groups(raids, _max_item_level(characters) or None)
    now = datetime.now(KST)
    preset = {k: request.query_params.get(k, "") for k in
              ("raid", "difficulty", "proficiency", "scheduled_datetime", "memo", "character_name", "role")}
    return templates.TemplateResponse(
        request,
        "party_create.html",
        {
            "user": user,
            "active": "parties",
            "groups": groups,
            # 개설 실패 후 되돌아왔을 때 채워줄 값(쿼리) — 없으면 빈 폼
            "preset": preset,
            "proficiency_options": proficiency_options,
            "characters": characters,
            "recent": recent_openings((history or {}).get("entries") or [], raids, discord_id, now),
            "presets": party_logic.time_presets(now),
            "reset": party_logic.reset_info(None, now),
            "default_prof": next(
                (p["value"] for p in proficiency_options if p["value"] == preset["proficiency"]),
                next((p["value"] for p in proficiency_options if p["value"] == "숙련"),
                     proficiency_options[0]["value"] if proficiency_options else ""),
            ),
            "error": error,
        },
    )


@router.get("/parties/create/check")
async def create_party_check(
    raid_name: str = "", difficulty: str = "", scheduled_datetime: str = "",
    user: dict = Depends(get_current_user),
):
    return JSONResponse(await _create_check_data(user["discord_id"], raid_name, difficulty, scheduled_datetime))


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
        # 실패 화면을 직접 렌더하면 뒤로가기/F5가 개설(디스코드 스레드 생성)을 재시도한다 —
        # 폼으로 되돌리되 고른 값은 그대로 채워준다.
        params = {
            "error": result.get("reason") or "공대를 개설하지 못했습니다.",
            "raid": raid_name, "difficulty": difficulty, "proficiency": proficiency,
            "scheduled_datetime": scheduled_datetime, "memo": memo, "character_name": character_name, "role": role,
        }
        return RedirectResponse("/parties/create?" + urlencode({k: v for k, v in params.items() if v}), status_code=303)

    message_id = result["message_id"]
    character_name = character_name.strip()
    if character_name:
        join_result = await bot_client.join_party(message_id, user["discord_id"], character_name, role)
        if not join_result.get("success"):
            reason = quote(join_result.get("reason") or "선택한 캐릭터로 자동 참여하지 못했습니다.")
            return RedirectResponse(f"/parties/{message_id}?join_error={reason}", status_code=303)

    return RedirectResponse(f"/parties/{message_id}", status_code=303)


# ── 공대 상세 ─────────────────────────────────────────────

async def _detail_context(
    message_id: str, discord_id: str, is_admin: bool = False, admin_mode: bool = False,
) -> dict:
    party = await bot_client.get_party(message_id)
    if not party:
        return {"party": None}

    joined = any(s["discord_id"] == discord_id for s in party["slots"])
    is_actual_leader = party["leader_id"] == discord_id
    # 관리자는 파티장이 아니어도 관리 패널을 쓸 수 있어야 한다(bot 쪽
    # _require_leader_or_admin과 짝) — is_leader를 느슨하게 확장하되, 템플릿에서
    # "당신이 파티장" 대신 "관리자 권한으로 보는 중"이라고 구분해서 보여준다.
    # admin_mode(사이드바 토글)가 꺼져 있으면 관리자여도 일반 참가자로만 본다 —
    # 아무 공대나 열 때마다 관리 패널이 뜨는 걸 막기 위한 화면 전용 스위치.
    ended = party_logic.is_ended(party)
    is_leader = (is_actual_leader or (is_admin and admin_mode)) and not ended
    viewing_as_admin = is_admin and admin_mode and not is_actual_leader
    my_slot = next((s for s in party["slots"] if s["discord_id"] == discord_id), None)
    can_join_view = not joined and not ended
    show_invite = is_leader

    # get_party 이후의 호출은 서로 의존하지 않는다 — 한꺼번에 기다린다.
    calls: dict = {
        "comments": bot_client.get_party_comments(message_id),  # 리더 여부와 무관하게 누구나 볼 수 있다.
        "raids": bot_client.get_raids(),
    }
    if joined and my_slot and my_slot["role"] != "support" and not ended:
        calls["support_classes"] = bot_client.get_support_classes()
    if can_join_view:
        # Discord PartyView._handle_waitlist와 동일한 조건(참여 안 했고 파티가 종료되지 않음)
        calls["eligibility"] = bot_client.get_party_eligibility(message_id, discord_id)
        calls["waitlist"] = bot_client.get_waitlist_status(message_id, discord_id)
    if show_invite:
        calls["invite"] = bot_client.get_invitable_users(message_id, discord_id)
        calls["proficiency"] = bot_client.get_proficiency_options()
    fetched = dict(zip(calls, await asyncio.gather(*calls.values())))

    support_classes = set(fetched.get("support_classes") or [])
    can_switch_to_support = bool(
        joined and my_slot and my_slot["role"] != "support" and my_slot["character_class"] in support_classes
    )
    eligibility = fetched.get("eligibility")
    character_is_support = {}
    on_waitlist = False
    if can_join_view:
        if eligibility and eligibility.get("qualifying"):
            # 자격 있는 캐릭터가 있을 때만 필요하고, 20초 TTL 캐시라 거의 왕복이 없다.
            support_classes = set(await bot_client.get_support_classes())
            character_is_support = {
                q["name"]: q["class"] in support_classes for q in eligibility["qualifying"]
            }
        on_waitlist = fetched["waitlist"]["on_waitlist"]

    invitable_users = []
    invitable_slots = []
    invite_result = fetched.get("invite")
    if invite_result and invite_result.get("success"):
        invitable_users = invite_result["users"]
        invitable_slots = invite_result["available_slots"]

    comments = fetched["comments"]
    raids = fetched["raids"]
    raid_info = raids.get(party["raid_name"], {})
    period = period_view(raid_info["available_until"]) if raid_info.get("available_until") else None
    diff_info = (raid_info.get("difficulties") or {}).get(party["difficulty"], {})
    groups = party_logic.group_layout(party, diff_info.get("party_split"))
    comp = party_logic.composition(party)

    difficulty_options = []
    proficiency_options = []
    if show_invite:
        difficulty_options = list((raid_info.get("difficulties") or {}).keys())
        proficiency_options = fetched["proficiency"]

    my_seat = None
    if my_slot:
        grp = next((g for g in groups if any(s.get("slot_number") == my_slot["slot_number"] for s in g["slots"])), None)
        local = next((s["local_number"] for s in (grp["slots"] if grp else []) if s.get("slot_number") == my_slot["slot_number"]), my_slot["slot_number"])
        my_seat = {"group": grp["group_number"] if grp else 1, "number": local, "multi": len(groups) > 1}

    status_label, status_tone = party_logic.status_view(party)
    return {
        "party": party,
        "view": party_view(party),
        "status_label": status_label,
        "status_tone": status_tone,
        "ended": ended,
        "joined": joined,
        "is_leader": is_leader,
        "is_actual_leader": is_actual_leader,
        "viewing_as_admin": viewing_as_admin,
        "my_slot": my_slot,
        "my_seat": my_seat,
        "can_switch_to_support": can_switch_to_support,
        "eligibility": eligibility,
        "character_is_support": character_is_support,
        "on_waitlist": on_waitlist,
        "invitable_users": invitable_users,
        "invitable_slots": invitable_slots,
        "comments": comments,
        "groups": groups,
        "multi_group": len(groups) > 1,
        "comp": comp,
        "difficulty_options": difficulty_options,
        "proficiency_options": proficiency_options,
        "period": period,
    }


@router.get("/parties/{message_id}")
async def party_detail(
    request: Request,
    message_id: str,
    join_error: str | None = None,
    cancelled: bool = False,
    notice_sent: int | None = None,
    user: dict = Depends(get_current_user),
):
    ctx = await _detail_context(
        message_id, user["discord_id"],
        is_admin=user.get("is_admin", False), admin_mode=user.get("admin_mode", False),
    )
    if join_error:
        action_result = {"success": False, "reason": join_error}
    elif cancelled:
        action_result = {"success": True}
    elif notice_sent is not None:
        action_result = {"success": True, "message": f"{notice_sent}명에게 DM을 보냈습니다."}
    else:
        action_result = None
    return templates.TemplateResponse(
        request,
        "party_detail.html",
        {"user": user, "active": "parties", "action_result": action_result, **ctx},
    )


def _redirect_with_result(
    message_id: str, result: dict, fallback_reason: str, done: str | None = None,
) -> RedirectResponse:
    """액션 결과를 렌더링 대신 redirect로 돌려준다 — POST 응답을 그대로 렌더하면
    뒤로가기 시 브라우저가 "이 페이지를 다시 표시하려면..." 폼 재제출 경고를 띄우고,
    실수로 뒤로 갔다 앞으로 오면 같은 액션(참여/퇴장/강제퇴장 등)이 다시 전송될 수 있다.
    done: 성공 토스트 문구 — 이전엔 실패만 알려주고 성공은 아무 반응이 없었다."""
    if not result.get("success"):
        reason = quote(result.get("reason") or fallback_reason)
        return RedirectResponse(f"/parties/{message_id}?join_error={reason}", status_code=303)
    return redirect_with_toast(f"/parties/{message_id}", done)


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
    return _redirect_with_result(message_id, result, "참여하지 못했습니다.", "공대에 참여했습니다.")


@router.post("/parties/{message_id}/leave")
async def leave(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.leave_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "나가지 못했습니다.", "공대에서 나왔습니다.")


@router.post("/parties/{message_id}/waitlist")
async def toggle_waitlist(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.toggle_waitlist(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "빈자리 알림 설정을 바꾸지 못했습니다.", "빈자리 알림 설정을 바꿨습니다.")


@router.post("/parties/{message_id}/invite")
async def invite(
    request: Request,
    message_id: str,
    target_discord_id: str = Form(...),
    slot_number: int = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.create_invite(message_id, user["discord_id"], target_discord_id, slot_number)
    return _redirect_with_result(message_id, result, "초대를 보내지 못했습니다.", "초대를 보냈습니다. 상대가 1시간 안에 응답하면 슬롯이 채워집니다.")


@router.get("/parties/{message_id}/guest-invite")
async def guest_invite_form(request: Request, message_id: str, user: dict = Depends(get_current_user)):
    """게스트(API 미등록 서버 멤버) 초대 폼 — 디스코드 GuestUserSelectView의 웹판.
    서버 멤버 전체를 훑는 조회라 상세 페이지를 열 때마다 하지 않고, 파티장이
    "게스트 초대" 버튼을 눌렀을 때만 htmx로 불러온다."""
    result = await bot_client.get_guest_candidates(message_id, user["discord_id"], config.DISCORD_GUILD_ID)
    return templates.TemplateResponse(
        request,
        "_guest_invite_form.html",
        {"message_id": message_id, "result": result},
    )


@router.post("/parties/{message_id}/invite-guest")
async def invite_guest(
    request: Request,
    message_id: str,
    target_discord_id: str = Form(...),
    slot_number: int = Form(...),
    user: dict = Depends(get_current_user),
):
    # 초대 자체는 등록 유저 초대와 같은 경로 — 수락하는 쪽(디스코드 DM)에서 API 미등록이면
    # 게스트 흐름(캐릭터 닉네임 입력 → 관리자 키로 조회)으로 이어진다.
    result = await bot_client.create_invite(message_id, user["discord_id"], target_discord_id, slot_number)
    return _redirect_with_result(message_id, result, "게스트 초대를 보내지 못했습니다.", "게스트 초대를 보냈습니다. 상대가 디스코드 DM에서 캐릭터를 입력하면 참여됩니다.")


@router.post("/parties/{message_id}/comments")
async def post_comment(
    request: Request,
    message_id: str,
    content: str = Form(..., max_length=500),
    user: dict = Depends(get_current_user),
):
    discord_id = user["discord_id"]
    avatar_url = user.get("avatar_url") or f"https://cdn.discordapp.com/embed/avatars/{(int(discord_id) >> 22) % 6}.png"
    result = await bot_client.post_party_comment(
        message_id, discord_id, user["username"], avatar_url, content.strip()
    )
    if request.headers.get("HX-Request"):
        return await _comments_partial(request, message_id, user, result, "댓글을 남기지 못했습니다.")
    return _redirect_with_result(message_id, result, "댓글을 남기지 못했습니다.", "댓글을 남겼습니다.")


async def _comments_partial(request: Request, message_id: str, user: dict, result: dict, fallback: str):
    """댓글 등록/삭제를 htmx로 했을 때 — 페이지 전체 대신 댓글 구역만 다시 그린다.
    실패 사유는 X-Toast 헤더로(toast.js가 띄운다)."""
    party, comments = await asyncio.gather(
        bot_client.get_party(message_id), bot_client.get_party_comments(message_id)
    )
    headers = {}
    if not result.get("success"):
        headers = {"X-Toast": quote(result.get("reason") or fallback), "X-Toast-Type": "error"}
    return templates.TemplateResponse(
        request, "_party_comments_list.html",
        {"user": user, "party": party or {"message_id": message_id, "status": "disbanded"}, "comments": comments},
        headers=headers,
    )


@router.post("/parties/{message_id}/comments/{comment_id}/delete")
async def delete_comment(
    request: Request,
    message_id: str,
    comment_id: int,
    user: dict = Depends(get_current_user),
):
    result = await bot_client.delete_party_comment(message_id, comment_id, user["discord_id"])
    if request.headers.get("HX-Request"):
        return await _comments_partial(request, message_id, user, result, "댓글을 삭제하지 못했습니다.")
    return _redirect_with_result(message_id, result, "댓글을 삭제하지 못했습니다.", "댓글을 삭제했습니다.")


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
        return redirect_with_toast(
            f"/parties/{message_id}", eligibility.get("reason") or "지금은 캐릭터를 변경할 수 없습니다.", "error",
        )
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
    return _redirect_with_result(message_id, result, "캐릭터를 변경하지 못했습니다.", "참여 캐릭터를 변경했습니다.")


@router.post("/parties/{message_id}/switch-role")
async def switch_role_submit(
    request: Request,
    message_id: str,
    new_role: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.switch_role(message_id, user["discord_id"], new_role)
    return _redirect_with_result(message_id, result, "역할을 변경하지 못했습니다.", "역할을 변경했습니다.")


@router.post("/parties/{message_id}/close")
async def close_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.close_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "마감하지 못했습니다.", "모집을 마감했습니다.")


@router.post("/parties/{message_id}/reopen")
async def reopen_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.reopen_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "재개하지 못했습니다.", "모집을 다시 열었습니다.")


@router.post("/parties/{message_id}/clear")
async def clear_party(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.clear_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "클리어 처리하지 못했습니다.", "클리어 처리했습니다. 참여자 전원의 이번 주 완료 체크가 자동 반영됐습니다.")


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
    return _redirect_with_result(message_id, result, "강제 퇴장시키지 못했습니다.", "강제 퇴장시켰습니다.")


@router.post("/parties/{message_id}/reschedule")
async def reschedule_party(
    request: Request,
    message_id: str,
    scheduled_datetime: str = Form(...),
    memo: str | None = Form(None),
    user: dict = Depends(get_current_user),
):
    # 메모는 이제 /memo로 따로 저장한다. 예전 폼처럼 memo 필드를 보내면 그대로 반영하고,
    # 필드가 아예 없으면 봇에 memo를 빼고 보내 기존 메모를 유지한다.
    if memo is None:
        result = await bot_client.reschedule_party(message_id, user["discord_id"], scheduled_datetime)
    else:
        result = await bot_client.reschedule_party(
            message_id, user["discord_id"], scheduled_datetime, memo.strip() or None
        )
    return _redirect_with_result(message_id, result, "일정을 변경하지 못했습니다.", "일정을 변경했습니다. 파티원에게 안내가 갑니다.")


@router.post("/parties/{message_id}/memo")
async def update_party_memo(
    request: Request,
    message_id: str,
    memo: str = Form(""),
    user: dict = Depends(get_current_user),
):
    """메모만 저장 — 일정 변경과 달리 파티원에게 DM이 가지 않는다."""
    result = await bot_client.update_party_memo(message_id, user["discord_id"], memo.strip()[:150] or None)
    return _redirect_with_result(message_id, result, "메모를 저장하지 못했습니다.", "메모를 저장했습니다.")


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
    return _redirect_with_result(message_id, result, "파티장을 위임하지 못했습니다.", "파티장을 위임했습니다.")


@router.post("/parties/{message_id}/edit-difficulty")
async def edit_party_difficulty(
    request: Request,
    message_id: str,
    difficulty: str = Form(...),
    proficiency: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.edit_party_difficulty(
        message_id, user["discord_id"], difficulty, proficiency
    )
    return _redirect_with_result(message_id, result, "난이도/숙련도를 변경하지 못했습니다.", "난이도/숙련도를 변경했습니다.")


@router.post("/parties/{message_id}/admin-revert-clear")
async def admin_revert_clear(
    request: Request, message_id: str, user: dict = Depends(require_admin),
):
    """클리어 취소(되돌리기) — 파티장도 못 쓰는 관리자 전용 액션이라 require_admin으로
    이 경로만 따로 막는다(다른 파티 액션들은 관리자·파티장 겸용이라 get_current_user)."""
    # 되살아난 파티가 "모집을 시작했습니다" 알림으로 나가지 않게 폴링 루프에 미리 알린다.
    party_events.note_admin_action(message_id, "revert")
    result = await bot_client.admin_revert_clear(message_id, user["discord_id"])
    if not result.get("success"):
        party_events.clear_admin_hint(message_id)
    return _redirect_with_result(message_id, result, "되돌리지 못했습니다.", "클리어를 되돌렸습니다.")


@router.post("/parties/{message_id}/admin-disband")
async def admin_disband(request: Request, message_id: str, user: dict = Depends(require_admin)):
    """파티 종료(스레드 유지) — 취소(스레드 삭제)와 구분되는 관리자 전용 액션."""
    # 종료도 클리어와 같은 status='disbanded'라, 알림이 "클리어했습니다"로 나가지 않게 미리 알린다.
    party_events.note_admin_action(message_id, "disband")
    result = await bot_client.admin_disband_party(message_id, user["discord_id"])
    if not result.get("success"):
        party_events.clear_admin_hint(message_id)
    return _redirect_with_result(message_id, result, "파티를 종료하지 못했습니다.", "파티를 종료했습니다(스레드는 유지).")


@router.post("/parties/{message_id}/admin-unlock")
async def admin_unlock(request: Request, message_id: str, user: dict = Depends(require_admin)):
    result = await bot_client.admin_unlock_party(message_id, user["discord_id"])
    return _redirect_with_result(message_id, result, "스레드 잠금을 해제하지 못했습니다.", "스레드 잠금을 해제했습니다.")


@router.post("/parties/{message_id}/admin-notify")
async def admin_notify(
    request: Request, message_id: str, content: str = Form(...), user: dict = Depends(require_admin),
):
    result = await bot_client.admin_notify_party(message_id, user["discord_id"], content.strip())
    if result.get("success"):
        return RedirectResponse(f"/parties/{message_id}?notice_sent={result.get('sent', 0)}", status_code=303)
    return _redirect_with_result(message_id, result, "DM을 보내지 못했습니다.")
