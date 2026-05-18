from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_api_key
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])


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
  parties = await db.get_guild_parties(guild_id)
  result = []
  for party in parties:
    slots = await db.get_party_slots(party["message_id"])
    result.append({**party, "slots": slots})
  return result


# ── 파티 상세 ─────────────────────────────────────────────

@router.get("/{message_id}")
async def get_party(message_id: str):
  party = await db.get_party(message_id)
  if not party:
    return None
  slots = await db.get_party_slots(message_id)
  return {**party, "slots": slots}


# ── disbanded 이력 ────────────────────────────────────────

@router.get("/history")
async def get_party_history(guild_id: str, limit: int = 50):
  return await db.get_disbanded_parties(guild_id, limit)


# ── 파티 상태 변경 ────────────────────────────────────────

@router.patch("/{message_id}/close")
async def close_party(message_id: str):
  await db.close_party(message_id)
  return {"success": True}

@router.patch("/{message_id}/reopen")
async def reopen_party(message_id: str):
  await db.reopen_party(message_id)
  return {"success": True}

@router.patch("/{message_id}/disband")
async def disband_party(message_id: str):
  await db.disband_party(message_id)
  return {"success": True}


# ── 클리어 ───────────────────────────────────────────────

@router.patch("/{message_id}/clear")
async def clear_party(message_id: str):
  party = await db.get_party(message_id)
  if not party or party["status"] == "disbanded":
    return {"success": False, "reason": "이미 종료된 파티입니다."}
  slots = await db.get_party_slots(message_id)
  if not slots:
    return {"success": False, "reason": "파티원이 없습니다."}
  count = await db.complete_raid_for_party(message_id)
  await db.disband_party(message_id)
  return {"success": True, "count": count}


# ── 파티 취소 (완전 삭제) ─────────────────────────────────

@router.delete("/{message_id}")
async def cancel_party(message_id: str):
  await db.purge_party(message_id)
  return {"success": True}


# ── 일정 변경 ─────────────────────────────────────────────

@router.patch("/{message_id}/schedule")
async def update_schedule(message_id: str, body: ScheduleBody):
  await db.update_party_schedule(message_id, body.scheduled_time, body.scheduled_datetime)
  return {"success": True}


# ── 메모 변경 ─────────────────────────────────────────────

@router.patch("/{message_id}/memo")
async def update_memo(message_id: str, body: MemoBody):
  await db.update_party_memo(message_id, body.memo)
  return {"success": True}


# ── 파티원 강제 퇴장 ──────────────────────────────────────

@router.delete("/{message_id}/slots/{discord_id}")
async def kick_member(message_id: str, discord_id: str):
  removed = await db.leave_slot(message_id, discord_id)
  return {"success": removed}


# ── 파티장 변경 ───────────────────────────────────────────

@router.patch("/{message_id}/leader")
async def change_leader(message_id: str, body: LeaderBody):
  await db.transfer_leader(message_id, body.new_leader_id)
  return {"success": True}
