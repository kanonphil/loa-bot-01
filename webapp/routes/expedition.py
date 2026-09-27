"""원정대 관리 — 웹에서 캐릭터 등록/삭제/아이템레벨 동기화.
Discord의 /캐릭터등록, /캐릭터삭제, "동기화" 버튼과 동일한 봇 내부 로직을 그대로 호출한다."""
from fastapi import APIRouter, Depends, Form, Request

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.flash import redirect_result
from webapp.templating import templates
from webapp.utils import time_ago

router = APIRouter()


async def _page_context(discord_id: str) -> dict:
    characters = await bot_client.get_user_characters_grouped(discord_id)
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
    # 캐릭터 카드 자체는 기존과 동일하게 평탄화된 목록으로도 노출 (기존 템플릿/테스트 호환)
    accounts = await bot_client.list_accounts(discord_id)
    return {"characters": characters, "character_groups": groups, "accounts": accounts}


@router.get("/expedition")
async def expedition_page(request: Request, user: dict = Depends(get_current_user)):
    ctx = await _page_context(user["discord_id"])
    return templates.TemplateResponse(
        request, "expedition.html", {"user": user, "active": "expedition", **ctx}
    )


@router.post("/expedition/add")
async def add_character(
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.add_character(user["discord_id"], character_name)
    if result.get("success") and result.get("character_name"):
        msg = f"{result['character_name']} ({result.get('character_class')} / {result.get('item_level')}) 등록 완료"
    else:
        msg = "캐릭터를 등록했습니다."
    return redirect_result("/expedition", result, msg, "캐릭터를 등록하지 못했습니다.")


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
    뒤로가기/F5가 동기화를 다시 돌리지 않는다. next: 메인 카드 등 다른 곳에서 눌렀을 때 돌아갈 경로."""
    result = await bot_client.sync_characters(user["discord_id"])
    target = next if next.startswith("/") and not next.startswith("//") else "/expedition"
    msg = f"{result.get('updated', 0)}/{result.get('total', 0)}개 캐릭터 동기화 완료"
    return redirect_result(target, result, msg, "동기화하지 못했습니다.")


@router.post("/expedition/add-account")
async def add_account(
    api_key: str = Form(...),
    character_name: str = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.add_account(user["discord_id"], api_key.strip(), character_name.strip())
    msg = f"\"{result.get('label')}\" 계정 등록 완료 (원정대 캐릭터 {result.get('added', 0)}/{result.get('total', 0)}개 추가)"
    return redirect_result("/expedition", result, msg, "계정을 등록하지 못했습니다.")


@router.post("/expedition/remove-account")
async def remove_account(
    key_id: int = Form(...),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.remove_account(user["discord_id"], key_id)
    return redirect_result("/expedition", result, "계정이 삭제되었습니다.", "계정을 찾을 수 없습니다.")
