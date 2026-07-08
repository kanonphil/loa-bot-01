"""
웹앱(별도 서버)이 로그인 시 호출하는 내부 전용 API.
X-Webapp-Key로만 인증하며, 관리자 API(X-API-Key)와는 분리되어 있다.
"""
import re

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_webapp_key
import bot.api.lostark as loa
import bot.database.manager as db
from bot.services.expedition import (
  register_character_auto_detect,
  sync_characters_for_discord_id,
  verify_and_register_api_key,
)

router = APIRouter(dependencies=[Depends(verify_webapp_key)])


@router.get("/verify-user")
async def verify_user(discord_id: str):
  """discord_id가 /api등록을 마친 계정인지 확인. 웹 로그인 게이트에 사용."""
  registered = await db.user_exists(discord_id)
  return {"discord_id": discord_id, "registered": registered}


@router.get("/guild-info")
async def guild_info(guild_id: str):
  """웹앱 사이드바에 길드 아이콘을 보여주기 위한 조회. 봇이 그 서버에 없거나
  준비 전이면 name/icon_url 모두 None — 호출 측(웹앱)에서 기본 로고로 대체한다."""
  from bot.api import bot_ref

  bot = bot_ref.get_bot()
  guild = bot.get_guild(int(guild_id)) if bot else None
  if guild is None:
    return {"name": None, "icon_url": None}
  return {"name": guild.name, "icon_url": str(guild.icon.url) if guild.icon else None}


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


@router.get("/support-classes")
async def support_classes():
  """서포터로 분류된 직업명 목록 — 웹의 공대 개설 폼이 캐릭터별로 '서포터' 역할
  선택 가능 여부를 미리 판단하는 데 사용(딜러 전용 직업은 서포터를 고를 수 없음)."""
  return sorted(await db.get_support_classes_set())


@router.get("/completions")
async def completions(discord_id: str, character_name: str):
  """이번 주(수요일 06:00 KST 기준) 완료 목록."""
  week_key = db.get_week_key()
  done = await db.get_completions(discord_id, character_name, week_key)
  return {"week_key": week_key, "completions": sorted(done)}


@router.get("/armory-detail")
async def armory_detail(discord_id: str, character_name: str):
  """캐릭터 상세 정보(스킬/트라이포드/룬/아크패시브/장신구 품질·연마/보석)."""
  from bot.services.armory import get_character_armory_detail

  return await get_character_armory_detail(discord_id, character_name)


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


@router.get("/raid-selection")
async def raid_selection(discord_id: str, character_name: str):
  """캐릭터별로 레이드 체크 화면에 표시할 레이드를 고른 상태.
  한 번도 고른 적 없으면(customized=False) 입장 가능한 레이드 전체를 보여줘야 한다."""
  selected = await db.get_selected_raids(discord_id, character_name)
  return {"customized": selected is not None, "selected_raids": selected or []}


class SetRaidSelectionBody(BaseModel):
  discord_id: str
  character_name: str
  raid_names: list[str]


@router.post("/raid-selection")
async def set_raid_selection(body: SetRaidSelectionBody):
  await db.set_selected_raids(body.discord_id, body.character_name, body.raid_names)
  return {"success": True}


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
  아직 살아있는 파티(parties)와 이미 purge된 지난 이력(party_history)을 합쳐서 반환하며,
  각 파티의 slot_count는 db.get_calendar_parties가 알맞은 테이블에서 이미 계산해 준다
  (purge된 파티는 party_slots가 비어 있으므로 여기서 다시 세면 항상 0이 되어버린다)."""
  return await db.get_calendar_parties(guild_id, start, end)


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

  await db.purge_party(message_id, archived_status="cancelled")

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


class AddAccountBody(BaseModel):
  discord_id: str
  api_key: str
  character_name: str


@router.post("/accounts/add")
async def add_account(body: AddAccountBody):
  """부계정(로스트아크 API 키) 추가 — Discord /api등록(ApiKeyModal)과 동일한
  검증(+길드 확인)을 거친 뒤, 원정대 캐릭터 전체를 등록한다("원정대 전체 등록"과 동일)."""
  success, message, siblings, api_key_id = await verify_and_register_api_key(
    body.discord_id, body.api_key, body.character_name
  )
  if not success:
    return {"success": False, "reason": message}

  added = 0
  for char in siblings or []:
    name = char.get("CharacterName")
    if name and await db.add_character(body.discord_id, name, api_key_id=api_key_id):
      added += 1
  return {"success": True, "label": body.character_name, "added": added, "total": len(siblings or [])}


# ── 길드 커뮤니티 게시판 ─────────────────────────────────────

BOARD_CATEGORIES = ("이벤트", "공지", "자유")

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(html: str) -> str:
  """게시글 본문(리치 텍스트 HTML)에서 디스코드 알림 요약용 평문만 추출."""
  return _HTML_TAG_RE.sub("", html)


def _resolve_display_name(guild_id: str, discord_id: str) -> str:
  """길드 멤버 캐시에서 서버 별명(닉네임)을 찾아온다 — 웹앱은 discord_id만 갖고 있어서
  <@id> 멘션 문법을 그대로 표시하면(디스코드 클라이언트 밖이라) 안 풀리고 ID 그대로 보인다."""
  from bot.api import bot_ref

  bot = bot_ref.get_bot()
  if not bot:
    return discord_id
  guild = bot.get_guild(int(guild_id))
  if not guild:
    return discord_id
  member = guild.get_member(int(discord_id))
  if not member:
    return discord_id
  return member.display_name


async def _send_board_announcement(post: dict) -> None:
  """이벤트 카테고리 게시글 생성 직후 디스코드 채널에 알림 발송 — 채널 미설정이면
  조용히 건너뛰고(경고 로그만), 발송 성공 여부와 무관하게 announced=1로 마킹해
  재시도를 반복하지 않는다(파티의 notified 플래그와 동일한 1회성 시도 원칙)."""
  import logging
  from bot.api import bot_ref
  from bot.ui.views import _format_schedule

  logger = logging.getLogger("bot.board")

  settings = await db.get_board_settings(post["guild_id"])
  channel_id = settings.get("board_channel_id") if settings else None
  if not channel_id:
    logger.warning("게시판 채널 미설정 — 길드 %s의 이벤트 게시글 알림을 건너뜁니다.", post["guild_id"])
    await db.mark_board_announced(post["id"])
    return

  bot = bot_ref.get_bot()
  if not bot:
    logger.warning("봇이 아직 준비되지 않아 게시판 알림을 건너뜁니다.")
    await db.mark_board_announced(post["id"])
    return

  try:
    channel = bot.get_channel(int(channel_id)) or await bot.fetch_channel(int(channel_id))
  except Exception:
    logger.warning("게시판 채널(%s)을 찾을 수 없어 알림을 건너뜁니다.", channel_id)
    await db.mark_board_announced(post["id"])
    return

  role_mention = f"<@&{settings['board_role_id']}>" if settings.get("board_role_id") else ""

  schedule_text = ""
  if post.get("scheduled_datetime"):
    try:
      from bot.ui.views import KST
      from datetime import datetime as _dt
      dt = _dt.fromisoformat(post["scheduled_datetime"])
      if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
      schedule_text = f"\n🕒 일정: {_format_schedule(dt)}"
    except ValueError:
      pass

  plain_content = _strip_html(post["content"]).strip()
  summary = plain_content[:200] + ("..." if len(plain_content) > 200 else "")

  lines = [f"📢 {role_mention} 새 이벤트가 등록되었습니다!".strip(), f"**{post['title']}**"]
  if schedule_text:
    lines.append(schedule_text.strip())
  lines.append(summary)
  lines.append("웹사이트 게시판에서 확인하세요.")

  try:
    await channel.send("\n".join(lines))
  except Exception:
    logger.warning("게시판 알림 전송 실패 (channel_id=%s)", channel_id)

  await db.mark_board_announced(post["id"])


@router.get("/board/posts")
async def board_posts(guild_id: str, category: str | None = None):
  return await db.list_board_posts(guild_id, category=category)


class CreateBoardPostBody(BaseModel):
  discord_id: str
  guild_id: str
  title: str
  category: str
  content: str
  scheduled_datetime: str | None = None


@router.post("/board/posts")
async def create_board_post(body: CreateBoardPostBody):
  if body.category not in BOARD_CATEGORIES:
    return {"success": False, "reason": "존재하지 않는 카테고리입니다."}
  if not body.title.strip():
    return {"success": False, "reason": "제목을 입력해주세요."}
  if not body.content.strip():
    return {"success": False, "reason": "내용을 입력해주세요."}

  post_id = await db.create_board_post(
    body.guild_id, body.discord_id, body.title.strip(), body.category,
    body.content.strip(), body.scheduled_datetime,
  )

  if body.category == "이벤트":
    post = await db.get_board_post(post_id)
    await _send_board_announcement(post)

  return {"success": True, "post_id": post_id}


@router.get("/board/posts/{post_id}")
async def board_post_detail(post_id: int):
  post = await db.get_board_post(post_id)
  if not post:
    return None
  comments = await db.list_board_comments(post_id)
  participants = await db.list_board_participants(post_id)
  guild_id = post["guild_id"]
  author_name = _resolve_display_name(guild_id, post["author_discord_id"])
  comments = [
    {**c, "display_name": _resolve_display_name(guild_id, c["discord_id"])} for c in comments
  ]
  participants = [
    {**p, "display_name": _resolve_display_name(guild_id, p["discord_id"])} for p in participants
  ]
  return {**post, "author_name": author_name, "comments": comments, "participants": participants}


class UpdateBoardPostBody(BaseModel):
  discord_id: str
  title: str
  content: str
  scheduled_datetime: str | None = None


@router.patch("/board/posts/{post_id}")
async def update_board_post(post_id: int, body: UpdateBoardPostBody):
  post = await db.get_board_post(post_id)
  if not post:
    return {"success": False, "reason": "게시글을 찾을 수 없습니다."}
  if post["author_discord_id"] != body.discord_id:
    return {"success": False, "reason": "작성자만 수정할 수 있습니다."}
  if not body.title.strip():
    return {"success": False, "reason": "제목을 입력해주세요."}
  if not body.content.strip():
    return {"success": False, "reason": "내용을 입력해주세요."}

  await db.update_board_post(post_id, body.title.strip(), body.content.strip(), body.scheduled_datetime)
  return {"success": True}


class DeleteBoardPostBody(BaseModel):
  discord_id: str


@router.delete("/board/posts/{post_id}")
async def delete_board_post(post_id: int, body: DeleteBoardPostBody):
  post = await db.get_board_post(post_id)
  if not post:
    return {"success": False, "reason": "게시글을 찾을 수 없습니다."}
  if post["author_discord_id"] != body.discord_id:
    return {"success": False, "reason": "작성자만 삭제할 수 있습니다."}

  await db.delete_board_post(post_id)
  return {"success": True}


class AddBoardCommentBody(BaseModel):
  discord_id: str
  content: str


@router.post("/board/posts/{post_id}/comments")
async def add_board_comment(post_id: int, body: AddBoardCommentBody):
  post = await db.get_board_post(post_id)
  if not post:
    return {"success": False, "reason": "게시글을 찾을 수 없습니다."}
  if not body.content.strip():
    return {"success": False, "reason": "댓글 내용을 입력해주세요."}

  comment_id = await db.add_board_comment(post_id, body.discord_id, body.content.strip())
  return {"success": True, "comment_id": comment_id}


class BoardParticipantBody(BaseModel):
  discord_id: str


@router.post("/board/posts/{post_id}/join")
async def join_board_post(post_id: int, body: BoardParticipantBody):
  post = await db.get_board_post(post_id)
  if not post:
    return {"success": False, "reason": "게시글을 찾을 수 없습니다."}

  await db.join_board_post(post_id, body.discord_id)
  return {"success": True}


@router.post("/board/posts/{post_id}/leave")
async def leave_board_post(post_id: int, body: BoardParticipantBody):
  post = await db.get_board_post(post_id)
  if not post:
    return {"success": False, "reason": "게시글을 찾을 수 없습니다."}

  await db.leave_board_post(post_id, body.discord_id)
  return {"success": True}


class BoardSettingsBody(BaseModel):
  guild_id: str
  channel_id: str
  role_id: str | None = None


@router.post("/board/settings")
async def set_board_settings(body: BoardSettingsBody):
  await db.set_board_channel(body.guild_id, body.channel_id, body.role_id)
  return {"success": True}
