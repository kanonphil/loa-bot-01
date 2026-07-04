import secrets

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from webapp.auth import discord_oauth
from webapp.clients import bot_client

router = APIRouter()


@router.get("/login")
async def login(request: Request):
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    return RedirectResponse(discord_oauth.build_authorize_url(state))


@router.get("/callback")
async def callback(request: Request, code: str, state: str):
    expected_state = request.session.pop("oauth_state", None)
    if not expected_state or expected_state != state:
        return RedirectResponse("/login?error=invalid_state")

    token_data = await discord_oauth.exchange_code(code)
    discord_user = await discord_oauth.fetch_user(token_data["access_token"])
    discord_id = discord_user["id"]

    if not await bot_client.is_registered(discord_id):
        return RedirectResponse("/login?error=not_registered")

    request.session["user"] = {
        "discord_id": discord_id,
        "username": discord_user.get("username"),
    }
    return RedirectResponse("/home")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
