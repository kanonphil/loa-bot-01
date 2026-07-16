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
                # 실시간 toast도 유저의 종류 토글/레이드 필터를 따른다
                if discord_id is not None and not await notification_store.event_matches(
                    discord_id, event.get("type"), event.get("raid_name"), event.get("difficulty")
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
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    count = await notification_store.unread_count(user["discord_id"]) if subscribed else 0
    return {"subscribed": subscribed, "count": count}


@router.get("/notifications/panel")
async def notification_panel(request: Request, user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    items = await notification_store.list_unread(user["discord_id"]) if subscribed else []
    read_items = await notification_store.list_read(user["discord_id"]) if subscribed else []
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
    return RedirectResponse(f"/parties/{notif['message_id']}", status_code=303)


@router.get("/settings")
async def settings_page(request: Request, user: dict = Depends(get_current_user)):
    prefs = await notification_store.get_preferences(user["discord_id"])
    # 레이드 필터 추가용 목록 — 봇 서버가 응답 못 하면 추가 UI만 숨긴다(설정 페이지 자체는 동작)
    try:
        raids = await bot_client.get_raids()
    except Exception:
        raids = {}
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "user": user,
            "active": "settings",
            "subscribed": prefs["subscribed"],
            "prefs": prefs,
            "raids": raids,
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
