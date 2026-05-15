from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
import bot.database.manager as db
import aiosqlite

router = APIRouter(dependencies=[Depends(verify_api_key)])


# ── 주간 클리어 통계 ──────────────────────────────────────

# /weekly: 레이드별 클리어 횟수 집계
@router.get("/weekly")
# week_key: str | None = None: 파라미터 없으면 이번 주 자동 조회
async def get_weekly_stats(week_key: str | None = None):
  week = week_key if week_key else db.get_week_key()
  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
      "SELECT raid_name, difficulty, COUNT(*) as count "
      "FROM raid_completions "
      "WHERE week_key = ? "
      "GROUP BY raid_name, difficulty "
      "ORDER BY count DESC",
      (week,),
    )
    rows = await cur.fetchall()
  return {"week_key": week, "data": [dict(r) for r in rows]}


# ── 캐릭터별 클리어 통계 ──────────────────────────────────

# /characters: 캐릭터별 클리어 횟수 집계
@router.get("/characters")
async def get_character_stats(week_key: str | None = None):
  week = week_key if week_key else db.get_week_key()
  async with aiosqlite.connect(db.DB_PATH) as conn:
    conn.row_factory = aiosqlite.Row
    cur = await conn.execute(
      "SELECT discord_id, character_name, COUNT(*) as clears "
      "FROM raid_completions "
      "WHERE week_key = ? "
      "GROUP BY discord_id, character_name "
      "ORDER BY clears DESC",
      (week,),
    )
    rows = await cur.fetchall()
  return {"week_key": week, "data": [dict(r) for r in rows]}


# ── 주차 목록 ─────────────────────────────────────────────

# /weeks: 드롭다운용 — 조회 가능한 주차 최근 12개
@router.get("/weeks")
async def get_available_weeks():
  async with aiosqlite.connect(db.DB_PATH) as conn:
    cur = await conn.execute(
      "SELECT DISTINCT week_key FROM raid_completions "
      "ORDER BY week_key DESC "
      "LIMIT 12",
    )
    rows = await cur.fetchall()
  return [r[0] for r in rows]