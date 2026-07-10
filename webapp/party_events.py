"""공대 목록 변경 감지 — 봇 서버를 주기적으로 폴링하는 백그라운드 루프 하나를
공유하고, 변경이 감지되면 구독 중인 모든 SSE 연결(브라우저 탭)에 알려서
새로고침 없이 반영되게 한다. 연결마다 각자 폴링하면 접속자 수만큼 봇 서버
요청이 늘어나므로(원래 불안정했던 봇 서버 보호), 폴링은 프로세스당 1개만 돈다.

같은 폴링 주기에 얹어서 "공대 생성/클리어/게스트 합류" 알림 이벤트도 감지한다
(봇 서버 요청 횟수는 그대로 — 클리어 감지 시 사라진 파티 1건당 상세 재조회만 추가)."""
import asyncio
import hashlib
import logging

from webapp import config, notification_store
from webapp.clients import bot_client

logger = logging.getLogger("webapp.party_events")

POLL_INTERVAL_SECONDS = 10

_subscribers: set[asyncio.Queue] = set()
_last_fingerprint: str | None = None

_notification_subscribers: set[asyncio.Queue] = set()
_last_snapshot: dict[str, dict] | None = None


def _fingerprint(parties: list[dict]) -> str:
    key = "|".join(
        f"{p['message_id']}:{p['status']}:{len(p.get('slots', []))}" for p in parties
    )
    return hashlib.sha1(key.encode()).hexdigest()


def _detect_notification_events(prev: dict[str, dict], current: dict[str, dict]) -> list[dict]:
    """새로 생긴 파티(created)와 게스트가 새로 합류한 파티(guest_joined)를 감지한다.
    사라진 파티(클리어/취소)는 봇 서버 상세 재조회가 필요해 _detect_cleared_events가 처리한다."""
    events: list[dict] = []

    for message_id, party in current.items():
        if message_id not in prev:
            events.append({
                "type": "created",
                "message_id": message_id,
                "text": f"{party.get('raid_name', '')} {party.get('difficulty', '')} 공격대가 모집을 시작했습니다.",
            })
            continue

        prev_discord_ids = {s.get("discord_id") for s in prev[message_id].get("slots", [])}
        for slot in party.get("slots", []):
            if slot.get("is_guest") and slot.get("discord_id") not in prev_discord_ids:
                events.append({
                    "type": "guest_joined",
                    "message_id": message_id,
                    "text": f"{party.get('raid_name', '')} {party.get('difficulty', '')} 공대에 게스트가 합류했습니다.",
                })

    return events


async def _detect_cleared_events(prev: dict[str, dict], current: dict[str, dict]) -> list[dict]:
    """폴링 목록에서 사라진 파티 중 클리어(status='disbanded')된 것만 골라낸다.
    취소/삭제된 파티는 get_party가 None을 반환하므로 자연히 제외된다."""
    events: list[dict] = []
    for message_id in prev.keys() - current.keys():
        try:
            party = await bot_client.get_party(message_id)
        except Exception:
            logger.exception("클리어 감지용 파티 상세 재조회 실패: %s", message_id)
            continue
        if party and party.get("status") == "disbanded":
            events.append({
                "type": "cleared",
                "message_id": message_id,
                "text": f"{party.get('raid_name', '')} {party.get('difficulty', '')} 공대가 클리어했습니다! 🏆",
            })
    return events


async def _poll_once() -> None:
    global _last_fingerprint, _last_snapshot
    parties = await bot_client.list_parties(config.DISCORD_GUILD_ID)
    fingerprint = _fingerprint(parties)
    if _last_fingerprint is not None and fingerprint != _last_fingerprint:
        for queue in list(_subscribers):
            queue.put_nowait(fingerprint)
    _last_fingerprint = fingerprint

    current_snapshot = {p["message_id"]: p for p in parties}
    if _last_snapshot is not None:
        events = _detect_notification_events(_last_snapshot, current_snapshot)
        events += await _detect_cleared_events(_last_snapshot, current_snapshot)
        for event in events:
            saved = await notification_store.add_notification(
                event["type"], event["message_id"], event["text"]
            )
            for queue in list(_notification_subscribers):
                queue.put_nowait(saved)
    _last_snapshot = current_snapshot


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


def subscribe_notifications() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue()
    _notification_subscribers.add(queue)
    return queue


def unsubscribe_notifications(queue: asyncio.Queue) -> None:
    _notification_subscribers.discard(queue)
