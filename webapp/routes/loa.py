"""로스트아크 공용 데이터 카드의 동작 — 지금은 골드섬 알림 구독 스위치 하나."""
import httpx
from fastapi import APIRouter, Depends, Request
from starlette.responses import JSONResponse

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_home
from webapp.flash import redirect_with_toast

router = APIRouter()


async def _read_enabled(request: Request) -> bool | None:
    """home.js는 JSON 본문 {enabled: bool}, 일반 폼은 enabled=on/true/1."""
    if "application/json" in request.headers.get("content-type", ""):
        try:
            value = (await request.json()).get("enabled")
        except (ValueError, AttributeError):
            return None
        return value if isinstance(value, bool) else None
    value = (await request.form()).get("enabled")
    return None if value is None else str(value).lower() in ("1", "true", "on", "yes")


@router.post("/loa/gold-island-subscription")
async def set_gold_island_subscription(request: Request, user: dict = Depends(get_current_user)):
    as_json = "application/json" in request.headers.get("accept", "")
    enabled = await _read_enabled(request)
    if enabled is None:
        if as_json:
            return JSONResponse({"success": False, "reason": "켜기/끄기 값이 없습니다."}, status_code=400)
        return redirect_with_toast("/main", "켜기/끄기 값이 없습니다.", "error")
    try:
        result = await bot_home.set_gold_island_subscription(user["discord_id"], enabled)
    except httpx.HTTPError:
        result = {"success": False, "reason": "알림 설정을 바꾸지 못했습니다. 잠시 후 다시 시도해주세요."}
    ok = bool(result.get("success"))
    state = bool(result.get("enabled", enabled)) if ok else not enabled
    reason = None if ok else (result.get("reason") or "알림 설정을 바꾸지 못했습니다.")
    if as_json:
        return {"success": ok, "enabled": state, "reason": reason}
    if not ok:
        return redirect_with_toast("/main", reason, "error")
    return redirect_with_toast("/main", "골드섬 알림을 켰습니다." if state else "골드섬 알림을 껐습니다.")
