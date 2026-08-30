import secrets

from fastapi import APIRouter, Request
from starlette.responses import RedirectResponse

from webapp import config
from webapp.auth import discord_oauth
from webapp.clients import bot_client
from webapp.templating import templates

router = APIRouter()

# /callback이 붙이는 error 코드별 사용자 안내 문구.
# 이 문구가 없으면(과거 버그) /login이 error를 무시하고 곧장 Discord 인증 화면으로
# 다시 보내서, 미등록 유저나 세션이 깨진 유저가 "승인"을 눌러도 똑같은 화면만
# 반복해서 보는 무한 루프에 빠졌다 — 반드시 여기서 멈추고 사용자에게 알려야 한다.
_LOGIN_ERROR_MESSAGES = {
    "invalid_state": "로그인 세션이 만료되었거나 유효하지 않습니다. 브라우저 쿠키를 확인한 뒤 다시 시도해주세요.",
    "not_registered": "먼저 디스코드에서 /api등록 명령어로 로스트아크 API 키를 등록한 뒤 다시 로그인해주세요.",
}


@router.get("/login")
async def login(request: Request, error: str | None = None):
    if error:
        message = _LOGIN_ERROR_MESSAGES.get(error, "로그인에 실패했습니다. 다시 시도해주세요.")
        return templates.TemplateResponse(request, "index.html", {"login_error": message})
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

    # 파티 스레드 댓글을 웹에서 쓸 때 디스코드로 릴레이(웹훅)할 때 이름/아바타로 쓴다.
    avatar_hash = discord_user.get("avatar")
    if avatar_hash:
        avatar_url = f"https://cdn.discordapp.com/avatars/{discord_id}/{avatar_hash}.png"
    else:
        avatar_url = f"https://cdn.discordapp.com/embed/avatars/{(int(discord_id) >> 22) % 6}.png"

    request.session["user"] = {
        "discord_id": discord_id,
        "username": discord_user.get("username"),
        "is_admin": discord_id in config.ADMIN_DISCORD_IDS,
        "avatar_url": avatar_url,
        # 관리자여도 기본은 꺼둔다 — 아무 공대나 열 때마다 관리 패널이 바로
        # 뜨는 게 번거롭다는 피드백으로, 켜고 싶을 때만 사이드바에서 켠다.
        "admin_mode": False,
    }
    return RedirectResponse("/main")


@router.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
