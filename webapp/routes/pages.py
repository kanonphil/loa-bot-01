from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from webapp.templating import templates

router = APIRouter()


@router.get("/")
async def index(request: Request):
    if request.session.get("user"):
        return RedirectResponse("/main")
    return templates.TemplateResponse(request, "index.html", {})
