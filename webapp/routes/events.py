"""공대 데이터 실시간 반영 — SSE로 공대 목록 변경을 알려서 대시보드/목록/캘린더가
새로고침 없이 최신 상태를 반영하게 한다."""
import asyncio

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from webapp import party_events
from webapp.auth.dependencies import get_current_user

router = APIRouter()

KEEPALIVE_INTERVAL_SECONDS = 15


async def _stream(request: Request):
    queue = party_events.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_INTERVAL_SECONDS)
                yield "event: parties-changed\ndata: changed\n\n"
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
    finally:
        party_events.unsubscribe(queue)


@router.get("/events/parties")
async def party_events_stream(request: Request, user: dict = Depends(get_current_user)):
    return StreamingResponse(_stream(request), media_type="text/event-stream")
