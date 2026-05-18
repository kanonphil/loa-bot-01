import time
import os
import signal
import asyncio
from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
from bot.api import bot_ref
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("")
async def get_status():
  bot = bot_ref.get_bot()
  uptime_sec = int(time.time() - bot_ref.start_time)
  is_online  = bot is not None and bot.is_ready()

  async with __import__("aiosqlite").connect(db.DB_PATH) as conn:
    cur = await conn.execute("SELECT COUNT(*) FROM users")
    user_count = (await cur.fetchone())[0]
    cur = await conn.execute(
      "SELECT COUNT(*) FROM parties WHERE status IN ('recruiting','full','closed')"
    )
    active_party_count = (await cur.fetchone())[0]
    cur = await conn.execute("SELECT COUNT(*) FROM raid_subscriptions")
    sub_count = (await cur.fetchone())[0]

  h, rem = divmod(uptime_sec, 3600)
  m, s   = divmod(rem, 60)

  return {
    "is_online":          is_online,
    "uptime_seconds":     uptime_sec,
    "uptime_str":         f"{h}시간 {m}분 {s}초",
    "user_count":         user_count,
    "active_party_count": active_party_count,
    "subscription_count": sub_count,
    "latency_ms":         round(bot.latency * 1000, 1) if bot and is_online else None,
  }


@router.post("/restart")
async def restart_bot():
  """1초 후 SIGTERM — systemd Restart=always 가 자동 재시작."""
  asyncio.get_event_loop().call_later(1, lambda: os.kill(os.getpid(), signal.SIGTERM))
  return {"success": True, "message": "봇이 1초 후 재시작됩니다."}
