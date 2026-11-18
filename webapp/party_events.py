"""공대 목록 변경 감지 — 봇 서버를 주기적으로 폴링하는 백그라운드 루프 하나를
공유하고, 변경이 감지되면 구독 중인 모든 SSE 연결(브라우저 탭)에 알려서
새로고침 없이 반영되게 한다. 연결마다 각자 폴링하면 접속자 수만큼 봇 서버
요청이 늘어나므로(원래 불안정했던 봇 서버 보호), 폴링은 프로세스당 1개만 돈다.

같은 폴링 주기에 얹어서 "공대 생성/클리어/게스트 합류" 알림 이벤트도 감지한다
(봇 서버 요청 횟수는 그대로 — 클리어 감지 시 사라진 파티 1건당 상세 재조회만 추가).

SSE로 나가는 이벤트는 {"type", "message_id"}이고, 페이지가 자기와 관련된 종류만 골라 갱신한다
(종류 목록은 routes/events.py 참고). 예전엔 "뭔가 바뀜" 신호 하나뿐이라 댓글 하나에도 열린 모든 탭이
전체 페이지를 다시 받았다."""
import asyncio
import hashlib
import logging
import time

from webapp import config, notification_store
from webapp.clients import bot_client

logger = logging.getLogger("webapp.party_events")

POLL_INTERVAL_SECONDS = 10

# 봇 알림 큐(web_notifications) 커서를 저장하는 키 — 재시작 사이에 온 알림을 놓치지 않으려고 DB에 둔다.
CURSOR_KEY = "web_notification_cursor"
# 목록에서 사라진 파티의 상세 재조회가 실패했을 때 다시 시도하는 횟수 상한
MAX_VANISH_RETRIES = 6
# "관리자가 웹에서 방금 한 동작" 힌트 유효 시간(초)
ADMIN_HINT_TTL_SECONDS = 120
_SEEN_LIMIT = 3000

_subscribers: set[asyncio.Queue] = set()
_last_fingerprint: str | None = None

_notification_subscribers: set[asyncio.Queue] = set()
_last_snapshot: dict[str, dict] | None = None
# 봇이 보낸 DM/공지의 웹 복사본(web_notifications) 커서 — None이면 아직 첫 조회 전.
_last_web_notification_id: int | None = None

# 지금까지 목록에서 본 적 있는 파티 id — 새로 나타난 파티가 "처음 생긴 것"인지 "클리어 되돌리기 등으로
# 되살아난 것"인지 구분하는 데 쓴다(되살아난 파티는 "모집을 시작했습니다" 알림을 내지 않는다).
_seen_ids: dict[str, None] = {}
# 목록에서 사라졌지만 상세 재조회에 실패해 아직 클리어/취소를 판정하지 못한 파티 → 시도 횟수
_pending_vanished: dict[str, int] = {}
# 저장에 실패해 다음 폴링에서 다시 저장할 알림 이벤트(저장 성공한 것은 빠진다 → 중복 없음)
_pending_events: list[dict] = []
# 웹에서 관리자가 한 동작 힌트 — 클리어와 "파티 종료(스레드 유지)"는 둘 다 status='disbanded'라 상태만으로는
# 구분되지 않는다. message_id → (종류, 시각)
_admin_hints: dict[str, tuple[str, float]] = {}


def note_admin_action(message_id: str, kind: str) -> None:
    """kind: 'disband'(관리자 파티 종료 — 클리어 알림을 내지 않는다) | 'revert'(클리어 되돌리기 — 모집 시작 알림을 내지 않는다)."""
    _admin_hints[message_id] = (kind, time.monotonic())


def clear_admin_hint(message_id: str) -> None:
    _admin_hints.pop(message_id, None)


def _take_hint(message_id: str) -> str | None:
    hint = _admin_hints.pop(message_id, None)
    if hint and time.monotonic() - hint[1] <= ADMIN_HINT_TTL_SECONDS:
        return hint[0]
    return None


def _fingerprint(parties: list[dict]) -> str:
    """상태·인원수만 보면 일정/난이도/메모/파티장/캐릭터 변경이 열린 탭에 반영되지
    않았다(한 명 나가고 한 명 들어오면 인원수도 그대로). 화면에 보이는 필드와 슬롯
    구성 전체를 지문에 넣는다."""
    parts = []
    for p in parties:
        parts.append(f"{p['message_id']}:{p['status']}:{_detail_sig(p)}:{p.get('comment_count')}:{_slots_sig(p)}")
    return hashlib.sha1("|".join(parts).encode()).hexdigest()


def _slots_sig(p: dict) -> str:
    return ",".join(
        f"{s.get('slot_number')}/{s.get('discord_id')}/{s.get('character_name')}/{s.get('role')}"
        for s in p.get("slots", [])
    )


def _detail_sig(p: dict) -> str:
    return (
        f"{p.get('scheduled_datetime')}:{p.get('total_slots')}:{p.get('difficulty')}:{p.get('proficiency')}:"
        f"{p.get('leader_id')}:{p.get('memo')}:{p.get('waitlist_count')}"
    )


def _detect_change_events(prev: dict[str, dict], current: dict[str, dict]) -> list[dict]:
    """SSE로 보낼 변경 이벤트 — 파티당 최대 1개(가장 큰 변경 하나). 사라진 파티는 여기서 다루지 않는다
    (클리어/취소 판정에 상세 재조회가 필요해 _resolve_vanished가 처리)."""
    events: list[dict] = []
    for message_id, party in current.items():
        old = prev.get(message_id)
        if old is None:
            kind = "reopened" if message_id in _seen_ids else "created"
            events.append({"type": kind, "message_id": message_id})
        elif old.get("status") != party.get("status"):
            events.append({"type": "status", "message_id": message_id})
        elif _slots_sig(old) != _slots_sig(party):
            events.append({"type": "slots", "message_id": message_id})
        elif _detail_sig(old) != _detail_sig(party):
            events.append({"type": "details", "message_id": message_id})
        elif old.get("comment_count") != party.get("comment_count"):
            events.append({"type": "comments", "message_id": message_id})
    return events


def _detect_notification_events(
    prev: dict[str, dict], current: dict[str, dict], reopened: set[str] | frozenset = frozenset(),
) -> list[dict]:
    """새로 생긴 파티(created)와 게스트가 새로 합류한 파티(guest_joined)를 감지한다.
    reopened: 새로 나타났지만 사실은 되살아난 파티(클리어 되돌리기 등) — "모집 시작" 알림에서 뺀다.
    사라진 파티(클리어/취소)는 봇 서버 상세 재조회가 필요해 _resolve_vanished가 처리한다."""
    events: list[dict] = []

    for message_id, party in current.items():
        if message_id not in prev:
            if message_id in reopened:
                continue
            events.append({
                "type": "created",
                "message_id": message_id,
                "text": f"{party.get('raid_name', '')} {party.get('difficulty', '')} 공격대가 모집을 시작했습니다.",
                "raid_name": party.get("raid_name"),
                "difficulty": party.get("difficulty"),
            })
            continue

        prev_discord_ids = {s.get("discord_id") for s in prev[message_id].get("slots", [])}
        for slot in party.get("slots", []):
            if slot.get("is_guest") and slot.get("discord_id") not in prev_discord_ids:
                events.append({
                    "type": "guest_joined",
                    "message_id": message_id,
                    "text": f"{party.get('raid_name', '')} {party.get('difficulty', '')} 공대에 게스트가 합류했습니다.",
                    "raid_name": party.get("raid_name"),
                    "difficulty": party.get("difficulty"),
                })

    return events


def _broadcast(event: dict) -> None:
    for queue in list(_subscribers):
        queue.put_nowait(event)


async def _resolve_vanished(ids: set[str]) -> tuple[list[dict], list[dict]]:
    """목록에서 사라진 파티가 클리어인지 취소/종료인지 판정한다.
    반환: (SSE 이벤트, 알림 이벤트). 상세 재조회가 실패한 파티는 다음 폴링에서 다시 시도한다
    (예전엔 그 파티의 클리어 알림이 조용히 사라졌다)."""
    sse_events: list[dict] = []
    notif_events: list[dict] = []
    for message_id in sorted(ids):
        try:
            party = await bot_client.get_party(message_id)
        except Exception:
            attempts = _pending_vanished.get(message_id, 0) + 1
            logger.exception("사라진 파티 상세 재조회 실패(%d회): %s", attempts, message_id)
            if attempts < MAX_VANISH_RETRIES:
                _pending_vanished[message_id] = attempts
            else:
                _pending_vanished.pop(message_id, None)
            if attempts == 1:
                # 목록은 지금 바로 갱신돼야 한다 — 클리어 여부는 판정되는 대로 따로 알린다.
                sse_events.append({"type": "removed", "message_id": message_id})
            continue
        _pending_vanished.pop(message_id, None)
        hint = _take_hint(message_id)
        if party and party.get("status") == "disbanded" and hint != "disband":
            sse_events.append({"type": "cleared", "message_id": message_id})
            notif_events.append({
                "type": "cleared",
                "message_id": message_id,
                "text": f"{party.get('raid_name', '')} {party.get('difficulty', '')} 공대가 클리어했습니다!",
                "raid_name": party.get("raid_name"),
                "difficulty": party.get("difficulty"),
            })
        else:
            sse_events.append({"type": "removed", "message_id": message_id})
    return sse_events, notif_events


async def _flush_pending_events() -> None:
    """저장에 성공한 알림부터 하나씩 큐에서 빼고, 실패하면 멈춘다 — 다음 폴링이 이어서 저장한다."""
    while _pending_events:
        event = _pending_events[0]
        try:
            saved = await notification_store.add_notification(
                event["type"],
                event["message_id"],
                event["text"],
                raid_name=event.get("raid_name"),
                difficulty=event.get("difficulty"),
            )
        except Exception:
            logger.exception("알림 저장 실패 — 다음 폴링에서 다시 시도합니다: %s", event.get("message_id"))
            return
        _pending_events.pop(0)
        for queue in list(_notification_subscribers):
            queue.put_nowait(saved)


async def _poll_once() -> None:
    global _last_fingerprint, _last_snapshot
    parties = await bot_client.list_parties(config.DISCORD_GUILD_ID)
    _last_fingerprint = _fingerprint(parties)
    current_snapshot = {p["message_id"]: p for p in parties}

    prev = _last_snapshot
    if prev is not None:
        reopened = {
            mid for mid in current_snapshot.keys() - prev.keys()
            if mid in _seen_ids or _take_hint(mid) == "revert"
        }
        sse_events = _detect_change_events(prev, current_snapshot)
        _pending_events.extend(_detect_notification_events(prev, current_snapshot, reopened))

        for mid in list(_pending_vanished):
            if mid in current_snapshot:
                _pending_vanished.pop(mid, None)  # 다시 목록에 나타났다 — 판정할 필요 없음
        vanished = (prev.keys() - current_snapshot.keys()) | set(_pending_vanished)
        vanished_sse, vanished_notifs = await _resolve_vanished(vanished)
        sse_events += vanished_sse
        _pending_events.extend(vanished_notifs)

        for event in sse_events:
            _broadcast(event)

    # 스냅샷은 바로 앞으로 보낸다 — 저장 못 한 알림은 _pending_events가, 판정 못 한 사라진 파티는
    # _pending_vanished가 들고 있으므로 다음 폴링에서 중복 없이 이어진다.
    _last_snapshot = current_snapshot
    for mid in current_snapshot:
        _seen_ids[mid] = None
    while len(_seen_ids) > _SEEN_LIMIT:
        _seen_ids.pop(next(iter(_seen_ids)))

    await _flush_pending_events()
    await _ingest_web_notifications()


async def _persist_cursor() -> None:
    try:
        await notification_store.set_state(CURSOR_KEY, str(_last_web_notification_id))
    except Exception:
        logger.exception("웹 알림 커서 저장 실패")


async def _ingest_web_notifications() -> None:
    """봇이 DM으로 보낸 개인 알림(초대/강퇴/위임/일정·난이도 변경/빈자리/파티 완성/시작
    시간)을 같은 폴링 주기에 가져와 본인 앞으로 온 알림으로 저장하고 toast로 흘린다.
    커서는 DB에 저장한다 — 메모리에만 두면 웹앱이 재시작되는 동안 온 알림이 영영 안 들어왔다.
    저장된 커서가 없는 첫 조회(최초 배포)만 현재 최신 id로 커서를 잡는다."""
    global _last_web_notification_id
    if _last_web_notification_id is None:
        try:
            stored = await notification_store.get_state(CURSOR_KEY)
        except Exception:
            logger.exception("웹 알림 커서 읽기 실패")
            stored = None
        if stored is not None and stored.lstrip("-").isdigit():
            _last_web_notification_id = int(stored)
    try:
        feed = await bot_client.get_web_notifications(_last_web_notification_id)
    except Exception:
        logger.exception("웹 알림 큐 조회 실패")
        return
    latest = int(feed.get("latest_id") or 0)
    if _last_web_notification_id is None:
        _last_web_notification_id = latest
        await _persist_cursor()
        return
    if latest < _last_web_notification_id:
        # 봇 DB가 초기화돼 id가 되감겼다 — 커서를 맞추지 않으면 이후 알림을 영영 못 받는다.
        _last_web_notification_id = latest
        await _persist_cursor()
    items = feed.get("items", [])
    for item in items:
        try:
            saved = await notification_store.add_notification(
                item["kind"], item.get("message_id") or "", item["text"],
                target_discord_id=item["discord_id"],
            )
        except Exception:
            logger.exception("웹 알림 저장 실패 — 다음 폴링에서 이 알림부터 다시 시도합니다")
            return
        for queue in list(_notification_subscribers):
            queue.put_nowait(saved)
        if item.get("id") is not None:
            _last_web_notification_id = max(_last_web_notification_id, int(item["id"]))
            await _persist_cursor()
    if not items and latest > _last_web_notification_id:
        _last_web_notification_id = latest
        await _persist_cursor()


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
