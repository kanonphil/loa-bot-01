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


async def _log_completion(body: CompletionBody, done: bool) -> None:
  from bot.services.admin_log import record_admin_action

  await record_admin_action(
    None, "api", "completion.set",
    f"{body.character_name} {body.raid_name} {body.difficulty} 클리어 {'체크' if done else '해제'} ({body.week_key} 주차)",
    target=body.discord_id,
  )


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
  if added:
    await _log_completion(body, True)
  return {"success": added}


@router.delete("")
async def remove_completion(body: CompletionBody):
  removed = await db.remove_completion(
    body.discord_id, body.character_name,
    body.raid_name, body.difficulty, body.week_key,
  )
  if removed:
    await _log_completion(body, False)
  return {"success": removed}
