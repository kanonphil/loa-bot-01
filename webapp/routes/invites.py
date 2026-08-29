"""내게 온 파티 초대 — 디스코드는 DM으로 바로 수락/거절 버튼이 오지만, 웹은 로그인한
유저가 볼 수 있는 목록 화면이 있어야 한다. 등록된 유저 초대만 지원(v1) — 게스트
초대는 디스코드 네이티브 유저피커에 상응하는 웹 UI가 없어 이번 범위에서 제외."""
from fastapi import APIRouter, Depends, Form, Request

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.format import schedule_view
from webapp.templating import templates

router = APIRouter()


async def _build_invite_views(discord_id: str) -> list[dict]:
    invites = await bot_client.get_my_invites(discord_id)
    views = []
    for inv in invites:
        eligibility = await bot_client.get_party_eligibility(inv["message_id"], discord_id)
        qualifying = (eligibility or {}).get("qualifying") or []
        support_classes = set(await bot_client.get_support_classes()) if qualifying else set()
        views.append({
            **inv,
            "schedule": schedule_view(inv.get("scheduled_datetime"), inv.get("scheduled_time")),
            "qualifying": qualifying,
            "character_is_support": {q["name"]: q["class"] in support_classes for q in qualifying},
            "can_accept": bool(qualifying) and (eligibility or {}).get("can_join", False),
            "cannot_accept_reason": (eligibility or {}).get("reason"),
        })
    return views


@router.get("/invites")
async def my_invites_page(request: Request, user: dict = Depends(get_current_user)):
    invite_views = await _build_invite_views(user["discord_id"])
    return templates.TemplateResponse(
        request, "invites.html", {"user": user, "active": "invites", "invites": invite_views}
    )


@router.post("/invites/{message_id}/accept")
async def accept_invite(
    request: Request,
    message_id: str,
    character_name: str = Form(...),
    role: str = Form("dps"),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.accept_invite(message_id, user["discord_id"], character_name, role)
    invite_views = await _build_invite_views(user["discord_id"])
    return templates.TemplateResponse(
        request,
        "invites.html",
        {"user": user, "active": "invites", "invites": invite_views, "action_result": result},
    )


@router.post("/invites/{message_id}/decline")
async def decline_invite(
    request: Request, message_id: str, user: dict = Depends(get_current_user)
):
    result = await bot_client.decline_invite(message_id, user["discord_id"])
    invite_views = await _build_invite_views(user["discord_id"])
    return templates.TemplateResponse(
        request,
        "invites.html",
        {"user": user, "active": "invites", "invites": invite_views, "action_result": result},
    )
