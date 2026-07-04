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
