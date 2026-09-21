from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])

# 통계 쿼리는 bot/database/manager.py로 옮겨 웹 관리자(internal.py의 /admin/stats/*)와 공유한다.


@router.get("/weekly")
async def get_weekly_stats(week_key: str | None = None):
  week = week_key if week_key else db.get_week_key()
  return {"week_key": week, "data": await db.get_weekly_clear_stats(week)}


@router.get("/characters")
async def get_character_stats(week_key: str | None = None):
  week = week_key if week_key else db.get_week_key()
  return {"week_key": week, "data": await db.get_character_clear_stats(week)}


@router.get("/weeks")
async def get_available_weeks():
  return await db.get_available_weeks()


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
