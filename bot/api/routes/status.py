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
  from bot.api.status_info import collect_status

  return await collect_status()


@router.post("/restart")
async def restart_bot():
  """1초 후 SIGTERM — systemd Restart=always 가 자동 재시작."""
  asyncio.get_event_loop().call_later(1, lambda: os.kill(os.getpid(), signal.SIGTERM))
  return {"success": True, "message": "봇이 1초 후 재시작됩니다."}
