"""원정대 관리 — 웹에서 캐릭터 등록/삭제/아이템레벨 동기화.
Discord의 /캐릭터등록, /캐릭터삭제, "동기화" 버튼과 동일한 봇 내부 로직을 그대로 호출한다."""
import asyncio

import httpx

from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import JSONResponse

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.flash import DEFAULT_FAILURE, redirect_result, redirect_with_toast, with_toast
from webapp.templating import templates
from webapp.utils import safe_local_path, time_ago

router = APIRouter()


PENDING_MESSAGE = "동기화가 오래 걸려 뒤에서 계속 진행 중입니다. 잠시 뒤 새로고침하면 반영됩니다."


def _wants_json(request: Request) -> bool:
    """exp.js가 인라인 오류를 그리려고 fetch로 보낸 요청 — 리다이렉트 대신 {success, reason, redirect}를 돌려준다.
    JS가 없으면 기존처럼 303 + 토스트."""
    return "application/json" in request.headers.get("accept", "")


def _respond(request: Request, path: str, result: dict, success_message: str | None, fallback: str = DEFAULT_FAILURE):
    if not _wants_json(request):
        return redirect_result(path, result, success_message, fallback)
    ok = bool(result.get("success"))
    message = success_message if ok else (result.get("reason") or fallback)
    return JSONResponse(
        {"success": ok, "reason": None if ok else message, "redirect": with_toast(path, message, "success" if ok else "error") if message else path}
    )


async def _combat_power_map(discord_id: str) -> dict[str, dict]:
    """캐릭터 이름 → {value, growth}. 원정대 목록 응답에 전투력이 없어 랭킹 캐시(로스트아크 API 미호출)에서 내 것만 뽑는다.
    랭킹을 못 읽으면 빈 값 — 전투력 칸만 '—'로 비고 화면은 그대로 뜬다."""
    try:
        data = await bot_client.get_ranking("combat_power", limit=500)
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, dict] = {}
    for e in data.get("entries") or []:
        if str(e.get("discord_id")) == str(discord_id):
            out[e.get("character_name")] = {"value": e.get("value", e.get("combat_power")), "growth": e.get("cp_growth_7d")}
    return out


async def _page_context(discord_id: str) -> dict:
    characters, accounts, cp_map = await asyncio.gather(
        bot_client.get_user_characters_grouped(discord_id),
        bot_client.list_accounts(discord_id),
        _combat_power_map(discord_id),
    )
    for c in characters:
        cp = cp_map.get(c.get("character_name"))
        c.setdefault("item_level", None)
        if c.get("combat_power") is None:
            c["combat_power"] = cp["value"] if cp else None
        c["cp_growth_7d"] = c.get("cp_growth_7d", cp["growth"] if cp else None)
        c["synced_ago"] = time_ago(c.get("cached_at")) if c.get("cached_at") else ""
    groups: list[dict] = []
    seen_labels: dict[str, dict] = {}
    for c in characters:
        label = c.get("account_label") or "기타"
        group = seen_labels.get(label)
        if group is None:
            group = {"label": label, "characters": []}
            seen_labels[label] = group
            groups.append(group)
        group["characters"].append(c)
    for group in groups:
        # 매일 04시 자동 동기화가 있다는 걸 모르면 "왜 레벨이 옛날 거냐"가 된다 — 최근 갱신 시각을 보여준다
        latest = max((c.get("cached_at") or "" for c in group["characters"]), default="")
        group["last_sync"] = time_ago(latest) if latest else ""
        group["last_sync_at"] = latest  # 올리면 한국 시간 전체(<time title>)
    # 캐릭터 카드 자체는 기존과 동일하게 평탄화된 목록으로도 노출 (기존 템플릿/테스트 호환)
    return {"characters": characters, "character_groups": groups, "accounts": accounts}


@router.get("/expedition")
async def expedition_page(request: Request, user: dict = Depends(get_current_user)):
    ctx = await _page_context(user["discord_id"])
    return templates.TemplateResponse(
        request, "expedition.html", {"user": user, "active": "expedition", **ctx}
    )


@router.post("/expedition/add")
async def add_character(
    request: Request,
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.add_character(user["discord_id"], character_name.strip())
    if result.get("success") and result.get("character_name"):
        msg = f"{result['character_name']} ({result.get('character_class')} / {result.get('item_level')}) 등록 완료"
    else:
        msg = "캐릭터를 등록했습니다."
    return _respond(request, "/expedition", result, msg, "캐릭터를 등록하지 못했습니다.")


@router.post("/expedition/remove")
async def remove_character(
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.remove_character(user["discord_id"], character_name)
    return redirect_result("/expedition", result, f"{character_name} 캐릭터를 삭제했습니다.", "캐릭터를 삭제하지 못했습니다.")


@router.post("/expedition/sync")
async def sync_characters(next: str = Form("/expedition"), user: dict = Depends(get_current_user)):
    """동기화는 캐릭터 수만큼 로스트아크 API를 돌아 수 초 걸린다 — 결과를 렌더하지 않고 redirect 해야
    뒤로가기/F5가 동기화를 다시 돌리지 않는다. next: 메인 카드 등 다른 곳에서 눌렀을 때 돌아갈 경로.
    봇이 시간 안에 못 끝내면 pending: true로 응답하고 뒤에서 계속 돈다 — 실패가 아니라 안내로 보여 준다."""
    target = safe_local_path(next, "/expedition")
    try:
        result = await bot_client.sync_characters(user["discord_id"])
    except httpx.TimeoutException:
        # 웹이 기다리는 20초를 넘겨도 봇은 계속 돌고 있다
        return redirect_with_toast(target, PENDING_MESSAGE, "info")
    if result.get("pending"):
        return redirect_with_toast(target, PENDING_MESSAGE, "info")
    msg = f"{result.get('updated', 0)}/{result.get('total', 0)}개 캐릭터 동기화 완료"
    return redirect_result(target, result, msg, "동기화하지 못했습니다.")


@router.post("/expedition/add-account")
async def add_account(
    request: Request,
    api_key: str = Form(...),
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.add_account(user["discord_id"], api_key.strip(), character_name.strip())
    msg = f"\"{result.get('label')}\" 계정 등록 완료 (원정대 캐릭터 {result.get('added', 0)}/{result.get('total', 0)}개 추가)"
    return _respond(request, "/expedition", result, msg, "계정을 등록하지 못했습니다.")


@router.post("/expedition/remove-account")
async def remove_account(
    key_id: int = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.remove_account(user["discord_id"], key_id)
    return redirect_result("/expedition", result, "계정이 삭제되었습니다.", "계정을 찾을 수 없습니다.")
