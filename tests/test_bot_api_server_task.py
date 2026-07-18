"""회귀 테스트: FastAPI(uvicorn) 서버 태스크가 예외로 죽으면 조용히 사라지지 않고
로그를 남겨야 한다. asyncio는 태스크를 약한 참조로만 유지하므로 인스턴스에 참조를
보관하지 않으면 실행 중에도 GC될 수 있다는 문제와 짝을 이루는 안전장치다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio

from bot.bot import LoABot


def test_on_api_server_done_logs_exception(capsys):
    bot = LoABot.__new__(LoABot)  # __init__을 건너뛰고(디스코드 로그인 불필요) 메서드만 검증

    async def _boom():
        raise RuntimeError("포트 충돌")

    async def runner():
        task = asyncio.create_task(_boom())
        await asyncio.sleep(0)  # 태스크가 완료될 시간을 준다
        try:
            await task
        except RuntimeError:
            pass
        bot._on_api_server_done(task)

    asyncio.run(runner())
    captured = capsys.readouterr()
    assert "FastAPI 서버가 예외로 종료됨" in captured.out
    assert "RuntimeError" in captured.out


def test_on_api_server_done_silent_when_cancelled():
    bot = LoABot.__new__(LoABot)

    async def runner():
        task = asyncio.create_task(asyncio.sleep(10))
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        bot._on_api_server_done(task)  # 예외 없이 조용히 반환돼야 한다

    asyncio.run(runner())
