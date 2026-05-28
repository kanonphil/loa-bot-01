from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
from bot.api import bot_ref
import bot.database.manager as db
import aiosqlite

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── 유저 목록 ─────────────────────────────────────────────

@router.get("")
async def get_users(guild_id: str | None = None):
  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    # 1단계: 유저 목록 조회
    cur = await conn.execute(
      "SELECT discord_id, registered_at FROM users ORDER BY registered_at DESC"
    )
    users = [dict(r) for r in await cur.fetchall()]
    # 2단계: 각 유저의 대표 캐릭터 조회 (user_characters 우선, 없으면 party_slots)
    for u in users:
      cur = await conn.execute(
        "SELECT character_name FROM user_characters WHERE discord_id=? LIMIT 1",
        (u["discord_id"],),
      )
      row = await cur.fetchone()
      if row:
        u["representative"] = row[0]
      else:
        cur = await conn.execute(
          "SELECT character_name FROM party_slots WHERE discord_id=? ORDER BY joined_at DESC LIMIT 1",
          (u["discord_id"],),
        )
        row = await cur.fetchone()
        u["representative"] = row[0] if row else None

  # 3단계: 디스코드 서버 별명 조회
  if guild_id:
    bot = bot_ref.get_bot()
    if bot:
      guild = bot.get_guild(int(guild_id))
      if guild:
        for u in users:
          member = guild.get_member(int(u["discord_id"]))
          u["discord_nick"] = member.nick if member else None

  return users


# ── 유저 캐릭터 목록 ──────────────────────────────────────

@router.get("/{discord_id}/characters")
async def get_characters(discord_id: str):
  return await db.get_cached_characters(discord_id, max_age_hours=99999)


# ── 유저 참여 이력 ────────────────────────────────────────

@router.get("/stale")
async def get_stale_users(days: int = 28):
  """캐릭터 동기화가 N일 이상 안 된 유저 (API 키 만료 의심)."""
  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
      "SELECT u.discord_id, u.registered_at, "
      "MAX(uc.cached_at) AS last_sync "
      "FROM users u "
      "LEFT JOIN user_characters uc ON u.discord_id = uc.discord_id "
      "GROUP BY u.discord_id "
      "HAVING last_sync IS NULL OR last_sync < datetime('now', ? ) "
      "ORDER BY last_sync ASC",
      (f"-{days} days",),
    )
    rows = await cur.fetchall()
  return [dict(r) for r in rows]


@router.get("/{discord_id}/history")
async def get_party_history(discord_id: str):
  return await db.get_user_party_history(discord_id)


# ── 유저 삭제 ─────────────────────────────────────────────

@router.delete("/{discord_id}")
async def delete_user(discord_id: str):
  await db.delete_user(discord_id)
  return {"success": True}
