"""
웹앱(별도 서버)이 로그인 시 호출하는 내부 전용 API.
X-Webapp-Key로만 인증하며, 관리자 API(X-API-Key)와는 분리되어 있다.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
import config
from bot.api.auth import verify_webapp_key
import bot.api.lostark as loa
import bot.database.manager as db
from bot.data import raids as raids_module
from bot.services.expedition import (
  register_character_auto_detect,
  sync_characters_for_discord_id,
  verify_and_register_api_key,
)

router = APIRouter(dependencies=[Depends(verify_webapp_key)])


def _require_admin(discord_id: str) -> str | None:
  """discord_id가 ADMIN_DISCORD_IDS에 없으면 에러 사유 문자열, 문제없으면 None.
  X-Webapp-Key는 웹앱 전체를 인증할 뿐 관리자 여부를 모르므로, 관리자 전용 액션은
  매 요청마다 여기서 다시 검증한다(웹앱 세션 쪽 검사만 믿지 않는다)."""
  if discord_id not in config.ADMIN_DISCORD_IDS:
    return "관리자 권한이 없습니다."
  return None


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
  """웹앱 여러 화면(공대/대시보드/레이드체크/원정대)이 공유하는 캐릭터 정보(직업·아이템레벨 등). 캐시된 값 그대로 반환."""
  return await db.get_cached_characters(discord_id, max_age_hours=99999)


@router.get("/user-characters-grouped")
async def user_characters_grouped(discord_id: str):
  """웹 원정대 페이지용 — 캐릭터 목록 + 소속 계정 라벨(account_label).
  부계정이 있으면 페이지에서 계정별로 묶어 보여준다."""
  return await db.get_cached_characters_with_account(discord_id, max_age_hours=99999)


@router.get("/user-party-history")
async def user_party_history(discord_id: str, limit: int = 20, offset: int = 0):
  """웹 '공대 이력' 페이지용 — 관리자 전용 /api/users/{id}/history와 별도 엔드포인트로
  둔다(그쪽은 ADMIN_API_KEY 인증이라 웹앱에는 그 권한을 주지 않는다)."""
  entries, has_more, total_count = await db.get_user_party_history(discord_id, limit, offset)
  return {"entries": entries, "has_more": has_more, "total_count": total_count}


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


@router.get("/job-classes")
async def job_classes():
  """전체 직업 목록(서포터 여부 포함) — 관리자 화면의 직업 관리용.
  /support-classes는 이름만 주지만 여기는 편집 대상 전체를 그대로 준다."""
  return await db.get_all_job_classes()


@router.get("/completions")
async def completions(discord_id: str, character_name: str):
  """이번 주(수요일 06:00 KST 기준) 완료 목록."""
  week_key = db.get_week_key()
  done = await db.get_completions(discord_id, character_name, week_key)
  return {"week_key": week_key, "completions": sorted(done)}


@router.get("/armory-detail")
async def armory_detail(discord_id: str, character_name: str):
  """캐릭터 상세 정보(스킬/트라이포드/룬/아크패시브/장신구 품질·연마/보석).
  캐시가 있으면 그대로 반환 — 로스트아크 API를 매번 호출하지 않는다."""
  from bot.services.armory import get_character_armory_detail

  return await get_character_armory_detail(discord_id, character_name)


@router.post("/armory-detail/sync")
async def armory_detail_sync(discord_id: str, character_name: str):
  """"동기화" 버튼 전용 — 로스트아크 API를 실제로 호출해 캐시를 최신 정보로 갱신한다."""
  from bot.services.armory import sync_character_armory_detail

  return await sync_character_armory_detail(discord_id, character_name)


@router.get("/ranking")
async def ranking(metric: str = "combat_power", limit: int = 100, role: str | None = None):
  """전체 원정대 랭킹 — metric: combat_power | item_level | weekly_clears.
  role(dps|support)은 combat_power에서만 적용되는 딜러/서포터 필터.
  캐시된 데이터만 읽으므로(로스트아크 API 미호출) 빠르고 한도 부담이 없다."""
  if metric not in ("combat_power", "item_level", "weekly_clears"):
    metric = "combat_power"
  if role not in ("dps", "support"):
    role = None
  return {"metric": metric, "role": role, "entries": await db.get_expedition_ranking(metric, limit, role)}


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


@router.get("/raid-progress")
async def raid_progress(discord_id: str):
  """원정대 전체의 이번 주 레이드 진행률을 한 번에 계산해 준다.

  웹앱이 캐릭터마다 completions/raid-selection을 따로 부르면 캐릭터 수만큼
  왕복이 생긴다(대시보드·사이드바 배지가 매번 그랬다). 봇 서버는 DB가 로컬이라
  여기서 한 번에 세는 게 훨씬 싸다. 진행률은 레이드 단위 — 한 레이드에서
  어느 난이도든 하나만 끝내면 그 레이드는 완료로 친다(웹 계산과 동일 규칙)."""
  from bot.data.raids import get_applicable_raids

  week_key = db.get_week_key()
  # 캐시가 오래됐다고 레벨을 None으로 지우면 진행률이 0이 된다 —
  # /user-characters-grouped와 같은 기준으로 캐시 나이를 무시하고 읽는다.
  characters = await db.get_cached_characters(discord_id, max_age_hours=99999)

  per_character = []
  for char in characters:
    name = char["character_name"]
    applicable = get_applicable_raids(char.get("item_level") or 0)
    raid_names = []
    for raid_name, _diff, _info in applicable:
      if raid_name not in raid_names:
        raid_names.append(raid_name)

    selected = await db.get_selected_raids(discord_id, name)
    if selected is not None:
      chosen = set(selected)
      raid_names = [r for r in raid_names if r in chosen]

    done = await db.get_completions(discord_id, name, week_key)
    done_raids = {key.rsplit("_", 1)[0] for key in done}
    done_count = sum(1 for r in raid_names if r in done_raids)

    per_character.append({
      "character_name":  name,
      "character_class": char.get("character_class"),
      "item_level":      char.get("item_level"),
      "done_count":      done_count,
      "total_slots":     len(raid_names),
      "remaining":       len(raid_names) - done_count,
    })

  return {
    "week_key":   week_key,
    "characters": per_character,
    "done":       sum(c["done_count"] for c in per_character),
    "total":      sum(c["total_slots"] for c in per_character),
  }


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
  from bot.ui.views import KST, _create_party_core, _format_schedule, validate_party_schedule

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

  # 디스코드 모달(ScheduleAndMemoModal)과 동일한 검증 — 과거 날짜 거부 + 익스트림
  # 레이드 운영 기간 확인. 이전에는 웹 경로에만 이 검증이 빠져 있어 과거 일정이나
  # 운영 기간 밖의 익스트림 공대를 만들 수 있었다.
  error = validate_party_schedule(dt, RAIDS.get(body.raid_name, {}))
  if error:
    return {"success": False, "reason": error}

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
  import discord as _discord
  from bot.api import bot_ref
  from bot.data.raids import SUPPORT_CLASSES
  from bot.ui.views import _party_url, _refresh_party_embed_with_reserved, _send_dm

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
    # 디스코드 참여하기 버튼(bot/ui/views.py _auto_join_dps, RoleSelectView)과 동일한
    # 후처리 — 이전에는 웹 참여가 waitlist를 안 지워서 이미 참여한 사람에게 나중에
    # 빈자리 알림 DM이 갈 수 있었고, 만석 공지·리더 DM도 전혀 발송되지 않았다.
    await db.remove_waitlist(message_id, body.discord_id)
    bot = bot_ref.get_bot()
    party = await db.get_party(message_id)
    if bot and party:
      await _refresh_party_embed_with_reserved(bot, party)
      if party["status"] == "full":
        try:
          slots = await db.get_party_slots(message_id)
          channel = bot.get_channel(int(party["channel_id"])) or await bot.fetch_channel(int(party["channel_id"]))
          mentions = " ".join(f"<@{s['discord_id']}>" for s in slots)
          await channel.send(
            f"🎉 **{party['raid_name']} {party['difficulty']}** 파티가 완성되었습니다!\n{mentions}"
          )
        except (_discord.NotFound, _discord.Forbidden, _discord.HTTPException):
          pass
      if party["leader_id"] != body.discord_id:
        raid_title = f"{party['raid_name']} {party['difficulty']}"
        role_icon = "🛡️" if role == "support" else "⚔️"
        await _send_dm(
          bot, party["leader_id"],
          f"{role_icon} **{raid_title}** 공대에 **{body.character_name}**({char_info['class']})이(가) 참여했습니다!\n{_party_url(party)}",
        )

  return {"success": success, "slot_number": slot_number, "message": message}


class LeavePartyBody(BaseModel):
  discord_id: str


@router.post("/parties/{message_id}/leave")
async def leave_party(message_id: str, body: LeavePartyBody):
  from bot.api import bot_ref
  from bot.ui.views import _leave_party_core

  success, reason = await _leave_party_core(bot_ref.get_bot(), message_id, body.discord_id)
  return {"success": success, "reason": reason}


@router.get("/parties/{message_id}/waitlist-status")
async def waitlist_status(message_id: str, discord_id: str):
  waitlist = await db.get_waitlist(message_id)
  return {"on_waitlist": discord_id in waitlist}


class WaitlistBody(BaseModel):
  discord_id: str


@router.post("/parties/{message_id}/waitlist")
async def toggle_waitlist(message_id: str, body: WaitlistBody):
  """빈자리 알림 대기 토글 — Discord PartyView._handle_waitlist와 동일한 규칙
  (참여 중이면 거부). 임베드 갱신 등 Discord 부수효과가 없는 순수 DB 토글이라
  다른 파티 액션들과 달리 _core 함수 없이 라우트에서 바로 처리한다."""
  slots = await db.get_party_slots(message_id)
  if any(s["discord_id"] == body.discord_id for s in slots):
    return {"success": False, "reason": "이미 파티에 참여 중입니다."}

  waitlist = await db.get_waitlist(message_id)
  if body.discord_id in waitlist:
    await db.remove_waitlist(message_id, body.discord_id)
    return {"success": True, "on_waitlist": False}
  await db.add_waitlist(message_id, body.discord_id)
  return {"success": True, "on_waitlist": True}


# ── 파티 초대 (등록 유저만 — 게스트 초대는 아직 웹에 없음) ────────

@router.get("/parties/{message_id}/invitable-users")
async def invitable_users(message_id: str, discord_id: str):
  """리더/관리자에게 보여줄 초대 가능 유저 + 빈 슬롯 목록. 웹의 초대 폼이 쓴다."""
  from bot.ui.views import _require_leader_or_admin

  party = await db.get_party(message_id)
  err = _require_leader_or_admin(party, discord_id)
  if err:
    return {"success": False, "reason": err}

  slots = await db.get_party_slots(message_id)
  reserved = await db.get_reserved_slots(message_id)
  in_party_ids = {s["discord_id"] for s in slots} | set(reserved.values()) | {party["leader_id"]}
  users = await db.get_invitable_users(in_party_ids)
  occupied = {s["slot_number"] for s in slots} | set(reserved.keys())
  available_slots = [n for n in range(1, party["total_slots"] + 1) if n not in occupied]
  return {"success": True, "users": users, "available_slots": available_slots}


class CreateInviteBody(BaseModel):
  discord_id: str
  target_discord_id: str
  slot_number: int


@router.post("/parties/{message_id}/invite")
async def create_invite(message_id: str, body: CreateInviteBody):
  from bot.api import bot_ref
  from bot.ui.views import _create_invite_core

  return await _create_invite_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.target_discord_id, body.slot_number
  )


@router.get("/my-invites")
async def my_invites(discord_id: str):
  """로그인한 유저에게 온 대기 중인 초대 목록 — 웹 전용(디스코드는 DM으로 바로 알림)."""
  return await db.get_user_invites(discord_id)


class AcceptInviteBody(BaseModel):
  discord_id: str
  character_name: str
  role: str


@router.post("/invites/{message_id}/accept")
async def accept_invite(message_id: str, body: AcceptInviteBody):
  from bot.api import bot_ref
  from bot.ui.views import _accept_invite_core

  return await _accept_invite_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.character_name, body.role
  )


class DeclineInviteBody(BaseModel):
  discord_id: str


@router.post("/invites/{message_id}/decline")
async def decline_invite(message_id: str, body: DeclineInviteBody):
  from bot.api import bot_ref
  from bot.ui.views import _decline_invite_core

  return await _decline_invite_core(bot_ref.get_bot(), message_id, body.discord_id)


# ── 파티 스레드 댓글 (디스코드 ↔ 웹 양방향) ─────────────────────

@router.get("/parties/{message_id}/comments")
async def get_party_comments(message_id: str):
  return await db.get_party_comments(message_id)


class PostCommentBody(BaseModel):
  discord_id: str
  display_name: str
  avatar_url: str
  content: str


@router.post("/parties/{message_id}/comments")
async def post_party_comment(message_id: str, body: PostCommentBody):
  from bot.api import bot_ref
  from bot.ui.views import _post_comment_core

  return await _post_comment_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.display_name, body.avatar_url, body.content
  )


class DeleteCommentBody(BaseModel):
  discord_id: str


@router.post("/parties/{message_id}/comments/{comment_id}/delete")
async def delete_party_comment(message_id: str, comment_id: int, body: DeleteCommentBody):
  deleted = await db.delete_party_comment(comment_id, body.discord_id)
  return {"success": deleted}


@router.get("/parties/{message_id}/switch-eligibility")
async def switch_eligibility(message_id: str, discord_id: str):
  """참여 캐릭터 변경 시 고를 수 있는 캐릭터 후보 — 같은 레이드의 다른 공대에 이미
  참여 중인 캐릭터도 후보에 포함하되 in_other_party로 표시(웹/봇 UI가 "타 공대 참여중"
  경고와 확인 절차를 붙일 수 있도록)."""
  return await db.get_party_switch_eligibility(message_id, discord_id)


class SwitchCharacterBody(BaseModel):
  discord_id: str
  character_name: str


@router.post("/parties/{message_id}/switch-character")
async def switch_character(message_id: str, body: SwitchCharacterBody):
  from bot.api import bot_ref
  from bot.ui.views import _switch_character_core

  return await _switch_character_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.character_name
  )


class SwitchRoleBody(BaseModel):
  discord_id: str
  new_role: str


@router.post("/parties/{message_id}/switch-role")
async def switch_role(message_id: str, body: SwitchRoleBody):
  """참여 캐릭터는 그대로 두고 역할(딜러/서포터)만 전환 — 나갔다 재참여할 필요 없음."""
  from bot.api import bot_ref
  from bot.ui.views import _switch_role_core

  return await _switch_role_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.new_role
  )


# ── 파티장 관리 (마감/재개/클리어/취소/강제퇴장/일정변경/위임) ─────
# 실제 로직(권한 검증 + DB 반영 + embed/DM/채널 부수효과)은 전부 bot/ui/views.py의
# _xxx_core 함수에 있다 — 디스코드 ⚙️관리 패널과 완전히 같은 코드를 쓴다. 예전엔
# 두 곳에 따로 구현돼 있어서 강제퇴장 시 대기열 알림이 웹에서만 안 가는 등의
# 드리프트가 실제로 있었다(자세한 내용은 _kick_member_core 문서 참고).

class LeaderActionBody(BaseModel):
  discord_id: str


@router.post("/parties/{message_id}/close")
async def close_party(message_id: str, body: LeaderActionBody):
  from bot.api import bot_ref
  from bot.ui.views import _close_party_core

  return await _close_party_core(bot_ref.get_bot(), message_id, body.discord_id)


@router.post("/parties/{message_id}/reopen")
async def reopen_party(message_id: str, body: LeaderActionBody):
  from bot.api import bot_ref
  from bot.ui.views import _reopen_party_core

  return await _reopen_party_core(bot_ref.get_bot(), message_id, body.discord_id)


@router.post("/parties/{message_id}/clear")
async def clear_party(message_id: str, body: LeaderActionBody):
  from bot.api import bot_ref
  from bot.ui.views import _clear_party_core

  return await _clear_party_core(bot_ref.get_bot(), message_id, body.discord_id)


class CancelPartyBody(BaseModel):
  discord_id: str
  reason: str | None = None


@router.post("/parties/{message_id}/cancel")
async def cancel_party(message_id: str, body: CancelPartyBody):
  from bot.api import bot_ref
  from bot.ui.views import _cancel_party_core

  return await _cancel_party_core(bot_ref.get_bot(), message_id, body.discord_id, body.reason)


class KickMemberBody(BaseModel):
  discord_id: str
  target_discord_id: str


@router.post("/parties/{message_id}/kick")
async def kick_member(message_id: str, body: KickMemberBody):
  from bot.api import bot_ref
  from bot.ui.views import _kick_member_core

  return await _kick_member_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.target_discord_id
  )


class ReschedulePartyBody(BaseModel):
  discord_id: str
  scheduled_datetime: str
  memo: str | None = None


@router.post("/parties/{message_id}/reschedule")
async def reschedule_party(message_id: str, body: ReschedulePartyBody):
  from datetime import datetime
  from bot.api import bot_ref
  from bot.ui.views import KST, _reschedule_party_core

  try:
    dt_kst = datetime.fromisoformat(body.scheduled_datetime).replace(tzinfo=KST)
  except ValueError:
    return {"success": False, "reason": "일정 형식이 올바르지 않습니다."}

  return await _reschedule_party_core(
    bot_ref.get_bot(), message_id, body.discord_id, dt_kst, body.memo
  )


class TransferLeaderBody(BaseModel):
  discord_id: str
  new_leader_discord_id: str


@router.post("/parties/{message_id}/transfer-leader")
async def transfer_leader_route(message_id: str, body: TransferLeaderBody):
  from bot.api import bot_ref
  from bot.ui.views import _transfer_leader_core

  return await _transfer_leader_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.new_leader_discord_id
  )


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
  from bot.api import bot_ref
  from bot.services.expedition import remove_character_and_leave_parties

  # 삭제 + 참여 중이던 활성 공대에서 자동으로 나가기까지 처리하는 공용 로직 —
  # Discord /캐릭터삭제, RemoveCharacterView와 동일한 코드를 사용한다.
  removed = await remove_character_and_leave_parties(
    bot_ref.get_bot(), body.discord_id, body.character_name
  )
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


@router.get("/accounts/list")
async def list_accounts(discord_id: str):
  """웹 '내 계정' 목록용 — Discord /api확인과 동일하게 마스킹된 키를 같이 내려준다."""
  accounts = await db.list_user_api_keys(discord_id)
  out = []
  for acc in accounts:
    key = await db.get_user_api_key_by_id(acc["id"])
    masked = (key[:8] + "****" + key[-4:]) if key and len(key) > 12 else "****"
    out.append({**acc, "masked_key": masked})
  return out


class RemoveAccountBody(BaseModel):
  discord_id: str
  key_id: int


@router.post("/accounts/remove")
async def remove_account(body: RemoveAccountBody):
  """Discord /api삭제와 동일한 로직 — 계정 삭제 시 캐릭터 자체는 안 지우고
  api_key_id만 NULL로 남긴다(db.remove_user_api_key)."""
  removed = await db.remove_user_api_key(body.discord_id, body.key_id)
  return {"success": removed}


# ── 관리자 (카테고리/레이드/난이도/직업 CRUD) ─────────────────
# Discord의 /관리 명령어군(bot/cogs/admin.py)과 같은 db 함수를 그대로 호출한다.
# 웹앱은 ADMIN_API_KEY를 갖지 않으므로(웹앱 서버 침해 시에도 관리자 권한이 새지 않도록
# 의도적으로 분리돼 있다), 이 라우트들은 X-Webapp-Key로 들어오되 discord_id를
# _require_admin으로 매번 재검증한다.

class AdminCategoryBody(BaseModel):
  discord_id: str
  name: str
  sort_order: int = 0


@router.post("/admin/categories/add")
async def admin_add_category(body: AdminCategoryBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  added = await db.add_category(body.name, body.sort_order)
  await raids_module.reload()
  return {"success": added}


class AdminCategoryNameBody(BaseModel):
  discord_id: str
  name: str


@router.post("/admin/categories/delete")
async def admin_delete_category(body: AdminCategoryNameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  removed = await db.remove_category(body.name)
  await raids_module.reload()
  return {"success": removed}


class AdminCategoryExtremeBody(BaseModel):
  discord_id: str
  name: str
  is_extreme: bool


@router.post("/admin/categories/extreme")
async def admin_set_category_extreme(body: AdminCategoryExtremeBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  updated = await db.update_category_extreme(body.name, body.is_extreme)
  await raids_module.reload()
  return {"success": updated}


class AdminRaidBody(BaseModel):
  discord_id: str
  name: str
  short_name: str
  icon: str = "⚔️"
  category: str


@router.post("/admin/raids/add")
async def admin_add_raid(body: AdminRaidBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  added = await db.add_raid(body.name, body.short_name, body.icon, body.category)
  await raids_module.reload()
  return {"success": added}


class AdminRaidNameBody(BaseModel):
  discord_id: str
  name: str


@router.post("/admin/raids/delete")
async def admin_delete_raid(body: AdminRaidNameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  removed = await db.remove_raid(body.name)
  await raids_module.reload()
  return {"success": removed}


class AdminRaidActiveBody(BaseModel):
  discord_id: str
  name: str
  is_active: bool


@router.post("/admin/raids/active")
async def admin_set_raid_active(body: AdminRaidActiveBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  updated = await db.set_raid_active(body.name, body.is_active)
  await raids_module.reload()
  return {"success": updated}


class AdminRaidPinBody(BaseModel):
  discord_id: str
  name: str
  is_pinned: bool


@router.post("/admin/raids/pin")
async def admin_set_raid_pinned(body: AdminRaidPinBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  updated = await db.set_raid_pinned(body.name, body.is_pinned)
  await raids_module.reload()
  return {"success": updated}


class AdminDifficultyBody(BaseModel):
  discord_id: str
  raid_name: str
  difficulty: str
  min_level: int
  total_slots: int
  party_split: int | None = None
  gates: int = 1


@router.post("/admin/difficulties/add")
async def admin_add_difficulty(body: AdminDifficultyBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  next_sort = await db.get_next_difficulty_sort_order(body.raid_name)
  added = await db.add_difficulty(
    body.raid_name, body.difficulty, body.min_level,
    body.total_slots, body.party_split, body.gates, next_sort,
  )
  await raids_module.reload()
  return {"success": added}


class AdminDifficultyDeleteBody(BaseModel):
  discord_id: str
  raid_name: str
  difficulty: str


@router.post("/admin/difficulties/delete")
async def admin_delete_difficulty(body: AdminDifficultyDeleteBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  removed = await db.remove_difficulty(body.raid_name, body.difficulty)
  await raids_module.reload()
  return {"success": removed}


class AdminJobClassBody(BaseModel):
  discord_id: str
  name: str
  is_support: bool = False


@router.post("/admin/classes/add")
async def admin_add_class(body: AdminJobClassBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  added = await db.add_job_class(body.name, body.is_support)
  await raids_module.reload()
  return {"success": added}


class AdminJobClassNameBody(BaseModel):
  discord_id: str
  name: str


@router.post("/admin/classes/delete")
async def admin_delete_class(body: AdminJobClassNameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  removed = await db.remove_job_class(body.name)
  await raids_module.reload()
  return {"success": removed}


# ── 관리자 공대 관리 ─────────────────────────────────────────
# 강제 마감/재개/강퇴/파티장위임/일정변경은 새 라우트를 안 만든다 — bot/ui/views.py의
# _require_leader_or_admin이 기존 리더 전용 라우트(/parties/{id}/close 등)에서
# discord_id가 ADMIN_DISCORD_IDS면 리더 검증을 통과시키므로, 웹앱이 관리자의
# discord_id로 그 라우트들을 그대로 호출하면 된다. 여기는 그 방식으로 못 하는
# 두 가지만 추가한다: 전체 목록 조회(리더 전용 라우트엔 없음)와 클리어 되돌리기
# (파티장에게는 의도적으로 안 주는 관리자 전용 액션).

@router.get("/admin/parties")
async def admin_list_parties(guild_id: str, discord_id: str):
  """진행 중(모집중/파티완성/마감) + 종료됨(클리어) 파티 전체 — 관리자 목록 화면용.
  종료됨 쪽은 아직 살아있는(이번 주) 파티와 주간 리셋으로 이미 purge된 이력을
  합쳐서 주되, purge된 쪽은 channel_id가 없어(party_history엔 저장 안 함)
  is_live=False로 구분해 화면에서 "되돌리기" 버튼을 숨길 수 있게 한다.
  이 섹션의 다른 라우트들과 동일하게, X-Webapp-Key만으로는 부족하고 discord_id가
  실제 관리자인지도 다시 검증한다. 이 라우트는 (다른 관리자 라우트와 달리) 성공
  응답 형태가 {"success": ...}가 아니라 {"open": ..., "closed": ...}라서, 거부 시엔
  같은 형태로 애매하게 얼버무리지 않고 그냥 403으로 명확히 막는다."""
  err = _require_admin(discord_id)
  if err:
    raise HTTPException(status_code=403, detail=err)

  open_parties = await db.get_guild_parties(guild_id)
  open_out = []
  for p in open_parties:
    slots = await db.get_party_slots(p["message_id"])
    open_out.append({**p, "slots": slots})

  closed_parties = await db.get_disbanded_parties(guild_id, limit=100)
  closed_out = []
  for p in closed_parties:
    is_live = p.get("channel_id") is not None
    # purge된 이력은 party_slots가 이미 지워져 있어(슬롯을 조회해도 항상 빈 배열) —
    # 아직 살아있는 것만 조회한다.
    slots = await db.get_party_slots(p["message_id"]) if is_live else []
    closed_out.append({**p, "slots": slots, "is_live": is_live})

  return {"open": open_out, "closed": closed_out}


class AdminPartyActionBody(BaseModel):
  discord_id: str


@router.post("/admin/parties/{message_id}/revert-clear")
async def admin_revert_clear(message_id: str, body: AdminPartyActionBody):
  """클리어를 되돌린다 — 파티장도 못 쓰는 관리자 전용(bot/ui/views.py의
  _admin_revert_clear_core 문서 참고)."""
  from bot.api import bot_ref
  from bot.ui.views import _admin_revert_clear_core

  return await _admin_revert_clear_core(bot_ref.get_bot(), message_id, body.discord_id)
