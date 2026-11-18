"""공대 데이터 실시간 반영 — SSE로 공대 목록 변경을 알려서 대시보드/목록/캘린더가
새로고침 없이 최신 상태를 반영하게 한다.

이벤트 형식: `event: parties-changed` + `data: {"type": "<종류>", "message_id": "<공대 id>"}`
종류: created(새 공대) · reopened(되살아난 공대) · slots(참가자 변동) · status(모집중/마감/완성 전환) ·
details(일정·난이도·메모·파티장 등) · comments(댓글 수만 변동) · cleared(클리어로 사라짐) ·
removed(취소·종료로 사라짐). 페이지마다 자기와 관련 있는 종류만 골라 갱신한다(static/party-live.js)."""
import json
from contextlib import aclosing

from fastapi import APIRouter, Depends, Request
from starlette.responses import StreamingResponse

from webapp import party_events, sse
from webapp.auth.dependencies import get_current_user

router = APIRouter()


def _render(event) -> str:
    payload = event if isinstance(event, dict) else {"type": "changed", "message_id": None}
    return f"event: parties-changed\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream(request: Request):
    queue = party_events.subscribe()
    # aclosing: 바깥 제너레이터가 닫힐 때 안쪽 sse.stream도 같이 닫혀 구독이 확실히 해제된다.
    async with aclosing(sse.stream(request, queue, party_events.unsubscribe, _render)) as inner:
        async for chunk in inner:
            yield chunk


@router.get("/events/parties")
async def party_events_stream(request: Request, user: dict = Depends(get_current_user)):
    return StreamingResponse(_stream(request), media_type="text/event-stream")
