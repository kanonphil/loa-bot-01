"""SSE 스트림 공통 루프 — 공대 변경(/events/parties)과 알림(/events/notifications)이 같은 뼈대를 쓴다.
큐에서 항목을 하나씩 받아 render(item)이 돌려준 문자열을 내보내고(None이면 건너뜀), 15초마다
keep-alive 주석을 보내 프록시(Cloudflare)가 유휴 연결을 끊지 않게 한다."""
import asyncio
import inspect

from fastapi import Request

KEEPALIVE_INTERVAL_SECONDS = 15


async def stream(request: Request, queue: asyncio.Queue, unsubscribe, render):
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            chunk = render(item)
            if inspect.isawaitable(chunk):
                chunk = await chunk
            if chunk is not None:
                yield chunk
    finally:
        unsubscribe(queue)
