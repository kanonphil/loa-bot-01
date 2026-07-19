import aiohttp
from urllib.parse import quote
from typing import Optional

LOA_API_BASE = "https://developer-lostark.game.onstove.com"
ARMORY_FILTERS = "profiles+equipment+engravings+gems+cards"
ARMORY_DETAIL_FILTERS = "profiles+equipment+combat-skills+engravings+cards+arkpassive+gems+arkgrid"

# 공유 세션 (API 키는 요청마다 헤더로 전달)
_shared_session: Optional[aiohttp.ClientSession] = None


async def _get_session() -> aiohttp.ClientSession:
    global _shared_session
    if _shared_session is None or _shared_session.closed:
        _shared_session = aiohttp.ClientSession()
    return _shared_session


async def close_session() -> None:
    global _shared_session
    if _shared_session and not _shared_session.closed:
        await _shared_session.close()


async def _get(api_key: str, path: str, params: dict = None) -> Optional[dict | list]:
    session = await _get_session()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    url = f"{LOA_API_BASE}{path}"
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with session.get(url, headers=headers, params=params, timeout=timeout) as resp:
            if resp.status == 200:
                return await resp.json()
            if resp.status == 404:
                return None
            if resp.status == 401:
                raise RuntimeError("API 키가 유효하지 않습니다. 발급된 키를 다시 확인해주세요.")
            if resp.status == 403:
                raise RuntimeError("API 접근이 거부되었습니다 (403). 키 권한을 확인해주세요.")
            if resp.status == 429:
                raise RuntimeError("API 요청 한도 초과 (429). 잠시 후 다시 시도해주세요.")
            # 그 외 오류: 상태코드와 응답 본문 포함
            body = await resp.text()
            raise RuntimeError(f"API 오류 {resp.status}: {body[:200]}")
    except aiohttp.ClientError as e:
        raise RuntimeError(f"네트워크 오류: {e}") from e
    except TimeoutError as e:
        raise RuntimeError("API 응답 시간 초과 (10초). 잠시 후 다시 시도해주세요.") from e


def _enc(name: str) -> str:
    """한글 캐릭터명을 URL 경로에 안전하게 인코딩"""
    return quote(name, safe="")


# ── 공개 API 함수 ────────────────────────────────────────

async def get_siblings(api_key: str, character_name: str) -> Optional[list[dict]]:
    """원정대 캐릭터 목록"""
    return await _get(api_key, f"/characters/{_enc(character_name)}/siblings")


async def get_armory(api_key: str, character_name: str, filters: str = ARMORY_FILTERS) -> Optional[dict]:
    """캐릭터 상세 정보"""
    return await _get(
        api_key,
        f"/armories/characters/{_enc(character_name)}",
        params={"filters": filters},
    )


def parse_combat_power(raw) -> Optional[float]:
    """CombatPower 필드 파싱. 로스트아크 오픈API는 이 값을 쉼표가 섞인 문자열로
    내려준다(예: "4,368.47") — 콤마 때문에 float() 파싱이 그대로 실패해서 대부분의
    캐릭터(전투력이 1,000 이상이라 쉼표가 붙는 경우)가 조용히 None 처리되어 랭킹에서
    아예 빠지던 버그가 있었다. 콤마만 제거하면 게임 내 전투정보실에 표시되는 값과
    동일하다(실측 확인됨). 소수점 2자리까지도 의미 있는 정보라 반올림해서 버리지
    않고 그대로 보존한다(정수로 반올림하지 않음)."""
    if raw is None:
        return None
    try:
        cleaned = str(raw).replace(",", "")
        return round(float(cleaned), 2)
    except (TypeError, ValueError):
        return None


async def get_combat_power(api_key: str, character_name: str) -> Optional[float]:
    """캐릭터 전투력(CombatPower) 하나만 가볍게 조회 — 랭킹 캐시 갱신용.
    프로필 필터만 써서 응답을 최소화한다. 값이 없거나 숫자가 아니면 None."""
    data = await get_armory(api_key, character_name, filters="profiles")
    if not data:
        return None
    raw = (data.get("ArmoryProfile") or {}).get("CombatPower")
    return parse_combat_power(raw)


async def get_character_info(api_key: str, character_name: str) -> Optional[dict]:
    """원정대 목록에서 해당 캐릭터 기본 정보 추출"""
    siblings = await get_siblings(api_key, character_name)
    if not siblings:
        return None
    for char in siblings:
        if char.get("CharacterName") == character_name:
            return char
    return None


def parse_item_level(char: dict | str | None) -> float:
    """dict(캐릭터 정보) 또는 레벨 문자열을 float으로 변환. ItemMaxLevel → ItemAvgLevel 순 fallback."""
    if isinstance(char, dict):
        level_str = char.get("ItemMaxLevel") or char.get("ItemAvgLevel") or "0"
    else:
        level_str = char or "0"
    try:
        return float(str(level_str).replace(",", ""))
    except (ValueError, TypeError):
        return 0.0
