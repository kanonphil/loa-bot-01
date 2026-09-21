from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_api_key
from bot.api import bot_ref
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])


class NotifyBody(BaseModel):
  message_id: str
  content:    str

class BroadcastBody(BaseModel):
  content: str


@router.get("")
async def get_all_subscriptions():
  return await db.get_all_subscriptions()


@router.get("/logs")
async def get_notification_logs(limit: int = 100):
  return await db.get_notification_logs(limit)


@router.post("/notify/party")
async def notify_party(body: NotifyBody):
  """파티 전체 파티원에게 수동 DM 발송."""
  from bot.services.broadcast import dm_party_members

  bot = bot_ref.get_bot()
  if not bot:
    return {"success": False, "reason": "봇이 오프라인입니다."}
  sent, total = await dm_party_members(bot, body.message_id, body.content)
  if total == 0:
    return {"success": False, "reason": "파티원이 없습니다."}
  return {"success": True, "sent": sent}


@router.post("/notify/all")
async def notify_all(body: BroadcastBody):
  """API 등록 유저 전원에게 공지 DM 발송."""
  from bot.services.broadcast import dm_all_users

  bot = bot_ref.get_bot()
  if not bot:
    return {"success": False, "reason": "봇이 오프라인입니다."}
  sent, total = await dm_all_users(bot, body.content)
  return {"success": True, "sent": sent, "total": total}
