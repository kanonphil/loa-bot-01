"""
웹앱(별도 서버)이 로그인 시 호출하는 내부 전용 API.
X-Webapp-Key로만 인증하며, 관리자 API(X-API-Key)와는 분리되어 있다.
"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_webapp_key
import bot.api.lostark as loa
import bot.database.manager as db

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

@router.get("/parties")
async def parties(guild_id: str):
  result = await db.get_guild_parties(guild_id)
  out = []
  for party in result:
    slots = await db.get_party_slots(party["message_id"])
    out.append({**party, "slots": slots})
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


# ── 원정대 관리 (길드원 셀프서비스) ──────────────────────────
# Discord의 /캐릭터등록, /캐릭터삭제, "동기화" 버튼(bot/ui/views.py)과 동일한 로직.

class AddCharacterBody(BaseModel):
  discord_id: str
  character_name: str


@router.post("/characters/add")
async def add_character(body: AddCharacterBody):
  name = body.character_name.strip()
  api_key = await db.get_user_api_key(body.discord_id)
  if not api_key:
    return {"success": False, "reason": "먼저 /api등록으로 API 키를 등록해주세요."}

  try:
    siblings = await loa.get_siblings(api_key, name)
  except RuntimeError as e:
    return {"success": False, "reason": str(e)}
  if siblings is None:
    return {"success": False, "reason": f"{name} 캐릭터를 찾을 수 없습니다. 이름과 API 키를 확인해주세요."}

  sibling_names = {c["CharacterName"] for c in siblings}
  registered = await db.get_user_characters(body.discord_id)
  if registered and not any(r in sibling_names for r in registered):
    return {"success": False, "reason": "본인 원정대의 캐릭터만 등록할 수 있습니다."}

  char = next((c for c in siblings if c["CharacterName"] == name), None)
  if char is None:
    return {"success": False, "reason": f"{name} 캐릭터를 찾을 수 없습니다. 이름과 API 키를 확인해주세요."}

  added = await db.add_character(body.discord_id, name)
  if not added:
    return {"success": False, "reason": f"{name}은(는) 이미 등록된 캐릭터입니다."}

  level = loa.parse_item_level(char)
  char_class = char.get("CharacterClassName", "?")
  if level > 0:
    await db.update_character_cache(body.discord_id, name, level, char_class)

  return {"success": True, "character_name": name, "character_class": char_class, "item_level": level}


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

  char_names = await db.get_user_characters(body.discord_id)
  if not char_names:
    return {"success": True, "updated": 0, "total": 0}

  try:
    siblings = await loa.get_siblings(api_key, char_names[0])
    siblings_map = {c["CharacterName"]: c for c in siblings} if siblings else {}
  except Exception:
    siblings_map = {}

  updated = 0
  for name in char_names:
    char = siblings_map.get(name)
    if not char:
      continue
    level = loa.parse_item_level(char)
    char_class = char.get("CharacterClassName", "?")
    if level > 0:
      await db.update_character_cache(body.discord_id, name, level, char_class)
      updated += 1

  return {"success": True, "updated": updated, "total": len(char_names)}
