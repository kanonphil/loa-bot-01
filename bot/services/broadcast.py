"""관리자 수동 DM — 파티원 전체 / 등록 유저 전원.

관리자 API(bot/api/routes/subscriptions.py, X-API-Key)와 웹앱용 internal 라우트
(bot/ui/views.py의 _admin_notify_party_core 등)가 같은 발송 로직을 쓴다."""
from __future__ import annotations

import asyncio
import time

import bot.database.manager as db

# 같은 내용의 전체 공지를 이 시간 안에 다시 보내면 거부 — 웹 요청이 타임아웃 난 뒤
# 재시도하면 전원이 같은 DM을 두 번 받던 문제.
BROADCAST_DEDUP_SECONDS = 600

_last_broadcast: dict = {}       # {"content", "started_at", "sent", "total", "done"}
_broadcast_task: asyncio.Task | None = None


async def _send(bot, discord_id: str, content: str) -> bool:
    try:
        from bot.ui.views import _get_user

        user = await _get_user(bot, discord_id)
        await user.send(content)
        return True
    except Exception:
        return False


async def dm_party_members(bot, message_id: str, content: str) -> tuple[int, int]:
    """(보낸 수, 대상 수)."""
    slots = await db.get_party_slots(message_id)
    sent = 0
    for s in slots:
        if await _send(bot, s["discord_id"], content):
            sent += 1
    return sent, len(slots)


async def dm_all_users(bot, content: str) -> tuple[int, int]:
    """API 등록 유저 전원에게 — (보낸 수, 대상 수)."""
    ids = await db.get_all_user_ids()
    sent = 0
    for discord_id in ids:
        if await _send(bot, discord_id, content):
            sent += 1
    return sent, len(ids)


def broadcast_status() -> dict:
    """마지막 전체 공지의 진행 상황(봇 재시작 전까지만 보관)."""
    return {k: v for k, v in _last_broadcast.items() if k != "content"}


async def start_broadcast(bot, content: str) -> dict:
    """전체 공지를 백그라운드로 시작하고 바로 반환 — 유저 수만큼 DM을 보내는 동안 HTTP
    요청을 붙잡고 있으면 웹앱 타임아웃(60초) 뒤 재시도로 이중 발송이 났다.
    반환: {"success", "reason"?, "total", "queued"}"""
    global _broadcast_task
    now = time.monotonic()
    if _broadcast_task is not None and not _broadcast_task.done():
        return {"success": False, "reason": "이전 전체 공지를 아직 보내는 중입니다. 잠시 후 다시 시도해주세요."}
    if (
        _last_broadcast.get("content") == content
        and now - _last_broadcast.get("started_at", 0) < BROADCAST_DEDUP_SECONDS
    ):
        return {"success": False, "reason": "같은 내용의 공지를 10분 안에 이미 보냈습니다."}

    ids = await db.get_all_user_ids()
    _last_broadcast.clear()
    _last_broadcast.update({"content": content, "started_at": now, "sent": 0, "total": len(ids), "done": False})

    async def run() -> None:
        try:
            for discord_id in ids:
                if await _send(bot, discord_id, content):
                    _last_broadcast["sent"] += 1
        except Exception as e:
            print(f"[전체 공지] 발송 중 오류: {type(e).__name__}: {e}")
        finally:
            _last_broadcast["done"] = True

    _broadcast_task = asyncio.get_running_loop().create_task(run())
    return {"success": True, "queued": True, "total": len(ids)}


async def start_broadcast_and_wait(bot, content: str, wait_seconds: float = 15.0) -> dict:
    """start_broadcast 후 최대 wait_seconds만 기다린다. 그 안에 끝나면 보낸 수까지 담아
    반환(queued=False), 아니면 발송은 계속 진행하고 queued=True로 바로 반환한다."""
    result = await start_broadcast(bot, content)
    if not result.get("success"):
        return result
    task = _broadcast_task
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=wait_seconds)
    except asyncio.TimeoutError:
        return {**result, "sent": _last_broadcast.get("sent", 0)}
    return {"success": True, "queued": False, "sent": _last_broadcast.get("sent", 0), "total": result["total"]}
