"""공대 알림(생성/클리어/게스트 합류) — 전 유저 실시간 toast 브로드캐스트(SSE) +
구독자용 종 아이콘 이력/알림 설정."""
import asyncio
import json
from contextlib import aclosing

from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse

from webapp import notification_store, party_events, sse
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client, bot_exp
from webapp.flash import redirect_result, redirect_with_toast
from webapp.templating import templates
from webapp.utils import time_ago as _time_ago

router = APIRouter()


async def _stream(request: Request, discord_id: str | None = None):
    queue = party_events.subscribe_notifications()

    async def render(event):
        # 개인 알림은 받는 사람에게만, 전체 이벤트는 유저의 종류 토글/레이드 필터대로
        target = event.get("target_discord_id")
        if target and target != discord_id:
            return None
        if discord_id is not None and not await notification_store.event_matches(
            discord_id, event.get("type"), event.get("raid_name"), event.get("difficulty"),
            targeted=bool(target),
        ):
            return None
        return f"event: notification\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    async with aclosing(sse.stream(request, queue, party_events.unsubscribe_notifications, render)) as inner:
        async for chunk in inner:
            yield chunk


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
    # 읽음 목록을 먼저 뽑고 → 안 읽음 목록을 뽑고 → 방금 뽑은 안 읽음만 읽음 처리한다. 예전엔 패널 조회와
    # read-all이 따로 날아가 읽음 처리가 먼저 커밋되면 새 알림이 "읽음" 탭에 들어가 버렸다.
    # items는 이 요청에서 처음 보여주는(= 아직 안 읽은) 알림이라 템플릿이 "새 알림"으로 그린다.
    read_items = await notification_store.list_read(user["discord_id"], personal_only=not subscribed)
    items = await notification_store.list_unread(user["discord_id"], personal_only=not subscribed)
    await notification_store.mark_read_ids(user["discord_id"], [item["id"] for item in items])
    for item in items + read_items:
        item["time_ago"] = _time_ago(item.get("created_at"))
    return templates.TemplateResponse(
        request,
        "_notification_panel.html",
        {
            "subscribed": subscribed,
            "items": items,
            "read_items": read_items,
            "new_ids": [item["id"] for item in items],
        },
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
        return RedirectResponse("/main#todo", status_code=303)  # 초대는 홈 "할 일"에서 수락/거절
    if notif["type"] in ("cancelled", "kicked"):
        # 취소된 파티는 이미 삭제됐고, 강퇴된 파티는 들어갈 수 없다 — 목록으로
        return redirect_with_toast("/parties", notif.get("text") or "", "info")
    if not notif.get("message_id"):
        return RedirectResponse("/parties", status_code=303)
    return RedirectResponse(f"/parties/{notif['message_id']}", status_code=303)


@router.get("/settings")
async def settings_page(
    request: Request, user: dict = Depends(get_current_user),
):
    prefs = await notification_store.get_preferences(user["discord_id"])
    # 봇 쪽 데이터(레이드 목록/디스코드 구독/사전 알림)는 봇 서버가 응답 못 하면 그 카드만
    # 비활성으로 보여준다 — 설정 페이지 자체(웹 알림 설정)는 계속 동작해야 한다.
    # 세 호출은 서로 무관해 동시에 보내고, 각각 실패해도 그 카드만 비운다(return_exceptions).
    raids_r, subs_r, pre_r, overview = await asyncio.gather(
        bot_client.get_raids(),
        bot_client.get_raid_subscriptions(user["discord_id"]),
        bot_client.get_preferences(user["discord_id"]),
        bot_exp.get_loa_overview(user["discord_id"]),  # 골드섬 구독 여부 — 실패하면 None(스위치만 비활성)
        return_exceptions=True,
    )
    if isinstance(overview, BaseException):
        overview = None
    gold = {
        "known": overview is not None and "gold_island_subscribed" in overview,
        "subscribed": bool((overview or {}).get("gold_island_subscribed")),
        "available": (overview or {}).get("available"),
    }
    raids: dict = {} if isinstance(raids_r, BaseException) else raids_r
    discord_subscriptions: list[dict] | None = None if isinstance(subs_r, BaseException) else subs_r
    pre_notify: dict | None = None if isinstance(pre_r, BaseException) else pre_r
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
            "gold": gold,
        },
    )


@router.post("/notifications/subscribe")
async def toggle_subscribe(user: dict = Depends(get_current_user)):
    subscribed = await notification_store.is_subscribed(user["discord_id"])
    await notification_store.set_subscribed(user["discord_id"], not subscribed)
    return redirect_with_toast("/settings", "알림 구독을 해제했습니다." if subscribed else "알림을 구독했습니다.")


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
    return redirect_with_toast("/settings", "알림 종류를 저장했습니다.")


@router.post("/notifications/raid-filters/add")
async def add_raid_filter(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    raid_name = (form.get("raid_name") or "").strip()
    difficulty = (form.get("difficulty") or "").strip() or None  # 빈 값 = 모든 난이도
    # 실제 있는 레이드·난이도만 저장한다 — 예전엔 임의 문자열을 길이 제한 없이 저장했다
    if raid_name:
        raids = await bot_client.get_raids()
        known = raids.get(raid_name)
        if known is None or (difficulty and difficulty not in (known.get("difficulties") or {})):
            return redirect_with_toast("/settings", "없는 레이드입니다.", "error")
        await notification_store.add_raid_filter(user["discord_id"], raid_name, difficulty)
    return redirect_with_toast("/settings", f"{raid_name} 필터를 추가했습니다." if raid_name else None)


@router.post("/notifications/raid-filters/remove")
async def remove_raid_filter(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    raid_name = (form.get("raid_name") or "").strip()
    difficulty = (form.get("difficulty") or "").strip() or None
    if raid_name:
        await notification_store.remove_raid_filter(user["discord_id"], raid_name, difficulty)
    return redirect_with_toast("/settings", "필터를 삭제했습니다." if raid_name else None)


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
        return redirect_result("/settings", result, "디스코드 DM 구독을 추가했습니다.", "구독하지 못했습니다.")
    return redirect_with_toast("/settings")


@router.post("/settings/discord-subscriptions/remove")
async def remove_discord_subscription(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    raid_name = (form.get("raid_name") or "").strip()
    difficulty = (form.get("difficulty") or "").strip() or "전체"
    if raid_name:
        result = await bot_client.remove_raid_subscription(user["discord_id"], raid_name, difficulty)
        return redirect_result("/settings", result, "디스코드 DM 구독을 취소했습니다.", "구독을 취소하지 못했습니다.")
    return redirect_with_toast("/settings")


@router.post("/settings/pre-notify")
async def save_pre_notify(request: Request, user: dict = Depends(get_current_user)):
    form = await request.form()
    try:
        hours = float(form.get("pre_notify_hours") or 0)
    except ValueError:
        hours = 0.0
    result = await bot_client.set_pre_notify_hours(user["discord_id"], hours)
    return redirect_result("/settings", result, "사전 알림 설정을 저장했습니다.", "저장하지 못했습니다.")


@router.post("/settings/gold-island")
async def save_gold_island(request: Request, user: dict = Depends(get_current_user)):
    """골드섬 10분 전 DM 구독 켜기/끄기. 스위치(exp.js)는 fetch + JSON으로, JS 없이 제출하면 303 + 토스트."""
    form = await request.form()
    enabled = (form.get("enabled") or "").strip() in ("1", "true", "on")
    result = await bot_exp.set_gold_island_subscription(user["discord_id"], enabled)
    message = ("골드섬 알림을 켰습니다." if enabled else "골드섬 알림을 껐습니다.") if result.get("success") else (
        result.get("reason") or "저장하지 못했습니다. 잠시 후 다시 시도해주세요."
    )
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"success": bool(result.get("success")), "reason": None if result.get("success") else message, "message": message})
    return redirect_with_toast("/settings", message, "success" if result.get("success") else "error")
