"""관리자 수동 DM — 파티원 전체 / 등록 유저 전원.

관리자 API(bot/api/routes/subscriptions.py, X-API-Key)와 웹앱용 internal 라우트
(bot/ui/views.py의 _admin_notify_party_core 등)가 같은 발송 로직을 쓴다."""
import bot.database.manager as db


async def _send(bot, discord_id: str, content: str) -> bool:
    try:
        user = await bot.fetch_user(int(discord_id))
        await user.send(content)
        return True
    except Exception:
        return False


async def dm_party_members(bot, message_id: str, content: str) -> tuple[int, int]:
    """(보낸 수, 대상 수)."""
    slots = await db.get_party_slots(message_id)
    sent = 0
    for s in slots:
        if await _send(bot, s["discord_id"], content):
            sent += 1
    return sent, len(slots)


async def dm_all_users(bot, content: str) -> tuple[int, int]:
    """API 등록 유저 전원에게 — (보낸 수, 대상 수)."""
    ids = await db.get_all_user_ids()
    sent = 0
    for discord_id in ids:
        if await _send(bot, discord_id, content):
            sent += 1
    return sent, len(ids)
