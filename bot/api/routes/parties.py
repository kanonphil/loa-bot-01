from fastapi import APIRouter, Depends
from bot.api.auth import verify_api_key
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])

# ── 파티 목록 ─────────────────────────────────────────────

@router.get("")
# guild_id: str: 쿼리 파라미터로 자동 처리 (/api/parties?guild_id=123)
async def get_parties(guild_id: str):
  parties = await db.get_guild_parties(guild_id)
  result = []
  for party in parties:
    slots = await db.get_party_slots(party["message_id"])
    # {**party, "slots": slots}: 파티 정보 + 슬롯 정보를 합쳐서 한번에 반환
    result.append({**party, "slots": slots})
  return result


# ── 파티 상세 ─────────────────────────────────────────────

@router.get("/{message_id}")
async def get_party(message_id: str):
  party = await db.get_party(message_id)
  if not party:
    return None
  slots = await db.get_party_slots(message_id)
  return {**party, "slots": slots}


# ── 파티 강제 종료 ────────────────────────────────────────

@router.delete("/{message_id}")
async def disband_party(message_id: str):
  await db.disband_party(message_id)
  return {"success": True}