from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
from bot.api import bot_ref
import bot.database.manager as db
import aiosqlite

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── 유저 목록 ─────────────────────────────────────────────

@router.get("")
async def get_users(guild_id: str | None = None):
  from bot.database.manager import _REPRESENTATIVE_CHARACTER_SQL

  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
      "SELECT u.discord_id, u.registered_at, "
      f"{_REPRESENTATIVE_CHARACTER_SQL.format(alias='u')} AS representative "
      "FROM users u ORDER BY u.registered_at DESC"
    )
    users = [dict(r) for r in await cur.fetchall()]

  # 디스코드 서버 별명 조회
  if guild_id:
    bot = bot_ref.get_bot()
    if bot:
      guild = bot.get_guild(int(guild_id))
      if guild:
        for u in users:
          member = guild.get_member(int(u["discord_id"]))
          u["discord_nick"] = member.display_name if member else None

  return users


# ── 유저 캐릭터 목록 ──────────────────────────────────────

@router.get("/{discord_id}/characters")
async def get_characters(discord_id: str):
  return await db.get_cached_characters(discord_id, max_age_hours=99999)


# ── 유저 참여 이력 ────────────────────────────────────────

@router.get("/stale")
async def get_stale_users(days: int = 28):
  """캐릭터 동기화가 N일 이상 안 된 유저 (API 키 만료 의심) — 웹 관리자 유저 목록과 같은 쿼리."""
  return await db.get_stale_users(days)


@router.get("/{discord_id}/history")
async def get_party_history(discord_id: str):
  entries, _has_more, _total_count = await db.get_user_party_history(discord_id)
  return entries


# ── 유저 삭제 ─────────────────────────────────────────────

@router.delete("/{discord_id}")
async def delete_user(discord_id: str):
  await db.delete_user(discord_id)
  return {"success": True}
