"""봇 서버(다른 머신)의 /api/internal 호출용 얇은 클라이언트."""
import httpx

from webapp import config


def _headers() -> dict:
    return {"X-Webapp-Key": config.BOT_API_WEBAPP_KEY}


async def is_registered(discord_id: str) -> bool:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/verify-user",
            params={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()["registered"]


async def get_user_characters(discord_id: str) -> list[dict]:
    """AI 상담 프롬프트에 넣을 캐릭터 정보. 실패해도 앱이 죽으면 안 되니 호출 측에서 감싸서 씀."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/user-characters",
            params={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_raids() -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/raids", headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()


async def get_raid_categories() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/raid-categories", headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()


async def get_completions(discord_id: str, character_name: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/completions",
            params={"discord_id": discord_id, "character_name": character_name},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def add_character(discord_id: str, character_name: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/characters/add",
            json={"discord_id": discord_id, "character_name": character_name},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def remove_character(discord_id: str, character_name: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/characters/remove",
            json={"discord_id": discord_id, "character_name": character_name},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def sync_characters(discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/characters/sync",
            json={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def toggle_completion(
    discord_id: str, character_name: str, raid_name: str, difficulty: str
) -> bool:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/completions/toggle",
            json={
                "discord_id": discord_id,
                "character_name": character_name,
                "raid_name": raid_name,
                "difficulty": difficulty,
            },
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()["completed"]


# ── 공대 모집 ─────────────────────────────────────────────

async def list_parties(guild_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/parties",
            params={"guild_id": guild_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_party(message_id: str) -> dict | None:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}", headers=_headers()
        )
        resp.raise_for_status()
        return resp.json()


async def get_party_eligibility(message_id: str, discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/eligibility",
            params={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def join_party(
    message_id: str,
    discord_id: str,
    character_name: str,
    role: str,
    party_group: int | None = None,
) -> dict:
    payload = {"discord_id": discord_id, "character_name": character_name, "role": role}
    if party_group is not None:
        payload["party_group"] = party_group
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/join",
            json=payload,
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def leave_party(message_id: str, discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/leave",
            json={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def get_proficiency_options() -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/proficiency-options",
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def create_party(
    discord_id: str,
    guild_id: str,
    raid_name: str,
    difficulty: str,
    proficiency: str,
    scheduled_datetime: str,
    memo: str | None,
) -> dict:
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/create",
            json={
                "discord_id": discord_id,
                "guild_id": guild_id,
                "raid_name": raid_name,
                "difficulty": difficulty,
                "proficiency": proficiency,
                "scheduled_datetime": scheduled_datetime,
                "memo": memo,
            },
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


# ── 파티장 관리 ───────────────────────────────────────────

async def close_party(message_id: str, discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/close",
            json={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def reopen_party(message_id: str, discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/reopen",
            json={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def clear_party(message_id: str, discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/clear",
            json={"discord_id": discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def cancel_party(message_id: str, discord_id: str, reason: str | None) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/cancel",
            json={"discord_id": discord_id, "reason": reason},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def kick_member(message_id: str, discord_id: str, target_discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/kick",
            json={"discord_id": discord_id, "target_discord_id": target_discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def reschedule_party(
    message_id: str, discord_id: str, scheduled_datetime: str, memo: str | None
) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/reschedule",
            json={"discord_id": discord_id, "scheduled_datetime": scheduled_datetime, "memo": memo},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()


async def transfer_leader(message_id: str, discord_id: str, new_leader_discord_id: str) -> dict:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{config.BOT_API_BASE_URL}/api/internal/parties/{message_id}/transfer-leader",
            json={"discord_id": discord_id, "new_leader_discord_id": new_leader_discord_id},
            headers=_headers(),
        )
        resp.raise_for_status()
        return resp.json()
