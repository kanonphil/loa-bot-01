"""캐릭터 상세 정보 — 스킬/트라이포드/룬, 아크패시브, 장신구 품질/연마, 보석."""
from fastapi import APIRouter, Depends, Request

from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()


@router.get("/characters/{character_name}")
async def character_detail(
    request: Request,
    character_name: str,
    discord_id: str | None = None,
    user: dict = Depends(get_current_user),
):
    # discord_id를 안 넘기면(원정대 관리에서 들어온 경우) 내 캐릭터로 간주.
    # 공대 모집의 "자세히 보기"처럼 다른 사람 캐릭터를 볼 때만 명시적으로 넘어온다.
    owner_discord_id = discord_id or user["discord_id"]
    detail = await bot_client.get_armory_detail(owner_discord_id, character_name)
    return templates.TemplateResponse(
        request,
        "character_detail.html",
        {"user": user, "active": "expedition", "character_name": character_name, "detail": detail},
    )


@router.get("/party-member-card")
async def party_member_card(
    request: Request, discord_id: str, character_name: str, user: dict = Depends(get_current_user)
):
    """공대 모집 화면에서 파티원 위에 마우스를 올렸을 때 뜨는 간단 요약 카드.
    전체 정보는 캐릭터 상세 페이지(/characters/{name})에 이미 있으니, 여기선 한눈에
    볼 핵심(전투력/아이템레벨/장신구 품질 요약)만 컴팩트하게 보여준다."""
    detail = await bot_client.get_armory_detail(discord_id, character_name)
    return templates.TemplateResponse(
        request,
        "_party_member_card.html",
        {"discord_id": discord_id, "detail": detail},
    )
