from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
import bot.database.manager as db
import aiosqlite

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── 주간 클리어 통계 ──────────────────────────────────────

@router.get("/weekly")
async def get_weekly_stats(week_key: str | None = None):
  week = week_key if week_key else db.get_week_key()
  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
      "SELECT raid_name, difficulty, COUNT(*) as count "
      "FROM raid_completions WHERE week_key=? "
      "GROUP BY raid_name, difficulty ORDER BY count DESC",
      (week,),
    )
    rows = await cur.fetchall()
  return {"week_key": week, "data": [dict(r) for r in rows]}


# ── 캐릭터별 클리어 통계 ──────────────────────────────────

@router.get("/characters")
async def get_character_stats(week_key: str | None = None):
  week = week_key if week_key else db.get_week_key()
  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
      "SELECT discord_id, character_name, COUNT(*) as clears "
      "FROM raid_completions WHERE week_key=? "
      "GROUP BY discord_id, character_name ORDER BY clears DESC",
      (week,),
    )
    rows = await cur.fetchall()
  return {"week_key": week, "data": [dict(r) for r in rows]}


# ── 주차 목록 ─────────────────────────────────────────────

@router.get("/weeks")
async def get_available_weeks():
  async with aiosqlite.connect(db.DB_PATH) as conn:
    cur = await conn.execute(
      "SELECT DISTINCT week_key FROM raid_completions "
      "ORDER BY week_key DESC LIMIT 12",
    )
    rows = await cur.fetchall()
  return [r[0] for r in rows]


# ── 서버 활동 통계 ────────────────────────────────────────

@router.get("/activity")
async def get_activity(guild_id: str):
  weekly  = await db.get_weekly_activity(guild_id)
  popular = await db.get_popular_raids(guild_id)
  users   = await db.get_active_users(guild_id)
  return {
    "weekly_parties": weekly,
    "popular_raids":  popular,
    "active_users":   users,
  }
