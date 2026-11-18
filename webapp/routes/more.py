"""더보기 — 왼쪽 메뉴/하단 탭의 4번째 칸. 자주 안 쓰는 화면(알림 설정·계산기·가이드)과
모바일에서 닿을 곳이 없는 관리·로그아웃을 모은다."""
from fastapi import APIRouter, Depends, Request

from webapp.auth.dependencies import get_current_user
from webapp.templating import templates

router = APIRouter()


@router.get("/more")
async def more_page(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse(request, "more.html", {"user": user, "active": "more"})
