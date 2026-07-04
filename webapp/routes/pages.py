from fastapi import APIRouter, Depends, HTTPException, Request, status

from webapp import chat_store
from webapp.auth.dependencies import get_current_user
from webapp.content.greetings import random_welcome
from webapp.templating import templates

router = APIRouter()


@router.get("/")
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {})


@router.get("/home")
async def home(request: Request, user: dict = Depends(get_current_user)):
    recent_sessions = await chat_store.list_sessions(user["discord_id"])
    welcome_message = random_welcome(user["username"])
    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "user": user,
            "welcome_message": welcome_message,
            "active": "home",
            "recent_sessions": recent_sessions,
            "active_session_id": None,
        },
    )


@router.get("/chat/{session_id}")
async def chat_thread(
    request: Request, session_id: str, user: dict = Depends(get_current_user)
):
    if not await chat_store.session_belongs_to(session_id, user["discord_id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없습니다.")

    messages = await chat_store.get_messages(session_id)
    recent_sessions = await chat_store.list_sessions(user["discord_id"])
    return templates.TemplateResponse(
        request,
        "chat_thread.html",
        {
            "user": user,
            "messages": messages,
            "session_id": session_id,
            "recent_sessions": recent_sessions,
            "active_session_id": session_id,
            "active": "home",
        },
    )
