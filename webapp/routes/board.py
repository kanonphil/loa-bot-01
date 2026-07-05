"""길드 커뮤니티 게시판 — 목록/작성/상세/댓글/참여/수정/삭제."""
from fastapi import APIRouter, Depends, Form, Request
from starlette.responses import RedirectResponse

from webapp import config
from webapp.auth.dependencies import get_current_user
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()

CATEGORIES = ["이벤트", "공지", "자유"]


@router.get("/board")
async def board_list(
    request: Request, category: str | None = None, user: dict = Depends(get_current_user)
):
    posts = await bot_client.list_board_posts(config.DISCORD_GUILD_ID, category=category)
    return templates.TemplateResponse(
        request,
        "board_list.html",
        {
            "user": user,
            "active": "board",
            "posts": posts,
            "categories": CATEGORIES,
            "selected_category": category,
        },
    )


@router.get("/board/create")
async def board_create_form(
    request: Request, error: str | None = None, user: dict = Depends(get_current_user)
):
    return templates.TemplateResponse(
        request,
        "board_create.html",
        {"user": user, "active": "board", "categories": CATEGORIES, "error": error},
    )


@router.post("/board/create")
async def board_create_submit(
    request: Request,
    title: str = Form(...),
    category: str = Form(...),
    content: str = Form(...),
    scheduled_datetime: str = Form(""),
    user: dict = Depends(get_current_user),
):
    result = await bot_client.create_board_post(
        user["discord_id"], config.DISCORD_GUILD_ID, title.strip(), category,
        content.strip(), scheduled_datetime.strip() or None,
    )
    if not result["success"]:
        return await board_create_form(request, error=result["reason"], user=user)
    return RedirectResponse(f"/board/{result['post_id']}", status_code=303)


async def _detail_context(post_id: int, discord_id: str) -> dict:
    post = await bot_client.get_board_post(post_id)
    if not post:
        return {"post": None}

    is_author = post["author_discord_id"] == discord_id
    joined = any(p["discord_id"] == discord_id for p in post["participants"])
    return {"post": post, "is_author": is_author, "joined": joined}


@router.get("/board/{post_id}")
async def board_detail(request: Request, post_id: int, user: dict = Depends(get_current_user)):
    ctx = await _detail_context(post_id, user["discord_id"])
    return templates.TemplateResponse(
        request, "board_detail.html", {"user": user, "active": "board", **ctx}
    )


@router.post("/board/{post_id}/comment")
async def board_add_comment(
    request: Request,
    post_id: int,
    content: str = Form(...),
    user: dict = Depends(get_current_user),
):
    action_result = await bot_client.add_board_comment(post_id, user["discord_id"], content.strip())
    ctx = await _detail_context(post_id, user["discord_id"])
    return templates.TemplateResponse(
        request,
        "board_detail.html",
        {"user": user, "active": "board", "action_result": action_result, **ctx},
    )


@router.post("/board/{post_id}/join")
async def board_join(request: Request, post_id: int, user: dict = Depends(get_current_user)):
    await bot_client.join_board_post(post_id, user["discord_id"])
    ctx = await _detail_context(post_id, user["discord_id"])
    return templates.TemplateResponse(
        request, "board_detail.html", {"user": user, "active": "board", **ctx}
    )


@router.post("/board/{post_id}/leave")
async def board_leave(request: Request, post_id: int, user: dict = Depends(get_current_user)):
    await bot_client.leave_board_post(post_id, user["discord_id"])
    ctx = await _detail_context(post_id, user["discord_id"])
    return templates.TemplateResponse(
        request, "board_detail.html", {"user": user, "active": "board", **ctx}
    )


@router.post("/board/{post_id}/edit")
async def board_edit(
    request: Request,
    post_id: int,
    title: str = Form(...),
    content: str = Form(...),
    scheduled_datetime: str = Form(""),
    user: dict = Depends(get_current_user),
):
    action_result = await bot_client.update_board_post(
        post_id, user["discord_id"], title.strip(), content.strip(), scheduled_datetime.strip() or None
    )
    ctx = await _detail_context(post_id, user["discord_id"])
    return templates.TemplateResponse(
        request,
        "board_detail.html",
        {"user": user, "active": "board", "action_result": action_result, **ctx},
    )


@router.post("/board/{post_id}/delete")
async def board_delete(request: Request, post_id: int, user: dict = Depends(get_current_user)):
    result = await bot_client.delete_board_post(post_id, user["discord_id"])
    if not result["success"]:
        ctx = await _detail_context(post_id, user["discord_id"])
        return templates.TemplateResponse(
            request,
            "board_detail.html",
            {"user": user, "active": "board", "action_result": result, **ctx},
        )
    return RedirectResponse("/board", status_code=303)
