"""AI 채팅 라우트 — Gemini API 연동."""
import logging

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from starlette.responses import Response

from webapp import chat_store
from webapp.ai.gemini_client import GeminiError, generate_reply
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()
logger = logging.getLogger("webapp.chat")


async def _get_ai_reply(discord_id: str, history: list[dict], message: str) -> str:
    try:
        characters = await bot_client.get_user_characters(discord_id)
    except Exception:
        logger.exception("캐릭터 정보 조회 실패 (discord_id=%s)", discord_id)
        characters = []

    try:
        return await generate_reply(characters, history, message)
    except GeminiError:
        logger.exception("Gemini 응답 생성 실패")
        return "죄송해요, 지금은 답변을 만들지 못했어요. 잠시 후 다시 시도해주세요."


@router.post("/chat/send")
async def send_message(
    request: Request,
    message: str = Form(...),
    session_id: str | None = Form(None),
    user: dict = Depends(get_current_user),
):
    if session_id:
        if not await chat_store.session_belongs_to(session_id, user["discord_id"]):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="세션을 찾을 수 없습니다."
            )
        history = await chat_store.get_messages(session_id)
        ai_reply = await _get_ai_reply(user["discord_id"], history, message)

        await chat_store.add_message(session_id, "user", message)
        await chat_store.add_message(session_id, "ai", ai_reply)
        return templates.TemplateResponse(
            request,
            "_chat_turn.html",
            {"user_message": message, "ai_message": ai_reply},
        )

    # 세션 없이 온 요청 = 새 채팅 시작
    ai_reply = await _get_ai_reply(user["discord_id"], [], message)

    new_session_id = await chat_store.create_session(user["discord_id"], message)
    await chat_store.add_message(new_session_id, "user", message)
    await chat_store.add_message(new_session_id, "ai", ai_reply)

    response = Response(status_code=200)
    response.headers["HX-Redirect"] = f"/chat/{new_session_id}"
    return response
