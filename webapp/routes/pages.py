from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from webapp.templating import templates

router = APIRouter()


@router.get("/guide")
async def guide(request: Request):
    """디스코드 /가이드의 웹판. 아직 /api등록을 못 해 로그인이 막힌 사람도 읽을 수 있어야
    하므로 로그인 없이 열린다(세션이 있으면 사이드바에 그대로 붙는다)."""
    return templates.TemplateResponse(
        request, "guide.html", {"user": request.session.get("user"), "active": "guide"}
    )


@router.get("/")
async def index(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/main")
    return templates.TemplateResponse(request, "index.html", {})
