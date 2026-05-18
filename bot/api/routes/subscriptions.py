from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_api_key
from bot.api import bot_ref
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])


class NotifyBody(BaseModel):
  message_id: str
  content:    str


@router.get("")
async def get_all_subscriptions():
  return await db.get_all_subscriptions()


@router.get("/logs")
async def get_notification_logs(limit: int = 100):
  return await db.get_notification_logs(limit)


@router.post("/notify/party")
async def notify_party(body: NotifyBody):
  """파티 전체 파티원에게 수동 DM 발송."""
  bot = bot_ref.get_bot()
  if not bot:
    return {"success": False, "reason": "봇이 오프라인입니다."}

  slots = await db.get_party_slots(body.message_id)
  if not slots:
    return {"success": False, "reason": "파티원이 없습니다."}

  sent = 0
  for s in slots:
    try:
      user = await bot.fetch_user(int(s["discord_id"]))
      await user.send(body.content)
      sent += 1
    except Exception:
      pass

  return {"success": True, "sent": sent}
