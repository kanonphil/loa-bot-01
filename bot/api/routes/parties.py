"""관리자 API(X-API-Key, Electron 관리자 앱) — 파티 관리.

상태를 바꾸는 라우트는 웹/디스코드와 같은 bot/ui/views.py의 _xxx_core 함수를
as_admin=True로 호출한다. 예전엔 여기서 db 함수를 직접 불러서, 클리어가 상태 확인
없이 다시 실행되거나, 취소가 DB만 지우고 스레드를 남기거나, 강퇴/마감/재개/파티장 변경이
DM·임베드 갱신 없이 처리되는 등 디스코드·웹과 결과가 달랐다."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_api_key
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])

# as_admin 경로라 호출자 discord_id는 의미가 없다(권한은 X-API-Key로 이미 확인됨)
_ADMIN_ACTOR = ""


def _bot():
  from bot.api import bot_ref
  return bot_ref.get_bot()


# ── 요청 바디 모델 ─────────────────────────────────────────

class ScheduleBody(BaseModel):
  scheduled_time: str
  scheduled_datetime: str

class MemoBody(BaseModel):
  memo: str | None = None

class LeaderBody(BaseModel):
  new_leader_id: str


# ── 파티 목록 ─────────────────────────────────────────────

@router.get("")
async def get_parties(guild_id: str):
  return await db.get_guild_parties_with_slots(guild_id)


# ── disbanded 이력 ────────────────────────────────────────

@router.get("/history")
async def get_party_history(guild_id: str, limit: int = 50):
  return await db.get_disbanded_parties(guild_id, limit)


# ── 파티 상세 ─────────────────────────────────────────────

@router.get("/{message_id}")
async def get_party(message_id: str):
  party = await db.get_party(message_id)
  if not party:
    return None
  slots = await db.get_party_slots(message_id)
  return {**party, "slots": slots}


# ── 파티 상태 변경 ────────────────────────────────────────

@router.patch("/{message_id}/close")
async def close_party(message_id: str):
  from bot.ui.views import _close_party_core
  return await _close_party_core(_bot(), message_id, _ADMIN_ACTOR, as_admin=True)

@router.patch("/{message_id}/reopen")
async def reopen_party(message_id: str):
  from bot.ui.views import _reopen_party_core
  return await _reopen_party_core(_bot(), message_id, _ADMIN_ACTOR, as_admin=True)

@router.patch("/{message_id}/disband")
async def disband_party(message_id: str):
  from bot.ui.views import _admin_disband_party_core
  return await _admin_disband_party_core(_bot(), message_id, _ADMIN_ACTOR, as_admin=True)


# ── 클리어 ───────────────────────────────────────────────

@router.patch("/{message_id}/clear")
async def clear_party(message_id: str):
  from bot.ui.views import _clear_party_core

  result = await _clear_party_core(_bot(), message_id, _ADMIN_ACTOR, as_admin=True)
  if result.get("success"):
    result["count"] = result.get("cleared_count", 0)  # 관리자 앱 하위호환 필드
  return result


# ── 스레드 잠금 해제 ──────────────────────────────────────

@router.patch("/{message_id}/unlock")
async def unlock_thread(message_id: str):
  from bot.ui.views import _unlock_party_thread

  party = await db.get_party(message_id)
  if not party:
    return {"success": False, "reason": "파티를 찾을 수 없습니다."}
  bot = _bot()
  if not bot:
    return {"success": False, "reason": "봇이 준비되지 않았습니다."}
  ok, reason = await _unlock_party_thread(bot, party)
  return {"success": ok, "reason": reason}


# ── 파티 취소 (완전 삭제) ─────────────────────────────────

@router.delete("/{message_id}")
async def cancel_party(message_id: str):
  from bot.ui.views import _cancel_party_core
  return await _cancel_party_core(_bot(), message_id, _ADMIN_ACTOR, None, as_admin=True)


# ── 일정 변경 ─────────────────────────────────────────────

@router.patch("/{message_id}/schedule")
async def update_schedule(message_id: str, body: ScheduleBody):
  before = await db.get_party(message_id)
  await db.update_party_schedule(message_id, body.scheduled_time, body.scheduled_datetime)
  if before:
    from bot.ui.views import _log_party_admin_action

    await _log_party_admin_action(
      before, _ADMIN_ACTOR, "party.reschedule",
      f"일정 변경 ({before.get('scheduled_time')} → {body.scheduled_time})", as_admin=True,
    )

  from bot.ui.views import _refresh_party_embed_with_reserved

  bot = _bot()
  if bot:
    party = await db.get_party(message_id)
    if party:
      await _refresh_party_embed_with_reserved(bot, party)
      await _rename_party_channel(bot, party, body.scheduled_time)

  return {"success": True}


async def _rename_party_channel(bot, party: dict, scheduled_time: str) -> None:
  """스레드 제목에도 일정이 들어가므로 같이 갱신(웹/디스코드 일정 변경과 같은 제목 형식)."""
  from bot.ui.views import _rename_party_thread

  try:
    await _rename_party_thread(bot, {**party, "scheduled_time": scheduled_time})
  except Exception:
    pass


# ── 메모 변경 ─────────────────────────────────────────────

@router.patch("/{message_id}/memo")
async def update_memo(message_id: str, body: MemoBody):
  await db.update_party_memo(message_id, body.memo)

  from bot.ui.views import _refresh_party_embed_with_reserved

  bot = _bot()
  if bot:
    party = await db.get_party(message_id)
    if party:
      await _refresh_party_embed_with_reserved(bot, party)

  return {"success": True}


# ── 파티원 강제 퇴장 ──────────────────────────────────────

@router.delete("/{message_id}/slots/{discord_id}")
async def kick_member(message_id: str, discord_id: str):
  from bot.ui.views import _kick_member_core
  return await _kick_member_core(_bot(), message_id, _ADMIN_ACTOR, discord_id, as_admin=True)


# ── 파티장 변경 ───────────────────────────────────────────

@router.patch("/{message_id}/leader")
async def change_leader(message_id: str, body: LeaderBody):
  from bot.ui.views import _transfer_leader_core
  return await _transfer_leader_core(_bot(), message_id, _ADMIN_ACTOR, body.new_leader_id, as_admin=True)
