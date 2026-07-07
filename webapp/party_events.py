"""공대 목록 변경 감지 — 봇 서버를 주기적으로 폴링하는 백그라운드 루프 하나를
공유하고, 변경이 감지되면 구독 중인 모든 SSE 연결(브라우저 탭)에 알려서
새로고침 없이 반영되게 한다. 연결마다 각자 폴링하면 접속자 수만큼 봇 서버
요청이 늘어나므로(원래 불안정했던 봇 서버 보호), 폴링은 프로세스당 1개만 돈다."""
import asyncio
import hashlib
import logging

from webapp import config
from webapp.clients import bot_client

logger = logging.getLogger("webapp.party_events")

POLL_INTERVAL_SECONDS = 10

_subscribers: set[asyncio.Queue] = set()
_last_fingerprint: str | None = None


def _fingerprint(parties: list[dict]) -> str:
    key = "|".join(
        f"{p['message_id']}:{p['status']}:{len(p.get('slots', []))}" for p in parties
    )
    return hashlib.sha1(key.encode()).hexdigest()


async def _poll_once() -> None:
    global _last_fingerprint
    parties = await bot_client.list_parties(config.DISCORD_GUILD_ID)
    fingerprint = _fingerprint(parties)
    if _last_fingerprint is not None and fingerprint != _last_fingerprint:
        for queue in list(_subscribers):
            queue.put_nowait(fingerprint)
    _last_fingerprint = fingerprint


async def poll_loop() -> None:
    while True:
        try:
            await _poll_once()
        except Exception:
            logger.exception("공대 목록 폴링 중 오류")
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


def subscribe() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _subscribers.add(queue)
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)
