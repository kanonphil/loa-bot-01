"""
웹앱(별도 서버)이 로그인 시 호출하는 내부 전용 API.
X-Webapp-Key로만 인증하며, 관리자 API(X-API-Key)와는 분리되어 있다.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_webapp_key
import bot.api.lostark as loa
import bot.database.manager as db
from bot.services.expedition import register_character_auto_detect, sync_characters_for_discord_id

router = APIRouter(dependencies=[Depends(verify_webapp_key)])


@router.get("/verify-user")
async def verify_user(discord_id: str):
  """discord_id가 /api등록을 마친 계정인지 확인. 웹 로그인 게이트에 사용."""
  registered = await db.user_exists(discord_id)
  return {"discord_id": discord_id, "registered": registered}


@router.get("/user-characters")
async def user_characters(discord_id: str):
  """AI 상담 프롬프트에 넣을 캐릭터 정보(직업·아이템레벨 등). 캐시된 값 그대로 반환."""
  return await db.get_cached_characters(discord_id, max_age_hours=99999)


@router.get("/user-characters-grouped")
async def user_characters_grouped(discord_id: str):
  """웹 원정대 페이지용 — 캐릭터 목록 + 소속 계정 라벨(account_label).
  부계정이 있으면 페이지에서 계정별로 묶어 보여준다."""
  return await db.get_cached_characters_with_account(discord_id, max_age_hours=99999)


# ── 레이드 체크 (길드원 셀프서비스) ──────────────────────────

@router.get("/raids")
async def raids():
  """레이드/난이도 전체 목록. 관리자 API(/api/raids)와 데이터는 같지만 웹앱 키로 접근."""
  return await db.get_raids_dict()


@router.get("/raid-categories")
async def raid_categories():
  return await db.get_categories()


@router.get("/completions")
async def completions(discord_id: str, character_name: str):
  """이번 주(수요일 06:00 KST 기준) 완료 목록."""
  week_key = db.get_week_key()
  done = await db.get_completions(discord_id, character_name, week_key)
  return {"week_key": week_key, "completions": sorted(done)}


class ToggleCompletionBody(BaseModel):
  discord_id: str
  character_name: str
  raid_name: str
  difficulty: str


@router.post("/completions/toggle")
async def toggle_completion(body: ToggleCompletionBody):
  completed = await db.toggle_completion(
    body.discord_id, body.character_name, body.raid_name, body.difficulty
  )
  return {"completed": completed}


# ── 공대 모집 (길드원 셀프서비스) ────────────────────────────

@router.get("/parties/proficiency-options")
async def proficiency_options():
  from bot.data.raids import PROFICIENCY
  return [{"value": k, "label": k, "description": v} for k, v in PROFICIENCY.items()]


class CreatePartyBody(BaseModel):
  discord_id: str
  guild_id: str
  raid_name: str
  difficulty: str
  proficiency: str
  scheduled_datetime: str  # KST 기준 "YYYY-MM-DDTHH:MM" (datetime-local 입력값)
  memo: str | None = None


@router.post("/parties/create")
async def create_party(body: CreatePartyBody):
  from datetime import datetime
  from bot.api import bot_ref
  from bot.data.raids import RAIDS, PROFICIENCY, get_difficulty_info
  from bot.ui.views import KST, _create_party_core, _format_schedule

  api_key = await db.get_user_api_key(body.discord_id)
  if not api_key:
    return {"success": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."}

  if body.raid_name not in RAIDS:
    return {"success": False, "reason": "존재하지 않는 레이드입니다."}
  diff_info = get_difficulty_info(body.raid_name, body.difficulty)
  if not diff_info:
    return {"success": False, "reason": "존재하지 않는 난이도입니다."}
  if body.proficiency not in PROFICIENCY:
    return {"success": False, "reason": "존재하지 않는 숙련도입니다."}

  forum_id = await db.get_forum_channel_id(body.guild_id)
  if not forum_id:
    return {"success": False, "reason": "공대 모집 포럼 채널이 아직 설정되지 않았습니다. 디스코드에서 /공대채널설정으로 먼저 지정해주세요."}

  try:
    dt = datetime.fromisoformat(body.scheduled_datetime).replace(tzinfo=KST)
  except ValueError:
    return {"success": False, "reason": "일정 형식이 올바르지 않습니다."}

  bot = bot_ref.get_bot()
  if not bot:
    return {"success": False, "reason": "봇이 아직 준비되지 않았습니다. 잠시 후 다시 시도해주세요."}

  party = await _create_party_core(
    bot, body.guild_id, body.discord_id, forum_id,
    body.raid_name, body.difficulty, body.proficiency,
    _format_schedule(dt), dt.isoformat(), body.memo,
  )
  return {"success": True, "message_id": party["message_id"]}


@router.get("/parties")
async def parties(guild_id: str):
  result = await db.get_guild_parties(guild_id)
  out = []
  for party in result:
    slots = await db.get_party_slots(party["message_id"])
    out.append({**party, "slots": slots})
  return out


@router.get("/parties/calendar")
async def parties_calendar(guild_id: str, start: str, end: str):
  """일정 캘린더용 — [start, end) 구간에 일정이 잡힌 파티 전체.
  클리어된 파티(status=disbanded)는 행이 남아있으므로 그대로 포함되고,
  취소된 파티는 완전 삭제(purge)돼 있으므로 자연히 빠진다."""
  parties = await db.get_calendar_parties(guild_id, start, end)
  out = []
  for party in parties:
    slots = await db.get_party_slots(party["message_id"])
    out.append({**party, "slot_count": len(slots)})
  return out


@router.get("/parties/{message_id}")
async def party_detail(message_id: str):
  party = await db.get_party(message_id)
  if not party:
    return None
  slots = await db.get_party_slots(message_id)
  return {**party, "slots": slots}


@router.get("/parties/{message_id}/eligibility")
async def party_eligibility(message_id: str, discord_id: str):
  """이 유저가 이 파티에 참여 가능한지 + 참여 가능한 캐릭터 목록.
  Discord 참여하기 버튼과 완전히 동일한 판단 로직(db.get_party_join_eligibility)을 사용한다.
  """
  return await db.get_party_join_eligibility(message_id, discord_id)


class JoinPartyBody(BaseModel):
  discord_id: str
  character_name: str
  role: str = "dps"
  party_group: int | None = None  # 파티가 하위 그룹으로 나뉜 경우에만 필요


@router.post("/parties/{message_id}/join")
async def join_party(message_id: str, body: JoinPartyBody):
  from bot.api import bot_ref
  from bot.data.raids import SUPPORT_CLASSES
  from bot.ui.views import _refresh_party_embed_with_reserved

  result = await db.get_party_join_eligibility(message_id, body.discord_id)
  if not result["can_join"]:
    return {"success": False, "reason": result["reason"]}

  char_info = next(
    (q for q in result["qualifying"] if q["name"] == body.character_name), None
  )
  if char_info is None:
    return {"success": False, "reason": "선택한 캐릭터는 참여 조건을 만족하지 않습니다."}

  role = body.role if body.role in ("dps", "support") else "dps"
  if role == "support" and char_info["class"] not in SUPPORT_CLASSES:
    return {"success": False, "reason": "서포터 역할은 서포터 직업만 선택할 수 있습니다."}

  party_split = result["party_split"]
  total_slots = result["total_slots"]

  kwargs: dict = {}
  if party_split and total_slots > party_split:
    if not body.party_group:
      return {"success": False, "reason": "참여할 파티(하위 그룹)를 선택해주세요."}
    kwargs["party_group"] = body.party_group
    kwargs["party_split"] = party_split

  success, slot_number, message = await db.auto_assign_slot(
    message_id, body.discord_id, body.character_name, char_info["class"], role,
    total_slots, **kwargs,
  )

  if success:
    bot = bot_ref.get_bot()
    party = await db.get_party(message_id)
    if bot and party:
      await _refresh_party_embed_with_reserved(bot, party)

  return {"success": success, "slot_number": slot_number, "message": message}


class LeavePartyBody(BaseModel):
  discord_id: str


@router.post("/parties/{message_id}/leave")
async def leave_party(message_id: str, body: LeavePartyBody):
  import discord as _discord
  from bot.api import bot_ref
  from bot.ui.embeds import party_embed
  from bot.ui.views import _refresh_party_embed_with_reserved

  party = await db.get_party(message_id)
  if not party:
    return {"success": False, "reason": "파티를 찾을 수 없습니다."}

  is_leader = party["leader_id"] == body.discord_id

  removed = await db.leave_slot(message_id, body.discord_id)
  if not removed:
    return {"success": False, "reason": "파티에 참여하지 않았습니다."}

  if is_leader:
    remaining = await db.get_party_slots(message_id)
    if remaining:
      await db.transfer_leader(message_id, remaining[0]["discord_id"])
    else:
      await db.disband_party(message_id)

  bot = bot_ref.get_bot()
  updated_party = await db.get_party(message_id)
  if bot and updated_party:
    if updated_party["status"] == "disbanded":
      try:
        channel = bot.get_channel(int(updated_party["channel_id"]))
        if channel is None:
          channel = await bot.fetch_channel(int(updated_party["channel_id"]))
        slots = await db.get_party_slots(message_id)
        msg = await channel.fetch_message(int(message_id))
        await msg.edit(embed=party_embed(updated_party, slots), view=None)
      except (_discord.NotFound, _discord.Forbidden, _discord.HTTPException):
        pass
    else:
      await _refresh_party_embed_with_reserved(bot, updated_party)

  return {"success": True}


# ── 파티장 관리 (마감/재개/클리어/취소/강제퇴장/일정변경/위임) ─────
# 디스코드 ⚙️관리 패널(ManageView)과 동일한 로직 — 웹에서도 파티장만 사용 가능.

def _require_leader(party: dict | None, discord_id: str) -> str | None:
  """파티가 없거나 리더가 아니면 에러 사유 문자열, 문제없으면 None."""
  if not party:
    return "파티를 찾을 수 없습니다."
  if party["leader_id"] != discord_id:
    return "파티장만 사용할 수 있습니다."
  return None


class LeaderActionBody(BaseModel):
  discord_id: str


@router.post("/parties/{message_id}/close")
async def close_party(message_id: str, body: LeaderActionBody):
  from bot.api import bot_ref
  from bot.ui.views import _refresh_party_embed_with_reserved

  party = await db.get_party(message_id)
  err = _require_leader(party, body.discord_id)
  if err:
    return {"success": False, "reason": err}
  if party["status"] in ("closed", "disbanded"):
    return {"success": False, "reason": "처리할 수 없는 상태입니다."}

  await db.close_party(message_id)
  updated = await db.get_party(message_id)
  bot = bot_ref.get_bot()
  if bot:
    await _refresh_party_embed_with_reserved(bot, updated)
  return {"success": True}


@router.post("/parties/{message_id}/reopen")
async def reopen_party(message_id: str, body: LeaderActionBody):
  from bot.api import bot_ref
  from bot.ui.views import _notify_waitlist, _refresh_party_embed_with_reserved

  party = await db.get_party(message_id)
  err = _require_leader(party, body.discord_id)
  if err:
    return {"success": False, "reason": err}
  if party["status"] != "closed":
    return {"success": False, "reason": "처리할 수 없는 상태입니다."}

  await db.reopen_party(message_id)
  updated = await db.get_party(message_id)
  bot = bot_ref.get_bot()
  if bot:
    await _refresh_party_embed_with_reserved(bot, updated)
    await _notify_waitlist(bot, updated)
  return {"success": True}


@router.post("/parties/{message_id}/clear")
async def clear_party(message_id: str, body: LeaderActionBody):
  import discord as _discord
  from bot.api import bot_ref
  from bot.ui.embeds import party_embed

  party = await db.get_party(message_id)
  err = _require_leader(party, body.discord_id)
  if err:
    return {"success": False, "reason": err}
  if party["status"] == "disbanded":
    return {"success": False, "reason": "이미 종료된 파티입니다."}

  slots = await db.get_party_slots(message_id)
  if not slots:
    return {"success": False, "reason": "파티원이 없어 클리어 처리할 수 없습니다."}

  count = await db.complete_raid_for_party(message_id)
  await db.disband_party(message_id)
  disbanded_party = {**party, "status": "disbanded"}

  bot = bot_ref.get_bot()
  if bot:
    try:
      channel = bot.get_channel(int(party["channel_id"])) or await bot.fetch_channel(int(party["channel_id"]))
      msg = await channel.fetch_message(int(message_id))
      await msg.edit(embed=party_embed(disbanded_party, slots), view=None)
      raid_title = f"{party['raid_name']} {party['difficulty']}"
      mentions = " ".join(f"<@{s['discord_id']}>" for s in slots)
      await channel.send(
        f"🏆 **{raid_title}** 클리어!\n{mentions}\n"
        f"파티원 **{count}명**의 레이드 체크가 자동 완료되었습니다."
      )
      await channel.edit(archived=True, locked=True)
    except (_discord.NotFound, _discord.Forbidden, _discord.HTTPException):
      pass

  return {"success": True, "cleared_count": count}


class CancelPartyBody(BaseModel):
  discord_id: str
  reason: str | None = None


@router.post("/parties/{message_id}/cancel")
async def cancel_party(message_id: str, body: CancelPartyBody):
  import discord as _discord
  from bot.api import bot_ref
  from bot.ui.embeds import party_embed
  from bot.ui.views import _send_dm

  party = await db.get_party(message_id)
  err = _require_leader(party, body.discord_id)
  if err:
    return {"success": False, "reason": err}
  if party["status"] == "disbanded":
    return {"success": False, "reason": "이미 종료된 파티입니다."}

  slots = await db.get_party_slots(message_id)
  raid_title = f"{party['raid_name']} {party['difficulty']}"
  reason_text = (body.reason or "").strip()

  await db.purge_party(message_id)

  bot = bot_ref.get_bot()
  if bot:
    dm_content = f"❌ **{raid_title}** 공대가 파티장에 의해 취소되었습니다."
    if reason_text:
      dm_content += f"\n📌 사유: {reason_text}"
    for s in slots:
      if s["discord_id"] != party["leader_id"]:
        await _send_dm(bot, s["discord_id"], dm_content)
    try:
      channel = bot.get_channel(int(party["channel_id"])) or await bot.fetch_channel(int(party["channel_id"]))
      cancelled_party = {**party, "status": "disbanded"}
      msg = await channel.fetch_message(int(message_id))
      await msg.edit(embed=party_embed(cancelled_party, slots), view=None)
      await channel.delete()
    except (_discord.NotFound, _discord.Forbidden, _discord.HTTPException):
      pass

  return {"success": True}


class KickMemberBody(BaseModel):
  discord_id: str
  target_discord_id: str


@router.post("/parties/{message_id}/kick")
async def kick_member(message_id: str, body: KickMemberBody):
  from bot.api import bot_ref
  from bot.ui.views import _refresh_party_embed_with_reserved, _send_dm

  party = await db.get_party(message_id)
  err = _require_leader(party, body.discord_id)
  if err:
    return {"success": False, "reason": err}
  if body.target_discord_id == body.discord_id:
    return {"success": False, "reason": "본인은 강제 퇴장시킬 수 없습니다."}

  removed = await db.leave_slot(message_id, body.target_discord_id)
  if not removed:
    return {"success": False, "reason": "파티원을 찾을 수 없습니다."}

  bot = bot_ref.get_bot()
  if bot:
    raid_title = f"{party['raid_name']} {party['difficulty']}"
    await _send_dm(
      bot, body.target_discord_id,
      f"⚠️ **{raid_title}** 공대에서 파티장에 의해 퇴장되었습니다.",
    )
    updated = await db.get_party(message_id)
    await _refresh_party_embed_with_reserved(bot, updated)

  return {"success": True}


class ReschedulePartyBody(BaseModel):
  discord_id: str
  scheduled_datetime: str
  memo: str | None = None


@router.post("/parties/{message_id}/reschedule")
async def reschedule_party(message_id: str, body: ReschedulePartyBody):
  from datetime import datetime
  from bot.api import bot_ref
  from bot.data.raids import RAIDS
  from bot.ui.views import KST, _format_schedule, _refresh_party_embed_with_reserved

  party = await db.get_party(message_id)
  err = _require_leader(party, body.discord_id)
  if err:
    return {"success": False, "reason": err}
  if party["status"] == "disbanded":
    return {"success": False, "reason": "이미 종료된 파티입니다."}

  try:
    dt_kst = datetime.fromisoformat(body.scheduled_datetime).replace(tzinfo=KST)
  except ValueError:
    return {"success": False, "reason": "일정 형식이 올바르지 않습니다."}
  if dt_kst < datetime.now(KST):
    return {"success": False, "reason": "과거 날짜로는 변경할 수 없습니다."}

  scheduled_time = _format_schedule(dt_kst)
  await db.update_party_schedule(message_id, scheduled_time, dt_kst.isoformat())
  await db.update_party_memo(message_id, body.memo)
  updated = await db.get_party(message_id)

  bot = bot_ref.get_bot()
  if bot:
    await _refresh_party_embed_with_reserved(bot, updated)
    try:
      channel = bot.get_channel(int(updated["channel_id"])) or await bot.fetch_channel(int(updated["channel_id"]))
      raid_info = RAIDS.get(updated["raid_name"], {})
      short_name = raid_info.get("short_name", updated["raid_name"])
      new_name = f"{short_name} {updated['difficulty']} {updated['proficiency']} — {scheduled_time}"
      await channel.edit(name=new_name)
      await channel.send(f"📅 일정이 **{scheduled_time}**으로 변경되었습니다.")
    except Exception:
      pass

  return {"success": True, "scheduled_time": scheduled_time}


class TransferLeaderBody(BaseModel):
  discord_id: str
  new_leader_discord_id: str


@router.post("/parties/{message_id}/transfer-leader")
async def transfer_leader_route(message_id: str, body: TransferLeaderBody):
  from bot.api import bot_ref
  from bot.ui.views import _party_url, _refresh_party_embed_with_reserved, _send_dm

  party = await db.get_party(message_id)
  err = _require_leader(party, body.discord_id)
  if err:
    return {"success": False, "reason": err}

  slots = await db.get_party_slots(message_id)
  if body.new_leader_discord_id not in {s["discord_id"] for s in slots}:
    return {"success": False, "reason": "파티에 참여 중인 인원만 파티장으로 위임할 수 있습니다."}

  await db.transfer_leader(message_id, body.new_leader_discord_id)
  updated = await db.get_party(message_id)

  bot = bot_ref.get_bot()
  if bot:
    await _refresh_party_embed_with_reserved(bot, updated)
    try:
      channel = bot.get_channel(int(updated["channel_id"])) or await bot.fetch_channel(int(updated["channel_id"]))
      await channel.send(f"👑 **파티장 변경** — <@{body.new_leader_discord_id}>님이 새 파티장이 되었습니다.")
    except Exception:
      pass
    await _send_dm(
      bot, body.new_leader_discord_id,
      f"👑 **{updated['raid_name']} {updated['difficulty']}** 공대의 파티장이 되었습니다!\n{_party_url(updated)}",
    )

  return {"success": True}


# ── 원정대 관리 (길드원 셀프서비스) ──────────────────────────
# Discord의 /캐릭터등록, /캐릭터삭제, "동기화" 버튼(bot/ui/views.py)과 동일한 로직.

class AddCharacterBody(BaseModel):
  discord_id: str
  character_name: str


@router.post("/characters/add")
async def add_character(body: AddCharacterBody):
  # 등록된 계정(부계정 포함)을 순서대로 시도해 이 캐릭터가 속한 계정을 자동 판별 —
  # Discord /캐릭터등록(AddCharacterModal)과 동일한 공용 로직.
  return await register_character_auto_detect(body.discord_id, body.character_name)


class RemoveCharacterBody(BaseModel):
  discord_id: str
  character_name: str


@router.post("/characters/remove")
async def remove_character(body: RemoveCharacterBody):
  removed = await db.remove_character(body.discord_id, body.character_name)
  if not removed:
    return {"success": False, "reason": f"{body.character_name}은(는) 등록된 캐릭터가 아닙니다."}
  return {"success": True}


class SyncCharactersBody(BaseModel):
  discord_id: str


@router.post("/characters/sync")
async def sync_characters(body: SyncCharactersBody):
  api_key = await db.get_user_api_key(body.discord_id)
  if not api_key:
    return {"success": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."}

  # 계정(부계정 포함)별로 그룹핑해서 동기화 — Discord "동기화" 버튼, 일일 자동 동기화와
  # 동일한 공용 로직.
  updated, total = await sync_characters_for_discord_id(body.discord_id)
  return {"success": True, "updated": updated, "total": total}
