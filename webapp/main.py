import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from webapp import config, guild_info, notification_store, party_events
from webapp.clients import bot_client
from webapp.auth.dependencies import NotAuthenticated
from webapp.routes import (
    admin,
    auth_routes,
    calendar,
    character,
    dashboard,
    events,
    expedition,
    notifications,
    pages,
    party,
    raid_check,
    ranking,
    tools,
)
from webapp.templating import templates

logger = logging.getLogger("webapp")

CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60  # 6시간마다 보관기간 지난 알림 정리


async def _cleanup_loop() -> None:
    while True:
        try:
            deleted = await notification_store.delete_expired(config.NOTIFICATION_RETENTION_DAYS)
            if deleted:
                logger.info("만료된 알림 %d개 삭제 (보관기간 %d일)", deleted, config.NOTIFICATION_RETENTION_DAYS)
        except Exception:
            logger.exception("알림 자동 정리 중 오류")
        try:
            # 주간 리셋(수요일 06:00 KST)이 지나면 전주 공대 알림을 자동으로 비운다.
            purged = await notification_store.delete_before_week_reset()
            if purged:
                logger.info("전주 공대 알림 %d개 삭제 (주간 리셋)", purged)
        except Exception:
            logger.exception("주간 알림 정리 중 오류")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await notification_store.init_db()
    await guild_info.refresh()
    cleanup_task = asyncio.create_task(_cleanup_loop())
    party_poll_task = asyncio.create_task(party_events.poll_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        party_poll_task.cancel()
        await bot_client.aclose()


app = FastAPI(title="로아봇 웹", lifespan=lifespan)

templates.env.globals["get_guild_name"] = guild_info.get_name
templates.env.globals["get_guild_icon_url"] = guild_info.get_icon_url
# 정적 파일(CSS/JS) 캐시 무효화용 — 프로세스 시작 시각을 쿼리스트링에 붙인다.
# 이게 없으면 CSS를 고쳐서 재배포해도 브라우저/Cloudflare가 예전 파일을 계속
# 캐시해서, 실제로는 반영됐는데 사용자 눈에는 안 바뀐 것처럼 보이는 문제가 있었다.
templates.env.globals["static_version"] = str(int(time.time()))

app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    same_site="lax",
    https_only=config.SESSION_HTTPS_ONLY,
    max_age=config.SESSION_MAX_AGE_DAYS * 24 * 60 * 60,
    domain=config.SESSION_COOKIE_DOMAIN,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_routes.router)
app.include_router(pages.router)
app.include_router(dashboard.router)
app.include_router(expedition.router)
app.include_router(character.router)
app.include_router(raid_check.router)
app.include_router(ranking.router)
app.include_router(party.router)
app.include_router(calendar.router)
app.include_router(tools.router)
app.include_router(events.router)
app.include_router(notifications.router)
app.include_router(admin.router)


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request, exc):
    return RedirectResponse("/login")


@app.get("/health")
async def health():
    return {"status": "ok"}
