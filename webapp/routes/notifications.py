"""공대 알림(생성/클리어/게스트 합류) — 전 유저 실시간 toast 브로드캐스트(SSE) +
구독자용 종 아이콘 이력/알림 설정."""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, StreamingResponse

from webapp import notification_store, party_events
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates
from webapp.utils import time_ago as _time_ago

router = APIRouter()

KEEPALIVE_INTERVAL_SECONDS = 15


async def _stream(request: Request, discord_id: str | None = None):
    queue = party_events.subscribe_notifications()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS)
                # 개인 알림은 받는 사람에게만, 전체 이벤트는 유저의 종류 토글/레이드 필터대로
                target = event.get("target_discord_id")
                if target and target != discord_id:
                    continue
                if discord_id is not None and not await notification_store.event_matches(
                    discord_id, event.get("type"), event.get("raid_name"), event.get("difficulty"),
                    targeted=bool(target),
                ):
                    continue
                yield f"event: notification\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        party_events.unsubscribe_notifications(queue)


@router.get("/events/notifications")
async def notification_stream(request: Request, user: dict = Depends(get_current_user)):
    return StreamingResponse(_stream(request, user["discord_id"]), media_type="text/event-stream")


@router.get("/notifications/count")
async def notification_count(user: dict = Depends(get_current_user)):
    """구독하지 않은 유저도 본인 앞으로 온 개인 알림(초대/강퇴 등)은 세어준다."""
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    count = await notification_store.unread_count(user["discord_id"], personal_only=not subscribed)
    return {"subscribed": subscribed, "count": count}


@router.get("/notifications/panel")
async def notification_panel(request: Request, user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    items = await notification_store.list_unread(user["discord_id"], personal_only=not subscribed)
    read_items = await notification_store.list_read(user["discord_id"], personal_only=not subscribed)
    for item in items + read_items:
        item["time_ago"] = _time_ago(item.get("created_at"))
    return templates.TemplateResponse(
        request,
        "_notification_panel.html",
        {"subscribed": subscribed, "items": items, "read_items": read_items},
    )


@router.post("/notifications/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    """종 아이콘을 열면 호출 — 안 읽은 알림을 전부 읽음 처리하고 남은 안읽음 수(0)를 반환."""
    await notification_store.mark_all_read(user["discord_id"])
    return {"count": 0}


@router.get("/notifications/{notification_id}/open")
async def open_notification(notification_id: int, user: dict = Depends(get_current_user)):
    notif = await notification_store.mark_read(user["discord_id"], notification_id)
    if not notif:
        return RedirectResponse("/parties", status_code=303)
    if notif["type"] == "invited":
        return RedirectResponse("/invites", status_code=303)
    if not notif.get("message_id"):
        return RedirectResponse("/parties", status_code=303)
    return RedirectResponse(f"/parties/{notif['message_id']}", status_code=303)


@router.get("/settings")
async def settings_page(
    request: Request, saved: str | None = None, error: str | None = None,
    user: dict = Depends(get_current_user),
):
    prefs = await notification_store.get_preferences(user["discord_id"])
    # 봇 쪽 데이터(레이드 목록/디스코드 구독/사전 알림)는 봇 서버가 응답 못 하면 그 카드만
    # 비활성으로 보여준다 — 설정 페이지 자체(웹 알림 설정)는 계속 동작해야 한다.
    raids: dict = {}
    discord_subscriptions: list[dict] | None = None
    pre_notify: dict | None = None
    try:
        raids = await bot_client.get_raids()
        discord_subscriptions = await bot_client.get_raid_subscriptions(user["discord_id"])
        pre_notify = await bot_client.get_preferences(user["discord_id"])
    except Exception:
        pass
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "active": "settings",
            "subscribed": prefs["subscribed"],
            "prefs": prefs,
            "raids": raids,
            "discord_subscriptions": discord_subscriptions,
            "pre_notify": pre_notify,
            "saved": saved,
            "error": error,
        },
    )


@router.post("/notifications/subscribe")
async def toggle_subscribe(user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    await notification_store.set_subscribed(user["discord_id"], not subscribed)
    return RedirectResponse("/settings", status_code=303)


@router.post("/notifications/preferences")
async def save_type_preferences(request: Request, user: dict = Depends(get_current_user)):
    """종류별(모집/클리어/게스트 합류) on/off — 체크박스 폼이라 체크된 것만 넘어온다."""
    form = await request.form()
    await notification_store.set_type_preferences(
        user["discord_id"],
        created="created" in form,
        cleared="cleared" in form,
        guest_joined="guest_joined" in form,
        personal="personal" in form,
    )
    return RedirectResponse("/settings", status_code=303)


@router.post("/notifications/raid-filters/add")
async def add_raid_filter(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    raid_name = (form.get("raid_name") or "").strip()
    difficulty = (form.get("difficulty") or "").strip() or None  # 빈 값 = 모든 난이도
    if raid_name:
        await notification_store.add_raid_filter(user["discord_id"], raid_name, difficulty)
    return RedirectResponse("/settings", status_code=303)


@router.post("/notifications/raid-filters/remove")
async def remove_raid_filter(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    raid_name = (form.get("raid_name") or "").strip()
    difficulty = (form.get("difficulty") or "").strip() or None
    if raid_name:
        await notification_store.remove_raid_filter(user["discord_id"], raid_name, difficulty)
    return RedirectResponse("/settings", status_code=303)


# ── 디스코드 DM 레이드 구독(/레이드구독) + 사전 알림 — 봇 DB에 저장되는 설정 ────
# 웹 알림(위)과 디스코드 DM 구독은 저장소가 달라 서로 몰랐다. 여기서 같은 설정 페이지에
# 나란히 보여주고 관리한다(저장소를 합치진 않는다 — 디스코드 명령어가 계속 그 테이블을 쓴다).

@router.post("/settings/discord-subscriptions/add")
async def add_discord_subscription(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    raid_name = (form.get("raid_name") or "").strip()
    difficulty = (form.get("difficulty") or "").strip() or "전체"
    if raid_name:
        result = await bot_client.add_raid_subscription(user["discord_id"], raid_name, difficulty)
        if not result.get("success"):
            return RedirectResponse(f"/settings?error={_q(result.get('reason') or '구독하지 못했습니다.')}", status_code=303)
    return RedirectResponse("/settings?saved=subscription", status_code=303)


@router.post("/settings/discord-subscriptions/remove")
async def remove_discord_subscription(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    raid_name = (form.get("raid_name") or "").strip()
    difficulty = (form.get("difficulty") or "").strip() or "전체"
    if raid_name:
        await bot_client.remove_raid_subscription(user["discord_id"], raid_name, difficulty)
    return RedirectResponse("/settings", status_code=303)


@router.post("/settings/pre-notify")
async def save_pre_notify(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    try:
        hours = float(form.get("pre_notify_hours") or 0)
    except ValueError:
        hours = 0.0
    result = await bot_client.set_pre_notify_hours(user["discord_id"], hours)
    if not result.get("success"):
        return RedirectResponse(f"/settings?error={_q(result.get('reason') or '저장하지 못했습니다.')}", status_code=303)
    return RedirectResponse("/settings?saved=pre_notify", status_code=303)


def _q(text: str) -> str:
    from urllib.parse import quote

    return quote(text)
