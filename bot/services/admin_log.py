"""관리자 활동 기록 — 웹·디스코드·관리자 API(X-API-Key)가 같은 record_admin_action을 부른다.

action은 "분류.동작" 형식이라 목록 필터(kind)는 접두어로 나눈다:
  party.*                            → party
  raid.* / category.* / difficulty.* → raid
  user.* / completion.* / notify_all → user
그 밖(loa.tracked_items 등)은 all에서만 보인다. 되돌리기 기록은 원래 action 뒤에 ".undo"를 붙인다.

undo_json이 있는 기록만 되돌릴 수 있다(강제 마감↔재개, 레이드 이름 변경, 레이드 활성/비활성,
추적 아이템 변경). 기록 실패가 원래 작업을 막지 않도록 record_admin_action은 예외를 삼킨다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import bot.database.manager as db

KST = timezone(timedelta(hours=9))

KIND_PREFIXES: dict[str, tuple[str, ...]] = {
    "party": ("party.",),
    "raid": ("raid.", "category.", "difficulty."),
    "user": ("user.", "completion.", "notify_all"),
}

API_ACTOR_NAME = "관리자 API"


def resolve_source(as_admin: bool, source: str | None) -> str:
    """as_admin(X-API-Key 관리자 API 경로)이면 'api', 아니면 호출부가 준 값(기본 'web')."""
    if as_admin:
        return "api"
    return source if source in ("web", "discord", "api") else "web"


async def actor_name(discord_id: str | None) -> str:
    """디스코드 표시 이름(봇 캐시) → 대표 캐릭터명 → discord_id 순. API 경로(빈 id)는 '관리자 API'."""
    if not discord_id:
        return API_ACTOR_NAME
    try:
        from bot.api import bot_ref

        bot = bot_ref.get_bot()
        if bot is not None and str(discord_id).isdigit():
            uid = int(discord_id)
            for guild in getattr(bot, "guilds", None) or []:
                member = guild.get_member(uid)
                if member is not None and isinstance(getattr(member, "display_name", None), str):
                    return member.display_name
            user = bot.get_user(uid) if hasattr(bot, "get_user") else None
            name = getattr(user, "global_name", None) or getattr(user, "name", None)
            if isinstance(name, str) and name:
                return name
    except Exception:
        pass
    try:
        names = await db.get_representative_names([discord_id])
        if names.get(discord_id):
            return names[discord_id]
    except Exception:
        pass
    return str(discord_id)


async def record_admin_action(
    actor_discord_id: str | None, source: str, action: str, summary: str, *,
    target: str | None = None, detail: dict | None = None, undo: dict | None = None,
) -> int | None:
    try:
        return await db.insert_admin_action(
            datetime.now(KST).replace(microsecond=0).isoformat(),
            actor_discord_id or None,
            await actor_name(actor_discord_id),
            source if source in ("web", "discord", "api") else "web",
            action,
            target,
            summary,
            json.dumps(detail, ensure_ascii=False) if detail is not None else None,
            json.dumps(undo, ensure_ascii=False) if undo is not None else None,
        )
    except Exception as e:
        print(f"[admin_log] 기록 실패 ({action}): {type(e).__name__}: {e}")
        return None


async def list_actions(kind: str = "all", limit: int = 100) -> list[dict]:
    limit = min(max(int(limit), 1), 500)
    rows = await db.list_admin_actions(KIND_PREFIXES.get(kind), limit)
    return [
        {
            "id": r["id"],
            "at": r["at"],
            "actor_name": r["actor_name"],
            "source": r["source"],
            "action": r["action"],
            "summary": r["summary"],
            "undoable": bool(r["undo_json"]) and not r["undone_at"],
            "undone_at": r["undone_at"],
        }
        for r in rows
    ]


async def _perform_undo(undo: dict, discord_id: str) -> tuple[bool, str | None]:
    from bot.data import raids as raids_module

    kind = undo.get("type")
    if kind in ("party_reopen", "party_close"):
        from bot.api import bot_ref
        from bot.ui.views import _close_party_core, _reopen_party_core

        core = _reopen_party_core if kind == "party_reopen" else _close_party_core
        result = await core(bot_ref.get_bot(), undo["message_id"], discord_id, log_admin=False)
        return bool(result.get("success")), result.get("reason")
    if kind == "raid_rename":
        current, original = undo["from"], undo["to"]
        if not await db.raid_exists(current):
            return False, f'"{current}" 레이드를 찾을 수 없습니다.'
        if await db.raid_exists(original):
            return False, f'이미 "{original}" 이름의 레이드가 있습니다.'
        await db.rename_raid(current, original)
        await raids_module.reload()
        return True, None
    if kind == "raid_active":
        if not await db.set_raid_active(undo["name"], bool(undo["is_active"])):
            return False, "레이드를 찾을 수 없습니다."
        await raids_module.reload()
        return True, None
    if kind == "tracked_items":
        from bot.services import loa_content

        await loa_content.set_tracked_items(list(undo.get("names") or []))
        return True, None
    return False, "되돌릴 수 없는 기록입니다."


async def undo_action(action_id: int, discord_id: str, source: str = "web") -> dict:
    row = await db.get_admin_action(action_id)
    if not row:
        return {"success": False, "reason": "기록을 찾을 수 없습니다."}
    if not row.get("undo_json"):
        return {"success": False, "reason": "되돌릴 수 없는 기록입니다."}
    if row.get("undone_at"):
        return {"success": False, "reason": "이미 되돌린 기록입니다."}
    try:
        undo = json.loads(row["undo_json"])
    except (TypeError, ValueError):
        return {"success": False, "reason": "되돌릴 수 없는 기록입니다."}

    now = datetime.now(KST).replace(microsecond=0).isoformat()
    # 먼저 선점해서 두 번 눌러도 한 번만 되돌린다
    if not await db.set_admin_action_undone(action_id, now):
        return {"success": False, "reason": "이미 되돌린 기록입니다."}
    try:
        ok, reason = await _perform_undo(undo, discord_id)
    except Exception as e:
        ok, reason = False, f"되돌리지 못했습니다: {e}"
    if not ok:
        await db.set_admin_action_undone(action_id, None)
        return {"success": False, "reason": reason or "되돌리지 못했습니다."}

    await record_admin_action(
        discord_id, source, f"{row['action']}.undo", f"되돌리기: {row['summary']}",
        target=row.get("target"), detail={"undone_action_id": action_id},
    )
    return {"success": True, "reason": None}
