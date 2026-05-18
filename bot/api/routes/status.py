import time
from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
from bot.api import bot_ref
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("")
async def get_status():
  bot = bot_ref.get_bot()
  uptime_sec = int(time.time() - bot_ref.start_time)

  # 봇 온라인 여부
  is_online = bot is not None and bot.is_ready()

  # DB 기본 통계
  async with __import__("aiosqlite").connect(db.DB_PATH) as conn:
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    user_count = (await cur.fetchone())[0]
    cur = await conn.execute(
      "SELECT COUNT(*) FROM parties WHERE status IN ('recruiting','full','closed')"
    )
    active_party_count = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM raid_subscriptions")
    sub_count = (await cur.fetchone())[0]

  # 업타임 포맷
  h, rem  = divmod(uptime_sec, 3600)
  m, s    = divmod(rem, 60)
  uptime_str = f"{h}시간 {m}분 {s}초"

  return {
    "is_online":          is_online,
    "uptime_seconds":     uptime_sec,
    "uptime_str":         uptime_str,
    "user_count":         user_count,
    "active_party_count": active_party_count,
    "subscription_count": sub_count,
    "latency_ms":         round(bot.latency * 1000, 1) if bot and is_online else None,
  }
