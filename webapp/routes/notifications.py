"""공대 알림(생성/클리어/게스트 합류) — 전 유저 실시간 toast 브로드캐스트(SSE) +
구독자용 종 아이콘 이력/알림 설정."""
import asyncio
import json

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse, StreamingResponse

from webapp import notification_store, party_events
from webapp.auth.dependencies import get_current_user
from webapp.templating import templates

router = APIRouter()

KEEPALIVE_INTERVAL_SECONDS = 15


async def _stream(request: Request):
    queue = party_events.subscribe_notifications()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS)
                yield f"event: notification\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        party_events.unsubscribe_notifications(queue)


@router.get("/events/notifications")
async def notification_stream(request: Request, user: dict = Depends(get_current_user)):
    return StreamingResponse(_stream(request), media_type="text/event-stream")


@router.get("/notifications/count")
async def notification_count(user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    count = await notification_store.unread_count(user["discord_id"]) if subscribed else 0
    return {"subscribed": subscribed, "count": count}


@router.get("/notifications/panel")
async def notification_panel(request: Request, user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    items = await notification_store.list_unread(user["discord_id"]) if subscribed else []
    return templates.TemplateResponse(
        request, "_notification_panel.html", {"subscribed": subscribed, "items": items}
    )


@router.get("/notifications/{notification_id}/open")
async def open_notification(notification_id: int, user: dict = Depends(get_current_user)):
    notif = await notification_store.mark_read(user["discord_id"], notification_id)
    if not notif:
        return RedirectResponse("/parties", status_code=303)
    return RedirectResponse(f"/parties/{notif['message_id']}", status_code=303)


@router.get("/settings")
async def settings_page(request: Request, user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    return templates.TemplateResponse(
        request, "settings.html", {"user": user, "active": "settings", "subscribed": subscribed}
    )


@router.post("/notifications/subscribe")
async def toggle_subscribe(user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    await notification_store.set_subscribed(user["discord_id"], not subscribed)
    return RedirectResponse("/settings", status_code=303)
