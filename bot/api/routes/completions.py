from fastapi import APIRouter, Depends
from pydantic import BaseModel
from bot.api.auth import verify_api_key
import bot.database.manager as db

router = APIRouter(dependencies=[Depends(verify_api_key)])


class CompletionBody(BaseModel):
  discord_id:     str
  character_name: str
  raid_name:      str
  difficulty:     str
  week_key:       str


@router.get("")
async def get_completions(discord_id: str, character_name: str, week_key: str):
  completions = await db.get_completions(discord_id, character_name, week_key)
  return list(completions)


@router.post("")
async def add_completion(body: CompletionBody):
  added = await db.add_completion(
    body.discord_id, body.character_name,
    body.raid_name, body.difficulty, body.week_key,
  )
  return {"success": added}


@router.delete("")
async def remove_completion(body: CompletionBody):
  removed = await db.remove_completion(
    body.discord_id, body.character_name,
    body.raid_name, body.difficulty, body.week_key,
  )
  return {"success": removed}
