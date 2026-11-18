"""내게 온 파티 초대 — 디스코드는 DM으로 바로 수락/거절 버튼이 오지만, 웹은 홈의 "할 일"에서
받는다(옛 /invites 주소는 홈으로 보낸다). 게스트(API 미등록) 초대는 웹 로그인이 불가하므로
디스코드 DM에서만 응답한다."""
from fastapi import APIRouter, Depends, Form
from starlette.responses import RedirectResponse

from webapp.flash import redirect_result, redirect_with_toast

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.format import invite_expiry_view, schedule_view

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
            "expiry": invite_expiry_view(inv.get("invited_at")),
            "qualifying": qualifying,
            "character_is_support": {q["name"]: q["class"] in support_classes for q in qualifying},
            "can_accept": bool(qualifying) and (eligibility or {}).get("can_join", False),
            "cannot_accept_reason": (eligibility or {}).get("reason"),
        })
    return views


@router.get("/invites")
async def my_invites_page(user: dict = Depends(get_current_user)):
    """초대 전용 화면은 없앴다 — 홈의 "할 일"에서 바로 수락/거절한다. 옛 주소·알림 링크는 홈으로."""
    return RedirectResponse("/main#todo", status_code=303)


@router.post("/invites/{message_id}/accept")
async def accept_invite(
    message_id: str,
    character_name: str = Form(...),
    role: str = Form("dps"),
    user: dict = Depends(get_current_user),
):
    """수락하면 참여한 공대로 바로 보낸다 — 초대함에 남아 "처리되었습니다"만 보여주던 대드엔드 제거."""
    result = await bot_client.accept_invite(message_id, user["discord_id"], character_name, role)
    if not result.get("success"):
        return redirect_result("/main", result, None, "초대를 수락하지 못했습니다.")
    return redirect_with_toast(f"/parties/{message_id}", f"{character_name}로 공대에 참여했습니다.")


@router.post("/invites/{message_id}/decline")
async def decline_invite(message_id: str, user: dict = Depends(get_current_user)):
    result = await bot_client.decline_invite(message_id, user["discord_id"])
    return redirect_result("/main", result, "초대를 거절했습니다.", "초대를 거절하지 못했습니다.")
