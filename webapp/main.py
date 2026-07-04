import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from starlette.staticfiles import StaticFiles

from webapp import chat_store, config
from webapp.auth.dependencies import NotAuthenticated
from webapp.routes import auth_routes, chat, dashboard, expedition, pages, party, raid_check

logger = logging.getLogger("webapp")

CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60  # 6시간마다 보관기간 지난 대화 정리


async def _cleanup_loop() -> None:
    while True:
        try:
            deleted = await chat_store.delete_expired_sessions(config.CHAT_RETENTION_DAYS)
            if deleted:
                logger.info("만료된 채팅 세션 %d개 삭제 (보관기간 %d일)", deleted, config.CHAT_RETENTION_DAYS)
        except Exception:
            logger.exception("채팅 세션 자동 정리 중 오류")
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await chat_store.init_db()
    cleanup_task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()


app = FastAPI(title="로아봇 웹", lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=config.SESSION_SECRET,
    same_site="lax",
    https_only=config.SESSION_HTTPS_ONLY,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

app.include_router(auth_routes.router)
app.include_router(pages.router)
app.include_router(chat.router)
app.include_router(dashboard.router)
app.include_router(expedition.router)
app.include_router(raid_check.router)
app.include_router(party.router)


@app.exception_handler(NotAuthenticated)
async def not_authenticated_handler(request, exc):
    return RedirectResponse("/login")


@app.get("/health")
async def health():
    return {"status": "ok"}
