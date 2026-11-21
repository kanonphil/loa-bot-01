import logging
import time

import httpx
from fastapi import Depends, HTTPException, Request, status

from webapp import config
from webapp.clients import bot_client

logger = logging.getLogger("webapp.auth")


class NotAuthenticated(HTTPException):
    """세션에 로그인된 유저가 없을 때. main.py에서 /login 리다이렉트로 변환."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_401_UNAUTHORIZED, detail="로그인이 필요합니다.")


class NotAdmin(HTTPException):
    """로그인은 했지만 관리자가 아닐 때."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail="관리자만 접근할 수 있습니다.")


class AdminModeOff(HTTPException):
    """관리자지만 관리자 모드(사이드바 스위치)가 꺼져 있을 때 — main.py에서 홈 + 안내 토스트로 바꾼다."""

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail="관리자 모드를 켜야 사용할 수 있습니다.")


# 세션 쿠키는 서명만 된 채 30일 유지되고 서버가 무효화할 수 없다 — 그래서 로그인 시점의 "등록됨"·
# "관리자" 판정이 그대로 남아, 유저가 삭제되거나 관리자에서 빠져도 계속 접근할 수 있었다.
# 요청마다 (1) 관리자 여부는 설정에서 다시 계산하고 (2) 등록 여부는 봇에 물어보되 유저별로
# 짧게 캐시해 봇 호출을 분당 1회 이하로 줄인다.
REGISTRATION_TTL_SECONDS = 60
_registration_cache: dict[str, tuple[float, bool]] = {}


def remember_registered(discord_id: str, registered: bool = True) -> None:
    """로그인 직후처럼 방금 확인한 결과를 캐시에 넣는다(바로 뒤 요청에서 또 묻지 않도록)."""
    _registration_cache[discord_id] = (time.monotonic(), registered)


def clear_registration_cache() -> None:
    _registration_cache.clear()


async def _still_registered(discord_id: str) -> bool:
    cached = _registration_cache.get(discord_id)
    if cached is not None and time.monotonic() - cached[0] < REGISTRATION_TTL_SECONDS:
        return cached[1]
    try:
        registered = await bot_client.is_registered(discord_id)
    except httpx.HTTPError:
        # 봇 서버가 죽었다고 모든 유저를 로그아웃시키지는 않는다 — 기존 세션을 유지하고 캐시하지 않는다.
        logger.warning("등록 여부 재확인 실패 — 기존 세션을 유지합니다: %s", discord_id, exc_info=True)
        return True
    remember_registered(discord_id, registered)
    return registered


async def get_current_user(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise NotAuthenticated()
    discord_id = user.get("discord_id")
    if not discord_id or not await _still_registered(discord_id):
        request.session.clear()
        raise NotAuthenticated()
    is_admin = discord_id in config.ADMIN_DISCORD_IDS
    if user.get("is_admin") != is_admin:
        user["is_admin"] = is_admin
        if not is_admin:
            user["admin_mode"] = False
        request.session["user"] = user
    return user


def require_admin_account(user: dict = Depends(get_current_user)) -> dict:
    """관리자 목록에 있는지만 본다 — 관리자 모드 스위치 자체(켜기/끄기)에만 쓴다."""
    if not user.get("is_admin"):
        raise NotAdmin()
    return user


def require_admin(user: dict = Depends(require_admin_account)) -> dict:
    """관리 화면·관리자 전용 액션 — 관리자이면서 관리자 모드가 켜져 있어야 한다.
    예전엔 스위치가 화면 노출만 바꾸고 꺼짐이어도 /admin 주소로 들어가 쓸 수 있었다."""
    if not user.get("admin_mode"):
        raise AdminModeOff()
    return user
