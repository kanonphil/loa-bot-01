import asyncio
import time
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


class LoaMaintenanceError(RuntimeError):
    """503 — 로스트아크 점검 중. RuntimeError의 하위 클래스라 기존 호출부(RuntimeError만
    잡는 곳)는 그대로 동작하고, 공용 데이터 수집(bot/services/loa_content.py)만 이걸 따로
    잡아 "점검 중"으로 표시하고 그 주기의 나머지 호출을 건너뛴다."""


# 키별 남은 요청 수(X-RateLimit-Remaining)와 리셋 시각(X-RateLimit-Reset, epoch초).
# 키 원문 대신 해시를 키로 써서 메모리에 키가 하나 더 남지 않게 한다.
RATE_LIMIT_LOW_WATERMARK = 10
RATE_LIMIT_MAX_WAIT = 60.0
_rate_state: dict[int, tuple[int, float]] = {}


def _note_rate_limit(api_key: str, headers) -> None:
    try:
        remaining = headers.get("X-RateLimit-Remaining")
        if remaining is None:
            return
        reset = headers.get("X-RateLimit-Reset")
        reset_at = float(reset) if reset not in (None, "") else time.time() + 60
        _rate_state[hash(api_key)] = (int(remaining), reset_at)
    except (TypeError, ValueError):
        pass


def rate_limit_wait_seconds(api_key: str, now: float | None = None) -> float:
    """남은 요청 수가 RATE_LIMIT_LOW_WATERMARK 미만이면 리셋 시각까지 기다릴 초(최대
    RATE_LIMIT_MAX_WAIT). 아니면 0."""
    state = _rate_state.get(hash(api_key))
    if not state:
        return 0.0
    remaining, reset_at = state
    if remaining >= RATE_LIMIT_LOW_WATERMARK:
        return 0.0
    now = time.time() if now is None else now
    return max(0.0, min(reset_at - now, RATE_LIMIT_MAX_WAIT))


async def _request(
    method: str, api_key: str, path: str, *, params: dict = None, json_body: dict = None,
    timeout: float = 10,
) -> Optional[dict | list]:
    wait = rate_limit_wait_seconds(api_key)
    if wait > 0:
        print(f"[lostark] 남은 요청 수가 적어 {wait:.0f}초 대기")
        await asyncio.sleep(wait)
    session = await _get_session()
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    if json_body is not None:
        headers["Content-Type"] = "application/json"
    url = f"{LOA_API_BASE}{path}"
    try:
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with session.request(
            method, url, headers=headers, params=params, json=json_body, timeout=client_timeout,
        ) as resp:
            _note_rate_limit(api_key, resp.headers)
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
            if resp.status == 503:
                raise LoaMaintenanceError("로스트아크 점검 중입니다 (503).")
            # 그 외 오류: 상태코드와 응답 본문 포함
            body = await resp.text()
            raise RuntimeError(f"API 오류 {resp.status}: {body[:200]}")
    except aiohttp.ClientError as e:
        raise RuntimeError(f"네트워크 오류: {e}") from e
    # Python 3.10(봇 서버)에서는 asyncio.TimeoutError가 내장 TimeoutError와 별개 클래스라
    # 둘 다 잡아야 한다 — 하나만 잡으면 타임아웃이 그대로 새어나가 호출부가 500/무응답이 된다.
    except (asyncio.TimeoutError, TimeoutError) as e:
        raise RuntimeError(f"API 응답 시간 초과 ({timeout:g}초). 잠시 후 다시 시도해주세요.") from e


async def _get(api_key: str, path: str, params: dict = None, timeout: float = 10) -> Optional[dict | list]:
    return await _request("GET", api_key, path, params=params, timeout=timeout)


async def _post(api_key: str, path: str, body: dict, timeout: float = 10) -> Optional[dict | list]:
    return await _request("POST", api_key, path, json_body=body, timeout=timeout)


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


# ── 공용 데이터(공지/이벤트/캘린더/거래소) ─────────────────────
# 응답 구조는 bot/services/loa_content.py가 방어적으로 파싱한다(필드 누락/추가에 관대).
# 공용 데이터는 15초 타임아웃 — 캘린더 응답이 수백 KB라 10초는 빠듯할 수 있다.
CONTENT_TIMEOUT = 15


async def get_notices(api_key: str, notice_type: str | None = None) -> Optional[list]:
    params = {"type": notice_type} if notice_type else None
    return await _get(api_key, "/news/notices", params=params, timeout=CONTENT_TIMEOUT)


async def get_events(api_key: str) -> Optional[list]:
    return await _get(api_key, "/news/events", timeout=CONTENT_TIMEOUT)


async def get_calendar(api_key: str) -> Optional[list]:
    return await _get(api_key, "/gamecontents/calendar", timeout=CONTENT_TIMEOUT)


async def get_market_options(api_key: str) -> Optional[dict]:
    return await _get(api_key, "/markets/options", timeout=CONTENT_TIMEOUT)


async def search_market_items(api_key: str, item_name: str, category_code: int, page_no: int = 1) -> Optional[dict]:
    body = {
        "Sort": "GRADE",
        "CategoryCode": category_code,
        "CharacterClass": None,
        "ItemTier": None,
        "ItemGrade": None,
        "ItemName": item_name,
        "PageNo": page_no,
        "SortCondition": "ASC",
    }
    return await _post(api_key, "/markets/items", body, timeout=CONTENT_TIMEOUT)


async def get_market_item(api_key: str, item_id: int) -> Optional[list]:
    return await _get(api_key, f"/markets/items/{int(item_id)}", timeout=CONTENT_TIMEOUT)
