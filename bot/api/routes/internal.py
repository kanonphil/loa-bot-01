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

from bot.services.permissions import require_admin as _require_admin
from bot.services.admin_log import record_admin_action


async def _log(discord_id: str, action: str, summary: str, **kw) -> None:
  """웹 관리자 라우트의 관리자 활동 기록(source='web')."""
  await record_admin_action(discord_id, "web", action, summary, **kw)


def _gold_text(value) -> str:
  return "미입력" if value is None else f"{value:,}"

router = APIRouter(dependencies=[Depends(verify_webapp_key)])


@router.get("/verify-user")
async def verify_user(discord_id: str):
  """discord_id가 /api등록을 마친 계정인지 확인. 웹 로그인 게이트에 사용."""
  registered = await db.user_exists(discord_id)
  if registered:
    # 웹 접속 기록(관리자 유저 목록의 last_active_at) — 웹앱이 유저당 분당 1회 이하로 부른다.
    try:
      await db.touch_user_last_seen(discord_id)
    except Exception:
      pass  # 기록 실패가 로그인 게이트를 막으면 안 된다
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


@router.get("/web-notifications")
async def web_notifications(after_id: int | None = None, limit: int = 200):
  """봇이 보낸 DM/공지의 웹 알림함 복사본. after_id 없이 부르면 현재 최신 id만 준다
  (웹앱이 기동 직후 지난 알림을 다시 뿌리지 않도록)."""
  latest = await db.get_latest_web_notification_id()
  if after_id is None:
    return {"latest_id": latest, "items": []}
  items = await db.get_web_notifications_after(after_id, limit)
  return {"latest_id": max([latest] + [i["id"] for i in items]), "items": items}


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
async def armory_detail(discord_id: str, character_name: str, cache_only: bool = False):
  """캐릭터 상세 정보(스킬/트라이포드/룬/아크패시브/장신구 품질·연마/보석).
  캐시가 있으면 그대로 반환 — 로스트아크 API를 매번 호출하지 않는다.
  cache_only=true면 캐시가 없어도 API를 부르지 않고 {"error", "not_cached": true}를 돌려준다
  (파티원 카드처럼 여러 캐릭터를 한꺼번에 그리는 화면이 API 한도를 쓰지 않도록)."""
  from bot.services.armory import get_character_armory_detail

  if cache_only:
    cached = await db.get_character_armory_cache(discord_id, character_name)
    if not cached:
      return {"error": "아직 불러온 상세 정보가 없습니다.", "not_cached": True}
    detail = cached["detail"]
    detail["synced_at"] = cached["synced_at"]
    return detail
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


def _toggle_validation_error(raid_name: str, difficulty: str) -> str | None:
  info = raids_module.RAIDS.get(raid_name)
  if not info:
    return "존재하지 않는 레이드입니다."
  if difficulty not in (info.get("difficulties") or {}):
    return "존재하지 않는 난이도입니다."
  if info.get("is_extreme"):
    # 익스트림은 원정대 단위 주 1회 — /completions/extreme/set으로만 체크한다
    return "익스트림 레이드는 원정대 단위로 체크해주세요."
  return None


@router.post("/completions/toggle")
async def toggle_completion(body: ToggleCompletionBody):
  """캐릭터 레이드 완료 토글. 실패 시 {"success": False, "reason", "completed": False} —
  예전엔 아무 검증 없이 임의 레이드명·남의 캐릭터·익스트림까지 기록돼 주간 클리어 랭킹이
  부풀거나 익스트림 원정대 1회 제한을 우회할 수 있었다."""
  err = _toggle_validation_error(body.raid_name, body.difficulty)
  if err is None and body.character_name not in await db.get_user_characters(body.discord_id):
    err = "본인 캐릭터만 체크할 수 있습니다."
  if err:
    return {"success": False, "reason": err, "completed": False}
  completed = await db.toggle_completion(
    body.discord_id, body.character_name, body.raid_name, body.difficulty
  )
  return {"success": True, "completed": completed}


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
  # 캐릭터마다 완료/선택을 따로 조회하면 캐릭터당 커넥션 2개 — 원정대 단위로 한 번씩만 읽는다
  completions_by_char = await db.get_week_completions_by_character(discord_id, week_key)
  selections = await db.get_all_selected_raids(discord_id)

  per_character = []
  for char in characters:
    name = char["character_name"]
    applicable = get_applicable_raids(char.get("item_level") or 0)
    raid_names = []
    for raid_name, _diff, _info in applicable:
      if raid_name not in raid_names:
        raid_names.append(raid_name)

    selected = selections.get(name)
    if selected is not None:
      chosen = set(selected)
      raid_names = [r for r in raid_names if r in chosen]

    done = completions_by_char.get(name, set())
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
    # 익스트림은 캐릭터 총합에서 빠지고(원정대당 주 1회라 캐릭터 칸에 안 맞음) 원정대 단위로 따로
    "extreme":    await _extreme_status_payload(discord_id, week_key),
  }


@router.get("/raid-check-summary")
async def raid_check_summary(discord_id: str):
  """웹 레이드 체크 페이지 한 화면에 필요한 데이터를 한 번에 — 예전엔 캐릭터 목록·레이드·
  카테고리·익스트림 상태에 더해 캐릭터마다 completions/raid-selection을 따로 불러 왕복이
  2N+4번이었다. 응답은 기존 개별 엔드포인트 응답의 상위집합이다.

  characters[]: user-characters-grouped 필드 + is_support, completions(이번 주 "레이드_난이도"
  키 목록), selection({customized, selected_raids}), applicable_raids(입장 가능한 일반 레이드,
  선택 필터 적용 전, RAIDS 순서: [{raid_name, short_name, icon, category, difficulties:[이름...]}]),
  visible_raid_names(선택 필터 적용 후 카드에 보일 레이드명), done_count, total_slots."""
  from bot.data.raids import RAIDS, SUPPORT_CLASSES, get_applicable_raids

  week_key = db.get_week_key()
  characters = await db.get_cached_characters_with_account(discord_id, max_age_hours=99999)
  completions_by_char = await db.get_week_completions_by_character(discord_id, week_key)
  selections = await db.get_all_selected_raids(discord_id)

  out = []
  for char in characters:
    name = char["character_name"]
    by_raid: dict[str, dict] = {}
    for raid_name, diff_name, _info in get_applicable_raids(char.get("item_level") or 0):
      info = RAIDS.get(raid_name, {})
      entry = by_raid.setdefault(raid_name, {
        "raid_name": raid_name,
        "short_name": info.get("short_name") or raid_name,
        "icon": info.get("icon"),
        "category": info.get("category"),
        "difficulties": [],
        "difficulty_gold": {},
      })
      entry["difficulties"].append(diff_name)
      entry["difficulty_gold"][diff_name] = _info.get("clear_gold")
    applicable = list(by_raid.values())

    selected = selections.get(name)
    visible = [r["raid_name"] for r in applicable]
    if selected is not None:
      chosen = set(selected)
      visible = [r for r in visible if r in chosen]

    done = completions_by_char.get(name, set())
    done_raids = {key.rsplit("_", 1)[0] for key in done}
    done_count = sum(1 for r in visible if r in done_raids)
    gold_earned, gold_total = _character_gold(by_raid, visible, done)
    out.append({
      **char,
      "is_support": char.get("character_class") in SUPPORT_CLASSES,
      "completions": sorted(done),
      "selection": {"customized": selected is not None, "selected_raids": selected or []},
      "applicable_raids": applicable,
      "visible_raid_names": visible,
      "done_count": done_count,
      "total_slots": len(visible),
      "gold_earned": gold_earned,
      "gold_total": gold_total,
    })

  return {
    "week_key": week_key,
    "characters": out,
    "gold": {"earned": sum(c["gold_earned"] for c in out), "total": sum(c["gold_total"] for c in out)},
    "raids": await db.get_raids_dict(),
    "categories": await db.get_categories(),
    "support_classes": sorted(SUPPORT_CLASSES),
    "extreme": await _extreme_status_payload(discord_id, week_key),
  }


def _character_gold(by_raid: dict[str, dict], visible: list[str], done_keys: set[str]) -> tuple[int, int]:
  """캐릭터의 이번 주 골드 (획득, 총합). 카드에 보이는 레이드마다 — 끝낸 레이드는 끝낸
  난이도의 골드(같은 레이드를 여러 난이도로 체크했으면 큰 쪽), 아직이면 입장 가능한 난이도 중
  가장 큰 골드. 골드 미입력(None)은 0. 주 3회 골드 제한은 반영하지 않는다(요청사항)."""
  from bot.data.raids import RAIDS

  done_by_raid: dict[str, list[str]] = {}
  for key in done_keys:
    raid_name, _, diff = key.rpartition("_")
    done_by_raid.setdefault(raid_name, []).append(diff)

  earned = total = 0
  for raid_name in visible:
    if raid_name in done_by_raid:
      gold_map = (RAIDS.get(raid_name) or {}).get("difficulty_gold") or {}
      gold = max((gold_map.get(d) or 0) for d in done_by_raid[raid_name])
      earned += gold
      total += gold
    else:
      applicable_gold = (by_raid.get(raid_name) or {}).get("difficulty_gold") or {}
      total += max((g or 0 for g in applicable_gold.values()), default=0)
  return earned, total


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
  # 웹앱이 10초마다 폴링하는 경로 — 파티마다 슬롯을 따로 조회하던 N+1을 없앴다.
  return await db.get_guild_parties_with_slots(guild_id)


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
  waitlist = await db.get_waitlist(message_id)
  return {**party, "slots": slots, "waitlist_count": len(waitlist)}


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
  from bot.ui.views import _after_join_core

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
    # 디스코드 참여하기 버튼(_auto_join_dps, RoleSelectView)과 같은 공용 후처리 —
    # 대기열 제거, 임베드 갱신, 만석 공지·웹 알림, 파티장 DM.
    await _after_join_core(
      bot_ref.get_bot(), message_id, body.discord_id, body.character_name, char_info["class"], role,
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
  return {"on_waitlist": discord_id in waitlist, "count": len(waitlist)}


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
  from bot.api import bot_ref
  from bot.ui.views import _delete_comment_core

  return await _delete_comment_core(bot_ref.get_bot(), message_id, comment_id, body.discord_id)


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
  """일정 변경(파티원 DM 발송). memo 키를 아예 빼고 보내면 기존 메모를 그대로 두고,
  memo를 보내면(null 포함) 그 값으로 바꾼다 — 웹은 메모를 /memo로 따로 저장한다."""
  from datetime import datetime
  from bot.api import bot_ref
  from bot.ui.views import KST, MEMO_UNCHANGED, _reschedule_party_core

  try:
    dt_kst = datetime.fromisoformat(body.scheduled_datetime).replace(tzinfo=KST)
  except ValueError:
    return {"success": False, "reason": "일정 형식이 올바르지 않습니다."}

  memo = body.memo if "memo" in body.model_fields_set else MEMO_UNCHANGED
  return await _reschedule_party_core(
    bot_ref.get_bot(), message_id, body.discord_id, dt_kst, memo
  )


class PartyMemoBody(BaseModel):
  discord_id: str
  memo: str | None = None


@router.post("/parties/{message_id}/memo")
async def update_party_memo(message_id: str, body: PartyMemoBody):
  """메모만 변경(파티장 또는 관리자). 임베드는 갱신하고 DM은 보내지 않는다.
  응답: {"success": bool, "reason": str|None, "memo": str|None(성공 시)}."""
  from bot.api import bot_ref
  from bot.ui.views import _update_party_memo_core

  return await _update_party_memo_core(bot_ref.get_bot(), message_id, body.discord_id, body.memo)


@router.get("/raid-subscribers-count")
async def raid_subscribers_count(
  raid_name: str, difficulty: str, discord_id: str | None = None, scheduled_datetime: str | None = None,
):
  """지금 이 레이드/난이도로 공대를 열면 "새 공대" DM을 받을 사람 수 → {"count": n}.
  실제 발송과 같은 규칙(views._new_party_dm_targets): 해당 난이도·'전체' 구독자(중복 1회)에서
  개설자(discord_id)와 일정 주차(scheduled_datetime, KST ISO — 없으면 이번 주)에 같은 레이드의
  다른 활성 공대에 이미 있는 사람을 뺀다. DM 차단 여부는 미리 알 수 없어 포함된다."""
  from bot.ui.views import _new_party_dm_targets

  targets = await _new_party_dm_targets(raid_name, difficulty, discord_id, scheduled_datetime or None)
  return {"count": len(targets)}


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


class EditPartyDifficultyBody(BaseModel):
  discord_id: str
  difficulty: str
  proficiency: str


@router.post("/parties/{message_id}/edit-difficulty")
async def edit_party_difficulty(message_id: str, body: EditPartyDifficultyBody):
  from bot.api import bot_ref
  from bot.ui.views import _edit_party_difficulty_core

  return await _edit_party_difficulty_core(
    bot_ref.get_bot(), message_id, body.discord_id, body.difficulty, body.proficiency
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
  # 동일한 공용 로직. 캐릭터가 많으면 웹 타임아웃(20초)을 넘기므로 백그라운드로 돌리고
  # 최대 15초만 기다린다. 같은 유저의 동기화가 이미 돌고 있으면 새로 시작하지 않고 그걸 기다린다.
  from bot.services.expedition import sync_characters_shared

  result = await sync_characters_shared(body.discord_id, wait_seconds=15.0)
  if result is None:
    total = len(await db.get_user_characters(body.discord_id))
    return {"success": True, "pending": True, "updated": 0, "total": total}
  updated, total = result
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
  if added:
    await _log(body.discord_id, "category.create", f'카테고리 "{body.name}" 추가', target=body.name)
  return {"success": added}


class AdminCategoryNameBody(BaseModel):
  discord_id: str
  name: str


@router.post("/admin/categories/delete")
async def admin_delete_category(body: AdminCategoryNameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  n = await db.count_raids_in_category(body.name)
  if n:
    return {"success": False, "reason": f"소속 레이드가 {n}개 있어 삭제할 수 없습니다."}
  removed = await db.remove_category(body.name)
  await raids_module.reload()
  if removed:
    await _log(body.discord_id, "category.delete", f'카테고리 "{body.name}" 삭제', target=body.name)
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


# 순서 변경은 "최종 배열 통째로" 저장한다 — 드래그 정렬 UI는 최종 배열을 만들기 때문에
# 항목마다 숫자를 따로 보내면 중간 상태가 저장돼 순서가 깨진다(관리자 API의 PUT
# /api/raids/order와 같은 설계, 같은 db 함수).

class AdminOrderBody(BaseModel):
  discord_id: str
  order: list[str]


@router.post("/admin/categories/order")
async def admin_reorder_categories(body: AdminOrderBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  count = await db.reorder_categories(body.order)
  await raids_module.reload()
  return {"success": count > 0, "count": count}


class AdminRaidOrderBody(BaseModel):
  discord_id: str
  category: str
  order: list[str]


@router.post("/admin/raids/order")
async def admin_reorder_raids(body: AdminRaidOrderBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  count = await db.reorder_raids(body.category, body.order)
  await raids_module.reload()
  return {"success": count > 0, "count": count}


class AdminDifficultyOrderBody(BaseModel):
  discord_id: str
  raid_name: str
  order: list[str]


@router.post("/admin/difficulties/order")
async def admin_reorder_difficulties(body: AdminDifficultyOrderBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  count = await db.reorder_difficulties(body.raid_name, body.order)
  await raids_module.reload()
  return {"success": count > 0, "count": count}


class AdminRaidCategoryBody(BaseModel):
  discord_id: str
  name: str
  category: str


@router.post("/admin/raids/move-category")
async def admin_move_raid_category(body: AdminRaidCategoryBody):
  """레이드를 다른 카테고리로 이동(그 카테고리 맨 뒤에 붙는다)."""
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  cats = {c["name"] for c in await db.get_categories()}
  if body.category not in cats:
    return {"success": False, "reason": f"{body.category} 카테고리가 없습니다."}
  updated = await db.move_raid_category(body.name, body.category)
  await raids_module.reload()
  return {"success": updated}


class AdminRaidPeriodBody(BaseModel):
  discord_id: str
  name: str
  available_from: str | None = None
  available_until: str | None = None


@router.post("/admin/raids/period")
async def admin_set_raid_period(body: AdminRaidPeriodBody):
  """익스트림 레이드 운영 기간 — 둘 다 비우면 기간 삭제. 디스코드 /관리 레이드기간설정과
  같은 db 함수라 저장 형식(KST 오프셋 붙은 ISO)도 호출부(웹앱)에서 맞춰 보낸다."""
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  start, end, err = raids_module.normalize_period(body.available_from, body.available_until)
  if err:
    return {"success": False, "reason": err}
  updated = await db.set_raid_period(body.name, start, end)
  await raids_module.reload()
  if updated:
    period = f"{start or '제한 없음'} ~ {end or '제한 없음'}" if (start or end) else "기간 삭제"
    await _log(body.discord_id, "raid.period", f'레이드 "{body.name}" 운영 기간 변경 ({period})',
               target=body.name, detail={"available_from": start, "available_until": end})
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
  if added:
    await _log(body.discord_id, "raid.create", f'레이드 "{body.name}" 추가 ({body.category})', target=body.name)
  return {"success": added}


class AdminRaidNameBody(BaseModel):
  discord_id: str
  name: str


@router.post("/admin/raids/delete")
async def admin_delete_raid(body: AdminRaidNameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  live = await db.count_live_parties_for_raid(body.name)
  if live:
    return {"success": False, "reason": f"진행 중인 공대가 {live}개 있어 삭제할 수 없습니다."}
  removed = await db.remove_raid(body.name)
  await raids_module.reload()
  if removed:
    await _log(body.discord_id, "raid.delete", f'레이드 "{body.name}" 삭제', target=body.name)
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
  was_active = (raids_module.RAIDS.get(body.name) or {}).get("is_active", True)
  updated = await db.set_raid_active(body.name, body.is_active)
  await raids_module.reload()
  if updated:
    await _log(
      body.discord_id, "raid.enable" if body.is_active else "raid.disable",
      f'레이드 "{body.name}" {"활성화" if body.is_active else "비활성화"}', target=body.name,
      undo={"type": "raid_active", "name": body.name, "is_active": bool(was_active)},
    )
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
  clear_gold: int | None = None


def _clear_gold_error(clear_gold: int | None) -> str | None:
  if clear_gold is not None and clear_gold < 0:
    return "클리어 골드는 0 이상이어야 합니다."
  return None


@router.post("/admin/difficulties/add")
async def admin_add_difficulty(body: AdminDifficultyBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  err = _difficulty_validation_error(body.min_level, body.total_slots, body.party_split, body.gates)
  err = err or _clear_gold_error(body.clear_gold)
  if err:
    return {"success": False, "reason": err}
  next_sort = await db.get_next_difficulty_sort_order(body.raid_name)
  added = await db.add_difficulty(
    body.raid_name, body.difficulty, body.min_level,
    body.total_slots, body.party_split, body.gates, next_sort, body.clear_gold,
  )
  await raids_module.reload()
  if added:
    await _log(
      body.discord_id, "difficulty.add",
      f"{body.raid_name} {body.difficulty} 난이도 추가 (입장 {body.min_level}, {body.total_slots}인, 골드 {_gold_text(body.clear_gold)})",
      target=f"{body.raid_name}/{body.difficulty}",
    )
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
  if removed:
    await _log(body.discord_id, "difficulty.delete", f"{body.raid_name} {body.difficulty} 난이도 삭제",
               target=f"{body.raid_name}/{body.difficulty}")
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

  open_out = await db.get_guild_parties_with_slots(guild_id)

  closed_parties = await db.get_disbanded_parties(guild_id, limit=100)
  closed_out = []
  for p in closed_parties:
    is_live = p.get("channel_id") is not None
    # purge된 이력은 party_slots가 이미 지워져 있어(슬롯을 조회해도 항상 빈 배열) —
    # 아직 살아있는 것만 조회한다.
    slots = await db.get_party_slots(p["message_id"]) if is_live else []
    # can_revert: 클리어로 끝났고 아직 purge 전인 공대만 되돌리기 가능(파티원 전원 이탈/관리자
    # 종료로 끝난 'disbanded'는 클리어가 아니라 되돌릴 대상이 아님)
    closed_out.append({
      **p, "slots": slots, "is_live": is_live, "can_revert": bool(is_live and p.get("cleared_at")),
    })

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


@router.post("/admin/parties/{message_id}/disband")
async def admin_disband_party(message_id: str, body: AdminPartyActionBody):
  """파티 종료(스레드 유지) — 취소(purge)와 구분되는 관리자 앱의 ⚫ 파티 종료."""
  from bot.api import bot_ref
  from bot.ui.views import _admin_disband_party_core

  return await _admin_disband_party_core(bot_ref.get_bot(), message_id, body.discord_id)


@router.post("/admin/parties/{message_id}/unlock")
async def admin_unlock_party(message_id: str, body: AdminPartyActionBody):
  from bot.api import bot_ref
  from bot.ui.views import _unlock_party_thread_core

  return await _unlock_party_thread_core(bot_ref.get_bot(), message_id, body.discord_id)


class AdminNotifyPartyBody(BaseModel):
  discord_id: str
  content: str


@router.post("/admin/parties/{message_id}/notify")
async def admin_notify_party(message_id: str, body: AdminNotifyPartyBody):
  from bot.api import bot_ref
  from bot.ui.views import _admin_notify_party_core

  return await _admin_notify_party_core(bot_ref.get_bot(), message_id, body.discord_id, body.content)


# ── 유저 관리 (Electron 관리자 앱 전용이던 기능을 웹에도 노출) ────────
# 관리자 API(/api/users, ADMIN_API_KEY)와 데이터/로직은 같지만, 웹앱에는 그 키를
# 주지 않으므로 X-Webapp-Key + _require_admin 재검증으로 별도 노출한다.

@router.get("/admin/users")
async def admin_list_users(discord_id: str, guild_id: str | None = None, q: str | None = None):
  """등록 유저 목록. 행마다:
  - representative, registered_at, discord_nick(guild_id를 줬을 때)
  - last_sync: 캐릭터 캐시 마지막 갱신(user_characters.cached_at 최댓값), 없으면 null
  - character_count: 등록 캐릭터 수(user_characters 행 수, 없으면 0)
  - last_active_at: 공대 참여(party_slots.joined_at, 아직 정리 안 된 공대만)·공대 댓글
    (party_comments.created_at)·레이드 클리어 체크(raid_completions.completed_at)·웹 로그인/
    세션 재확인(users.last_seen_at, verify-user가 찍음) 중 가장 늦은 시각, 하나도 없으면 null.
  시각은 전부 SQLite CURRENT_TIMESTAMP 형식의 UTC("YYYY-MM-DD HH:MM:SS", 시간대 표기 없음) —
  웹앱 utils.time_ago/kst_time이 naive를 UTC로 읽는 것과 맞다. 집계는 쿼리 한 번
  (db.get_admin_user_list)."""
  err = _require_admin(discord_id)
  if err:
    raise HTTPException(status_code=403, detail=err)

  users = await db.get_admin_user_list()

  if guild_id:
    from bot.api import bot_ref
    bot = bot_ref.get_bot()
    guild = bot.get_guild(int(guild_id)) if bot else None
    if guild:
      for u in users:
        member = guild.get_member(int(u["discord_id"]))
        u["discord_nick"] = member.display_name if member else None

  if q:
    needle = q.strip().lower()
    users = [
      u for u in users
      if needle in (u.get("representative") or "").lower()
      or needle in (u.get("discord_nick") or "").lower()
      or needle in u["discord_id"]
    ]

  return users


@router.get("/admin/users/{target_discord_id}/characters")
async def admin_user_characters(target_discord_id: str, discord_id: str):
  err = _require_admin(discord_id)
  if err:
    raise HTTPException(status_code=403, detail=err)
  return await db.get_cached_characters(target_discord_id, max_age_hours=99999)


@router.get("/admin/users/{target_discord_id}/history")
async def admin_user_history(target_discord_id: str, discord_id: str, limit: int = 20, offset: int = 0):
  err = _require_admin(discord_id)
  if err:
    raise HTTPException(status_code=403, detail=err)
  entries, has_more, total_count = await db.get_user_party_history(target_discord_id, limit, offset)
  return {"entries": entries, "has_more": has_more, "total_count": total_count}


class AdminDeleteUserBody(BaseModel):
  discord_id: str


@router.post("/admin/users/{target_discord_id}/delete")
async def admin_delete_user(target_discord_id: str, body: AdminDeleteUserBody):
  from bot.api import bot_ref
  from bot.services.expedition import delete_user_and_leave_parties

  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  await delete_user_and_leave_parties(
    bot_ref.get_bot(), target_discord_id, actor_discord_id=body.discord_id, source="web",
  )
  return {"success": True}


@router.get("/admin/users/{target_discord_id}/impact")
async def admin_user_delete_impact(target_discord_id: str, discord_id: str):
  """유저 삭제 확인 창 — 캐릭터/계정 수, 진행 중 공대(파티장이면 넘겨받을 사람), 이번 주 클리어 수."""
  from bot.services.expedition import get_user_delete_impact

  _admin_or_403(discord_id)
  return await get_user_delete_impact(target_discord_id)


# ── 관리자: 통계 / 구독·알림 / 클리어 편집 / 봇 상태 (관리자 앱에만 있던 화면) ─────
# 조회는 관리자가 아니면 403, 쓰기는 {"success": False, "reason": ...} — 이 파일의
# 다른 관리자 라우트와 같은 규칙.

def _admin_or_403(discord_id: str) -> None:
  err = _require_admin(discord_id)
  if err:
    raise HTTPException(status_code=403, detail=err)


@router.get("/admin/stats/weekly")
async def admin_stats_weekly(discord_id: str, week_key: str | None = None):
  _admin_or_403(discord_id)
  week = week_key or db.get_week_key()
  return {"week_key": week, "data": await db.get_weekly_clear_stats(week)}


@router.get("/admin/stats/characters")
async def admin_stats_characters(discord_id: str, week_key: str | None = None):
  _admin_or_403(discord_id)
  week = week_key or db.get_week_key()
  rows = await db.get_character_clear_stats(week)
  names = await db.get_representative_names([r["discord_id"] for r in rows])
  for r in rows:
    r["representative"] = names.get(r["discord_id"])
  return {"week_key": week, "data": rows}


@router.get("/admin/stats/weeks")
async def admin_stats_weeks(discord_id: str):
  _admin_or_403(discord_id)
  weeks = await db.get_available_weeks()
  current = db.get_week_key()
  if current not in weeks:
    weeks.insert(0, current)
  return {"current": current, "weeks": weeks}


@router.get("/admin/stats/activity")
async def admin_stats_activity(discord_id: str, guild_id: str):
  _admin_or_403(discord_id)
  return {
    "weekly_parties": await db.get_weekly_activity(guild_id),
    "popular_raids":  await db.get_popular_raids(guild_id),
    "active_users":   await db.get_active_users(guild_id),
  }


@router.get("/admin/subscriptions")
async def admin_subscriptions(discord_id: str):
  _admin_or_403(discord_id)
  subs = await db.get_all_subscriptions()
  names = await db.get_representative_names([s["discord_id"] for s in subs])
  for s in subs:
    s["representative"] = names.get(s["discord_id"])
  return subs


@router.get("/admin/notification-logs")
async def admin_notification_logs(discord_id: str, limit: int = 200):
  _admin_or_403(discord_id)
  return await db.get_notification_logs(limit)


class AdminBroadcastBody(BaseModel):
  discord_id: str
  content: str


@router.post("/admin/notify-all")
async def admin_notify_all(body: AdminBroadcastBody):
  """등록 유저 전원 공지 DM — 관리자 앱의 📢 전체 공지.
  발송은 백그라운드로 돌고 최대 15초만 기다린다 — 그 안에 끝나면 sent/total, 아니면
  queued=True(발송 계속 진행 중, 진행 상황은 GET /admin/notify-all/status). 같은 내용을
  10분 안에 다시 보내면 거부한다(타임아웃 뒤 재시도로 전원이 두 번 받던 문제)."""
  from bot.api import bot_ref
  from bot.services.broadcast import start_broadcast_and_wait

  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  content = body.content.strip()
  if not content:
    return {"success": False, "reason": "보낼 내용을 입력해주세요."}
  bot = bot_ref.get_bot()
  if not bot:
    return {"success": False, "reason": "봇이 준비되지 않았습니다."}
  result = await start_broadcast_and_wait(bot, content)
  if result.get("success"):
    preview = content if len(content) <= 40 else content[:40] + "…"
    await _log(body.discord_id, "notify_all", f'전체 공지 발송: "{preview}"', detail={"content": content})
  return result


@router.get("/admin/notify-all/status")
async def admin_notify_all_status(discord_id: str):
  from bot.services.broadcast import broadcast_status

  _admin_or_403(discord_id)
  return broadcast_status()


@router.get("/admin/completions")
async def admin_completions(discord_id: str, target_discord_id: str, character_name: str, week_key: str | None = None):
  """다른 유저의 특정 주차 클리어 목록 — 셀프서비스 /completions는 이번 주만 보고
  관리자 검증도 없어서, 과거 주차까지 편집하는 관리자 화면용으로 따로 둔다."""
  _admin_or_403(discord_id)
  week = week_key or db.get_week_key()
  done = await db.get_completions(target_discord_id, character_name, week)
  return {"week_key": week, "completions": sorted(done)}


class AdminSetCompletionBody(BaseModel):
  discord_id: str
  target_discord_id: str
  character_name: str
  raid_name: str
  difficulty: str
  week_key: str
  done: bool


@router.post("/admin/completions/set")
async def admin_set_completion(body: AdminSetCompletionBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  if body.done:
    changed = await db.add_completion(body.target_discord_id, body.character_name, body.raid_name, body.difficulty, body.week_key)
  else:
    changed = await db.remove_completion(body.target_discord_id, body.character_name, body.raid_name, body.difficulty, body.week_key)
  if changed:
    await _log(
      body.discord_id, "completion.set",
      f"{body.character_name} {body.raid_name} {body.difficulty} 클리어 {'체크' if body.done else '해제'} ({body.week_key} 주차)",
      target=body.target_discord_id,
      detail={"character_name": body.character_name, "raid_name": body.raid_name, "difficulty": body.difficulty,
              "week_key": body.week_key, "done": body.done},
    )
  return {"success": True, "done": body.done}


@router.get("/admin/status")
async def admin_status(discord_id: str):
  """봇 온라인/업타임/지연/유저·공대·구독 수 — 재시작은 의도적으로 노출하지 않는다."""
  from bot.api.status_info import collect_status

  _admin_or_403(discord_id)
  return await collect_status()


# ── 디스코드 DM 레이드 구독(/레이드구독)을 웹 설정에서도 관리 ──────────────

class SubscriptionBody(BaseModel):
  discord_id: str
  raid_name: str
  difficulty: str  # 실제 난이도명 또는 "전체"(모든 난이도)


def _validate_subscription(raid_name: str, difficulty: str) -> str | None:
  from bot.data.raids import RAIDS

  info = RAIDS.get(raid_name)
  if not info:
    return "존재하지 않는 레이드입니다."
  if difficulty != "전체" and difficulty not in (info.get("difficulties") or {}):
    return "존재하지 않는 난이도입니다."
  return None


@router.get("/subscriptions")
async def my_subscriptions(discord_id: str):
  return await db.get_user_subscriptions(discord_id)


@router.post("/subscriptions")
async def add_subscription(body: SubscriptionBody):
  err = _validate_subscription(body.raid_name, body.difficulty)
  if err:
    return {"success": False, "reason": err}
  added = await db.subscribe_raid(body.discord_id, body.raid_name, body.difficulty)
  if not added:
    return {"success": False, "reason": "이미 구독 중입니다."}
  return {"success": True}


@router.post("/subscriptions/remove")
async def remove_subscription(body: SubscriptionBody):
  removed = await db.unsubscribe_raid(body.discord_id, body.raid_name, body.difficulty)
  if not removed:
    return {"success": False, "reason": "구독 중이 아닙니다."}
  return {"success": True}


# ── 사전 알림(N시간 전) 설정 ──────────────────────────────────────

class PreNotifyBody(BaseModel):
  discord_id: str
  pre_notify_hours: float


@router.get("/preferences")
async def my_preferences(discord_id: str):
  return {
    "pre_notify_hours": await db.get_pre_notify_hours(discord_id),
    "choices": list(db.PRE_NOTIFY_HOURS_CHOICES),
  }


@router.post("/preferences")
async def set_preferences(body: PreNotifyBody):
  if body.pre_notify_hours not in db.PRE_NOTIFY_HOURS_CHOICES:
    return {"success": False, "reason": "지원하지 않는 시간입니다."}
  await db.set_pre_notify_hours(body.discord_id, body.pre_notify_hours)
  return {"success": True, "pre_notify_hours": body.pre_notify_hours}


# ── 게스트 초대용 서버 멤버 목록 ───────────────────────────────────

@router.get("/parties/{message_id}/guest-candidates")
async def guest_candidates(message_id: str, discord_id: str, guild_id: str):
  """리더/관리자에게 보여줄 게스트(API 미등록) 초대 후보 — 디스코드 서버 멤버 중
  봇이 아니고, /api등록을 안 했고, 이 파티에 아직 없는 사람. 디스코드의
  GuestUserSelectView(유저 피커)에 해당하는 웹 UI의 데이터."""
  from bot.api import bot_ref
  from bot.ui.views import _require_leader_or_admin

  party = await db.get_party(message_id)
  err = _require_leader_or_admin(party, discord_id)
  if err:
    return {"success": False, "reason": err}

  bot = bot_ref.get_bot()
  guild = bot.get_guild(int(guild_id)) if bot else None
  if guild is None:
    return {"success": False, "reason": "봇이 아직 준비되지 않았습니다."}

  slots = await db.get_party_slots(message_id)
  reserved = await db.get_reserved_slots(message_id)
  in_party_ids = {s["discord_id"] for s in slots} | set(reserved.values()) | {party["leader_id"]}
  registered = set(await db.get_all_user_ids())
  members = [
    {"discord_id": str(m.id), "display_name": m.display_name}
    for m in guild.members
    if not m.bot and str(m.id) not in registered and str(m.id) not in in_party_ids
  ]
  members.sort(key=lambda m: m["display_name"].lower())
  occupied = {s["slot_number"] for s in slots} | set(reserved.keys())
  available_slots = [n for n in range(1, party["total_slots"] + 1) if n not in occupied]
  return {"success": True, "members": members, "available_slots": available_slots}


# ── 공대 포럼 채널 설정(/공대채널설정) 웹 관리자 폼 ─────────────────────

@router.get("/admin/forum-channel")
async def admin_forum_channel(discord_id: str, guild_id: str):
  import discord as _discord
  from bot.api import bot_ref

  _admin_or_403(discord_id)
  current = await db.get_forum_channel_id(guild_id)
  bot = bot_ref.get_bot()
  guild = bot.get_guild(int(guild_id)) if bot else None
  channels = []
  if guild is not None:
    channels = [
      {"id": str(ch.id), "name": ch.name}
      for ch in guild.channels
      if isinstance(ch, _discord.ForumChannel)
    ]
  current_name = next((c["name"] for c in channels if c["id"] == current), None)
  return {"forum_channel_id": current, "forum_channel_name": current_name, "channels": channels}


class ForumChannelBody(BaseModel):
  discord_id: str
  guild_id: str
  channel_id: str


@router.post("/admin/forum-channel")
async def admin_set_forum_channel(body: ForumChannelBody):
  import discord as _discord
  from bot.api import bot_ref

  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  bot = bot_ref.get_bot()
  guild = bot.get_guild(int(body.guild_id)) if bot else None
  if guild is None:
    return {"success": False, "reason": "봇이 아직 준비되지 않았습니다."}
  channel = guild.get_channel(int(body.channel_id)) if body.channel_id.isdigit() else None
  if not isinstance(channel, _discord.ForumChannel):
    return {"success": False, "reason": "이 서버의 포럼 채널만 지정할 수 있습니다."}
  await db.set_forum_channel(body.guild_id, body.channel_id)
  return {"success": True, "forum_channel_id": body.channel_id, "forum_channel_name": channel.name}


# ── 지난 주차 클리어 기록 ──────────────────────────────────────────

@router.get("/completions/weeks")
async def completion_weeks(discord_id: str):
  """이 유저의 기록이 있는 주차 키(최신순). 이번 주는 기록이 없어도 맨 앞에 넣는다."""
  weeks = await db.get_user_completion_weeks(discord_id)
  current = db.get_week_key()
  if current not in weeks:
    weeks.insert(0, current)
  return {"current_week": current, "weeks": weeks}


@router.get("/completions/week")
async def completions_for_week(discord_id: str, week_key: str):
  return {"week_key": week_key, "characters": await db.get_user_week_completions(discord_id, week_key)}


# ── 레이드/카테고리/난이도 수정 — 이전엔 토글·순서·기간만 있고 이름/약칭/아이콘/수치는
# 삭제 후 재등록해야 했다. 이름 변경은 참조 테이블을 한 트랜잭션으로 연쇄 갱신한다(db.rename_*).

def _clean_name(value: str | None) -> str:
  return (value or "").strip()


def _difficulty_validation_error(min_level: int, total_slots: int, party_split: int | None, gates: int) -> str | None:
  if min_level <= 0:
    return "입장 레벨은 1 이상이어야 합니다."
  if total_slots <= 0:
    return "인원은 1 이상이어야 합니다."
  if gates < 1:
    return "관문 수는 1 이상이어야 합니다."
  if party_split is not None and (party_split <= 0 or party_split > total_slots or total_slots % party_split != 0):
    return "분할 인원은 전체 인원을 나눌 수 있는 수여야 합니다."
  return None


class AdminRaidUpdateBody(BaseModel):
  discord_id: str
  name: str
  short_name: str
  icon: str = "⚔️"


@router.post("/admin/raids/update")
async def admin_update_raid(body: AdminRaidUpdateBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  short = _clean_name(body.short_name)
  if not short:
    return {"success": False, "reason": "약칭을 입력해주세요."}
  if not await db.raid_exists(body.name):
    return {"success": False, "reason": "레이드를 찾을 수 없습니다."}
  before = raids_module.RAIDS.get(body.name) or {}
  icon = _clean_name(body.icon) or "⚔️"
  await db.update_raid(body.name, short, icon)
  await raids_module.reload()
  if before.get("short_name") != short or before.get("icon") != icon:
    await _log(body.discord_id, "raid.update",
               f'레이드 "{body.name}" 약칭/아이콘 변경 ({before.get("short_name")} → {short})', target=body.name)
  return {"success": True}


class AdminRenameBody(BaseModel):
  discord_id: str
  old_name: str
  new_name: str


@router.post("/admin/raids/rename")
async def admin_rename_raid(body: AdminRenameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  new = _clean_name(body.new_name)
  if not new:
    return {"success": False, "reason": "새 이름을 입력해주세요."}
  if new == body.old_name:
    return {"success": True, "unchanged": True}
  if not await db.raid_exists(body.old_name):
    return {"success": False, "reason": "레이드를 찾을 수 없습니다."}
  if await db.raid_exists(new):
    return {"success": False, "reason": "이미 같은 이름의 레이드가 있습니다."}
  refs = await db.count_raid_references(body.old_name)
  await db.rename_raid(body.old_name, new)
  await raids_module.reload()
  party_count = refs.get("parties_all", 0) + refs.get("party_history", 0)
  await _log(
    body.discord_id, "raid.rename",
    f'레이드 이름 "{body.old_name}" → "{new}" · 공대 {party_count}, 기록 {refs.get("raid_completions", 0)}건 함께 변경',
    target=new, detail=refs, undo={"type": "raid_rename", "from": new, "to": body.old_name},
  )
  return {"success": True}


@router.get("/admin/raids/references")
async def admin_raid_references(discord_id: str, name: str, difficulty: str | None = None):
  """이름 변경 확인 창용 — 이 레이드(또는 난이도)를 참조하는 기록 수."""
  _admin_or_403(discord_id)
  return await db.count_raid_references(name, difficulty or None)


@router.post("/admin/categories/rename")
async def admin_rename_category(body: AdminRenameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  new = _clean_name(body.new_name)
  if not new:
    return {"success": False, "reason": "새 이름을 입력해주세요."}
  if new == body.old_name:
    return {"success": True, "unchanged": True}
  names = {c["name"] for c in await db.get_categories()}
  if body.old_name not in names:
    return {"success": False, "reason": "카테고리를 찾을 수 없습니다."}
  if new in names:
    return {"success": False, "reason": "이미 같은 이름의 카테고리가 있습니다."}
  await db.rename_category(body.old_name, new)
  await raids_module.reload()
  await _log(body.discord_id, "category.rename", f'카테고리 이름 "{body.old_name}" → "{new}"', target=new)
  return {"success": True}


class AdminDifficultyUpdateBody(BaseModel):
  discord_id: str
  raid_name: str
  difficulty: str
  min_level: int
  total_slots: int
  party_split: int | None = None
  gates: int = 1
  # 안 보내면 기존 값 유지, null을 보내면 비움
  clear_gold: int | None = None


@router.post("/admin/difficulties/update")
async def admin_update_difficulty(body: AdminDifficultyUpdateBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  err = _difficulty_validation_error(body.min_level, body.total_slots, body.party_split, body.gates)
  err = err or _clear_gold_error(body.clear_gold)
  if err:
    return {"success": False, "reason": err}
  gold_kwargs = {"clear_gold": body.clear_gold} if "clear_gold" in body.model_fields_set else {}
  before = ((raids_module.RAIDS.get(body.raid_name) or {}).get("difficulties") or {}).get(body.difficulty) or {}
  updated = await db.update_difficulty(
    body.raid_name, body.difficulty, body.min_level, body.total_slots, body.party_split, body.gates,
    **gold_kwargs,
  )
  if not updated:
    return {"success": False, "reason": "난이도를 찾을 수 없습니다."}
  await raids_module.reload()
  changes = []
  for label, key, new_value in (
    ("입장", "min_level", body.min_level), ("인원", "total_slots", body.total_slots),
    ("분할", "party_split", body.party_split), ("관문", "gates", body.gates),
  ):
    if before.get(key) != new_value:
      changes.append(f"{label} {before.get(key)} → {new_value}")
  if gold_kwargs and before.get("clear_gold") != body.clear_gold:
    changes.append(f"골드 {_gold_text(before.get('clear_gold'))} → {_gold_text(body.clear_gold)}")
  if changes:
    await _log(body.discord_id, "difficulty.update",
               f"{body.raid_name} {body.difficulty} 난이도 수정 · {', '.join(changes)}",
               target=f"{body.raid_name}/{body.difficulty}")
  return {"success": True}


class AdminDifficultyRenameBody(BaseModel):
  discord_id: str
  raid_name: str
  old_difficulty: str
  new_difficulty: str


@router.post("/admin/difficulties/rename")
async def admin_rename_difficulty(body: AdminDifficultyRenameBody):
  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  new = _clean_name(body.new_difficulty)
  if not new:
    return {"success": False, "reason": "새 난이도명을 입력해주세요."}
  if new == body.old_difficulty:
    return {"success": True, "unchanged": True}
  diffs = (raids_module.RAIDS.get(body.raid_name) or {}).get("difficulties") or {}
  if body.old_difficulty not in diffs:
    return {"success": False, "reason": "난이도를 찾을 수 없습니다."}
  if new in diffs:
    return {"success": False, "reason": "이미 같은 이름의 난이도가 있습니다."}
  await db.rename_difficulty(body.raid_name, body.old_difficulty, new)
  await raids_module.reload()
  await _log(body.discord_id, "difficulty.rename",
             f'{body.raid_name} 난이도 이름 "{body.old_difficulty}" → "{new}"', target=f"{body.raid_name}/{new}")
  return {"success": True}


# ── 익스트림 레이드 — 원정대(계정) 단위 주 1회 클리어 ─────────────────────

async def _extreme_status_payload(discord_id: str, week_key: str) -> list[dict]:
  """운영 중인 익스트림 레이드마다 원정대 클리어 상태. 레이드 체크 상단 섹션·메인 진행 카드·
  디스코드 /레이드체크 필드가 같은 모양을 쓴다."""
  from bot.data.raids import active_extreme_raids

  status = await db.get_expedition_extreme_status(discord_id, week_key)
  result = []
  for name, info in active_extreme_raids():
    done = status.get(name)
    result.append({
      "raid_name": name,
      "short_name": info.get("short_name") or name,
      "icon": info.get("icon"),
      "available_from": info.get("available_from"),
      "available_until": info.get("available_until"),
      "difficulties": info.get("difficulties") or {},
      "cleared": done is not None,
      "character_name": done["character_name"] if done else None,
      "difficulty": done["difficulty"] if done else None,
    })
  return result


@router.get("/completions/extreme")
async def extreme_completions(discord_id: str):
  week_key = db.get_week_key()
  return {"week_key": week_key, "raids": await _extreme_status_payload(discord_id, week_key)}


class ExtremeSetBody(BaseModel):
  discord_id: str
  raid_name: str
  difficulty: str
  character_name: str


@router.post("/completions/extreme/set")
async def set_extreme_completion(body: ExtremeSetBody):
  info = raids_module.RAIDS.get(body.raid_name)
  if not info or not info.get("is_extreme"):
    return {"success": False, "reason": "익스트림 레이드가 아닙니다."}
  if body.difficulty not in (info.get("difficulties") or {}):
    return {"success": False, "reason": "존재하지 않는 난이도입니다."}
  if body.character_name not in await db.get_user_characters(body.discord_id):
    return {"success": False, "reason": "본인 캐릭터만 체크할 수 있습니다."}
  await db.set_extreme_completion(body.discord_id, body.raid_name, body.difficulty, body.character_name)
  return {"success": True, "character_name": body.character_name, "difficulty": body.difficulty}


class ExtremeClearBody(BaseModel):
  discord_id: str
  raid_name: str


@router.post("/completions/extreme/clear")
async def clear_extreme_completion(body: ExtremeClearBody):
  removed = await db.clear_extreme_completion(body.discord_id, body.raid_name)
  return {"success": True, "removed": removed}


# ── 로스트아크 공용 데이터(공지·이벤트·캘린더·시세) ─────────────────────
# 서버 공용 키(config.GUEST_LOOKUP_DISCORD_ID)로 받은 캐시만 읽는다 — 요청마다 로스트아크
# API를 부르지 않는다(갱신은 봇 루프가 bot/services/loa_content.tick으로).

@router.get("/loa/overview")
async def loa_overview(discord_id: str = ""):
  from bot.services import loa_content

  return await loa_content.overview(discord_id)


@router.get("/loa/calendar")
async def loa_calendar(date: str | None = None):
  from bot.services import loa_content

  return await loa_content.calendar_for(date)


class GoldIslandSubscriptionBody(BaseModel):
  discord_id: str
  enabled: bool


@router.post("/loa/gold-island-subscription")
async def loa_gold_island_subscription(body: GoldIslandSubscriptionBody):
  if not body.discord_id:
    return {"success": False, "reason": "로그인 정보가 없습니다.", "enabled": False}
  await db.set_gold_island_subscription(body.discord_id, body.enabled)
  return {"success": True, "enabled": body.enabled}


@router.get("/loa/prices")
async def loa_prices():
  from bot.services import loa_content

  return await loa_content.prices()


@router.get("/admin/loa/tracked-items")
async def admin_loa_tracked_items(discord_id: str):
  from bot.services import loa_content

  _admin_or_403(discord_id)
  return {"names": await loa_content.get_tracked_items()}


class TrackedItemsBody(BaseModel):
  discord_id: str
  names: list[str]


@router.post("/admin/loa/tracked-items")
async def admin_set_loa_tracked_items(body: TrackedItemsBody):
  from bot.services import loa_content

  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  cleaned = loa_content.clean_tracked_names(body.names)
  if len(cleaned) > loa_content.MAX_TRACKED_ITEMS:
    return {"success": False, "reason": f"추적 아이템은 최대 {loa_content.MAX_TRACKED_ITEMS}개까지 지정할 수 있습니다."}
  previous = await loa_content.get_tracked_items()
  names, unresolved = await loa_content.set_tracked_items(cleaned)
  if names != previous:
    await _log(
      body.discord_id, "loa.tracked_items",
      f"거래소 추적 아이템 변경 ({', '.join(names) or '없음'})",
      detail={"before": previous, "after": names}, undo={"type": "tracked_items", "names": previous},
    )
  return {"success": True, "names": names, "unresolved": unresolved}


# ── 전투력 추이 ───────────────────────────────────────────────

@router.get("/characters/{name}/history")
async def character_cp_history(name: str, discord_id: str, days: int = 90):
  """캐릭터 전투력/아이템레벨 일별 기록 — 본인뿐 아니라 등록된 길드원 누구나 볼 수 있다
  (랭킹처럼 길드 안에서는 공개 정보)."""
  if not await db.user_exists(discord_id):
    raise HTTPException(status_code=403, detail="등록된 길드원만 볼 수 있습니다.")
  days = min(max(days, 1), 365)
  return {"items": await db.get_cp_history(name, days)}


# ── 관리자 활동 기록 ────────────────────────────────────────────

@router.get("/admin/actions")
async def admin_actions(discord_id: str, kind: str = "all", limit: int = 100):
  from bot.services import admin_log

  _admin_or_403(discord_id)
  if kind not in ("party", "raid", "user", "all"):
    kind = "all"
  return {"items": await admin_log.list_actions(kind, limit)}


class AdminUndoBody(BaseModel):
  discord_id: str


@router.post("/admin/actions/{action_id}/undo")
async def admin_undo_action(action_id: int, body: AdminUndoBody):
  from bot.services import admin_log

  err = _require_admin(body.discord_id)
  if err:
    return {"success": False, "reason": err}
  return await admin_log.undo_action(action_id, body.discord_id, source="web")
