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
  import discord as _discord
  from bot.api import bot_ref
  from bot.ui.embeds import party_embed

  party = await db.get_party(message_id)
  if not party:
    return {"success": False, "reason": "파티를 찾을 수 없습니다."}
  slots = await db.get_party_slots(message_id)
  if not slots:
    return {"success": False, "reason": "파티원이 없습니다."}

  count = await db.complete_raid_for_party(message_id)
  await db.disband_party(message_id)

  # Discord embed 갱신 + 클리어 메시지 발송
  bot = bot_ref.get_bot()
  if bot:
    try:
      channel = bot.get_channel(int(party["channel_id"]))
      if channel is None:
        channel = await bot.fetch_channel(int(party["channel_id"]))
      # 잠긴/아카이브된 스레드는 먼저 열어야 메시지 발송 가능
      if getattr(channel, 'locked', False) or getattr(channel, 'archived', False):
        await channel.edit(archived=False, locked=False)
      msg = await channel.fetch_message(int(message_id))
      cleared_party = {**party, "status": "disbanded"}
      await msg.edit(embed=party_embed(cleared_party, slots), view=None)
      raid_title = f"{party['raid_name']} {party['difficulty']}"
      mentions   = " ".join(f"<@{s['discord_id']}>" for s in slots)
      await channel.send(
        f"🏆 **{raid_title}** 클리어!\n{mentions}\n"
        f"파티원 **{count}명**의 레이드 체크가 완료되었습니다."
      )
      try:
        await channel.edit(archived=True, locked=True)
      except _discord.HTTPException:
        pass
    except (_discord.NotFound, _discord.Forbidden, _discord.HTTPException):
      pass

  return {"success": True, "count": count}


# ── 스레드 잠금 해제 ──────────────────────────────────────

@router.patch("/{message_id}/unlock")
async def unlock_thread(message_id: str):
  import discord as _discord
  from bot.api import bot_ref

  party = await db.get_party(message_id)
  if not party:
    return {"success": False, "reason": "파티를 찾을 수 없습니다."}

  bot = bot_ref.get_bot()
  if not bot:
    return {"success": False, "reason": "봇이 준비되지 않았습니다."}

  try:
    channel = bot.get_channel(int(party["channel_id"]))
    if channel is None:
      channel = await bot.fetch_channel(int(party["channel_id"]))
    await channel.edit(archived=False, locked=False)
    return {"success": True}
  except (_discord.NotFound, _discord.Forbidden):
    return {"success": False, "reason": "채널을 찾을 수 없거나 권한이 없습니다."}
  except _discord.HTTPException as e:
    return {"success": False, "reason": str(e)}


# ── 파티 취소 (완전 삭제) ─────────────────────────────────

@router.delete("/{message_id}")
async def cancel_party(message_id: str):
  await db.purge_party(message_id)
  return {"success": True}


# ── 일정 변경 ─────────────────────────────────────────────

@router.patch("/{message_id}/schedule")
async def update_schedule(message_id: str, body: ScheduleBody):
  await db.update_party_schedule(message_id, body.scheduled_time, body.scheduled_datetime)

  from bot.api import bot_ref
  from bot.ui.views import _refresh_party_embed_with_reserved

  bot = bot_ref.get_bot()
  if bot:
    party = await db.get_party(message_id)
    if party:
      await _refresh_party_embed_with_reserved(bot, party)
      await _rename_party_channel(bot, party, body.scheduled_time)

  return {"success": True}


async def _rename_party_channel(bot, party: dict, scheduled_time: str) -> None:
  """스레드 제목에도 일정이 들어가므로, 봇의 /일정변경 커맨드와 동일하게 같이 갱신."""
  import discord as _discord
  from bot.data.raids import RAIDS

  try:
    channel = bot.get_channel(int(party["channel_id"]))
    if channel is None:
      channel = await bot.fetch_channel(int(party["channel_id"]))
    raid_info = RAIDS.get(party["raid_name"], {})
    short_name = raid_info.get("short_name", party["raid_name"])
    new_name = f"{short_name} {party['difficulty']} {party['proficiency']} — {scheduled_time}"
    await channel.edit(name=new_name)
  except (_discord.NotFound, _discord.Forbidden, _discord.HTTPException):
    pass


# ── 메모 변경 ─────────────────────────────────────────────

@router.patch("/{message_id}/memo")
async def update_memo(message_id: str, body: MemoBody):
  await db.update_party_memo(message_id, body.memo)

  from bot.api import bot_ref
  from bot.ui.views import _refresh_party_embed_with_reserved

  bot = bot_ref.get_bot()
  if bot:
    party = await db.get_party(message_id)
    if party:
      await _refresh_party_embed_with_reserved(bot, party)

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
