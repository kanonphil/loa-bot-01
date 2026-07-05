"""원정대(캐릭터 등록/동기화) 관련 다중 계정(부계정) 핵심 로직.

디스코드 명령어(bot/ui/views.py AddCharacterModal, ExpeditionView.sync_btn)와
웹앱이 호출하는 내부 API(bot/api/routes/internal.py)가 동일하게 사용하는
단일 로직 — 여기 말고 각자 구현하면 계정별 처리 규칙이 어긋날 수 있으니
반드시 이 모듈을 통해서만 판단/실행할 것.
"""
from __future__ import annotations

import asyncio

import config
import bot.api.lostark as loa
import bot.database.manager as db


async def verify_and_register_api_key(
    discord_id: str, key: str, name: str
) -> tuple[bool, str, list[dict] | None, int | None]:
    """API 키 검증 + 길드 확인 + 저장까지 처리. 매번 새 계정(부계정)으로 추가된다 — 몇 번을 호출해도
    기존에 등록된 다른 계정은 그대로 유지된다.
    (성공 여부, 유저에게 보낼 메시지, 원정대 캐릭터 목록, 새로 등록된 api_key_id) 반환.
    discord.Interaction 없이 동작해서 디스코드 모달(ApiKeyModal)과 웹 POST
    /expedition/add-account가 동일하게 사용한다."""
    try:
        siblings = await loa.get_siblings(key, name)
    except RuntimeError as e:
        return False, f"❌ API 키 검증 실패: {e}", None, None

    if siblings is None:
        # 캐릭터를 못 찾았지만 API 키는 유효할 수 있음 (404)
        # 401이었으면 RuntimeError가 발생했을 것
        return False, (
            f"⚠️ API 키는 유효하지만 **{name}** 캐릭터를 찾을 수 없습니다.\n"
            "캐릭터 이름을 다시 확인한 뒤 재시도해주세요.\n\n"
            "API 키는 저장되지 않았습니다."
        ), None, None

    # 길드 확인 — 실제 "동물롱장" 소속만 등록 허용 (디스코드 서버엔 길드원 아닌 인원도 있음)
    # 부계정을 추가로 등록할 때도 매번 동일하게 확인한다.
    if config.REQUIRED_GUILD_NAME:
        try:
            armory = await loa.get_armory(key, name)
        except RuntimeError as e:
            return False, f"❌ 길드 확인 중 오류: {e}", None, None
        profile = (armory or {}).get("ArmoryProfile") or {}
        guild_name = profile.get("GuildName") or ""
        if guild_name != config.REQUIRED_GUILD_NAME:
            detail = f" (현재: {guild_name})" if guild_name else " (길드 미가입)"
            return False, (
                f"❌ **{name}** 캐릭터는 **{config.REQUIRED_GUILD_NAME}** 길드 소속이 아닙니다{detail}.\n"
                "API 키는 저장되지 않았습니다."
            ), None, None

    api_key_id = await db.add_user_api_key(discord_id, name, key)
    return True, (
        f"✅ **API 키 등록 완료!** (원정대 캐릭터 **{len(siblings)}개** 확인)\n\n"
        f"원정대에 등록할 캐릭터를 선택하세요:"
    ), siblings, api_key_id


async def resolve_character_account(
    discord_id: str, character_name: str
) -> tuple[dict | None, int | None, str | None]:
    """discord_id가 등록한 계정들 중 character_name이 실제로 속한 계정을 찾는다.

    등록된 계정을 등록 순서대로 하나씩 시도해서, 그 계정의 원정대(siblings)
    목록에 character_name이 있는 첫 번째 계정을 사용한다.

    반환: (해당 캐릭터의 siblings 목록 중 character_name 항목, 그 계정의 api_key_id, 에러 메시지)
    성공 시 에러 메시지는 None. 어느 계정에서도 못 찾으면 (None, None, 에러메시지).
    """
    accounts = await db.list_user_api_keys(discord_id)
    if not accounts:
        return None, None, "먼저 /api등록으로 API 키를 등록해주세요."

    last_error: str | None = None
    for acc in accounts:
        api_key = await db.get_user_api_key_by_id(acc["id"])
        if not api_key:
            continue
        try:
            siblings = await loa.get_siblings(api_key, character_name)
        except RuntimeError as e:
            last_error = str(e)
            continue
        if not siblings:
            continue
        char = next((c for c in siblings if c.get("CharacterName") == character_name), None)
        if char is not None:
            return char, acc["id"], None

    if last_error:
        return None, None, last_error
    return None, None, f"{character_name} 캐릭터를 찾을 수 없습니다. 이름과 API 키를 확인해주세요."


async def register_character_auto_detect(
    discord_id: str, character_name: str
) -> dict:
    """캐릭터를 등록할 계정을 자동으로 찾아 등록까지 처리.

    /캐릭터등록(AddCharacterModal), 웹 POST /characters/add 에서 공유하는 핵심 로직.
    반환: {"success": bool, "reason": str} 또는
          {"success": True, "character_name", "character_class", "item_level"}
    """
    name = character_name.strip()

    char, api_key_id, error = await resolve_character_account(discord_id, name)
    if char is None:
        return {"success": False, "reason": error}

    # 본인 원정대 캐릭터인지 확인 — 이미 등록된 캐릭터가 있다면 그 캐릭터들과
    # 같은 원정대(같은 계정)에 속해야 한다. resolve_character_account가 이미
    # "등록된 계정들" 중에서만 찾으므로 사실상 이 캐릭터는 해당 계정 소속이 확정된 상태지만,
    # 계정 자체가 남의 원정대일 수는 없으므로 별도 검증은 필요 없다.

    added = await db.add_character(discord_id, name, api_key_id=api_key_id)
    if not added:
        return {"success": False, "reason": f"{name}은(는) 이미 등록된 캐릭터입니다."}

    level = loa.parse_item_level(char)
    char_class = char.get("CharacterClassName", "?")
    if level > 0:
        await db.update_character_cache(discord_id, name, level, char_class, api_key_id=api_key_id)

    return {
        "success": True,
        "character_name": name,
        "character_class": char_class,
        "item_level": level,
    }


async def sync_characters_for_discord_id(discord_id: str) -> tuple[int, int]:
    """유저의 등록된 모든 캐릭터를, 각자 연결된 계정(api_key_id)별로 그룹핑해서 동기화.

    Discord "동기화" 버튼(ExpeditionView.sync_btn)과 웹 POST /characters/sync,
    그리고 일일 자동 동기화 태스크(bot.bot.LoABot.account_sync_task)가
    공유하는 핵심 로직.

    api_key_id가 없는(레거시) 캐릭터는 유저의 첫 번째 등록 계정으로 간주해 동기화한다.

    반환: (updated_count, total_count)
    """
    char_rows = await db.get_cached_characters(discord_id, max_age_hours=99999)
    char_names = [c["character_name"] for c in char_rows]
    if not char_names:
        return 0, 0

    accounts = await db.list_user_api_keys(discord_id)
    if not accounts:
        return 0, len(char_names)

    # 캐릭터를 api_key_id별로 그룹핑. api_key_id가 없으면(레거시 데이터) 첫 계정으로 fallback.
    default_key_id = accounts[0]["id"]
    chars_by_key: dict[int, list[str]] = {}
    for name in char_names:
        key_id = await db.get_character_api_key_id(discord_id, name)
        if key_id is None:
            key_id = default_key_id
        chars_by_key.setdefault(key_id, []).append(name)

    updated = 0
    for key_id, names in chars_by_key.items():
        api_key = await db.get_user_api_key_by_id(key_id)
        if not api_key:
            continue
        try:
            siblings = await loa.get_siblings(api_key, names[0])
            siblings_map = {c["CharacterName"]: c for c in siblings} if siblings else {}
        except Exception:
            siblings_map = {}

        for name in names:
            char = siblings_map.get(name)
            if not char:
                continue
            level = loa.parse_item_level(char)
            char_class = char.get("CharacterClassName", "?")
            if level > 0:
                await db.update_character_cache(discord_id, name, level, char_class, api_key_id=key_id)
                updated += 1

    return updated, len(char_names)


async def sync_all_accounts_daily() -> None:
    """모든 유저의 모든 등록 계정을 순회하며 캐릭터 정보를 갱신하는 일일 자동 동기화.

    bot.bot.LoABot.account_sync_task(@tasks.loop(hours=24))에서 호출된다.
    계정 하나가 실패(키 만료/네트워크 오류)해도 다른 계정 처리에 영향 주지 않도록
    각 계정 처리를 try/except로 감싼다.
    """
    all_keys = await db.get_all_api_keys()
    for entry in all_keys:
        try:
            key_id = entry["id"]
            api_key = await db.get_user_api_key_by_id(key_id)
            if not api_key:
                continue
            char_names = await db.get_characters_by_api_key_id(key_id)
            if not char_names:
                continue
            try:
                siblings = await loa.get_siblings(api_key, char_names[0])
            except RuntimeError:
                continue
            siblings_map = {c["CharacterName"]: c for c in siblings} if siblings else {}
            for name in char_names:
                char = siblings_map.get(name)
                if not char:
                    continue
                level = loa.parse_item_level(char)
                char_class = char.get("CharacterClassName", "?")
                if level > 0:
                    await db.update_character_cache(
                        entry["discord_id"], name, level, char_class, api_key_id=key_id
                    )
        except Exception as e:
            print(f"[account_sync_task] 계정 동기화 실패 (api_key_id={entry.get('id')}): {e}")
        await asyncio.sleep(1)
