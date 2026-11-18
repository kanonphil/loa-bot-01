"""사이드바에 쓸 길드 아이콘을 봇 서버에서 가져와 메모리에 캐시.
길드 아이콘은 거의 안 바뀌니 매 페이지 요청마다 봇 서버를 호출할 필요가 없다.
봇 서버가 응답 안 해도(오프라인/재시작 중) 앱 자체는 정상 기동해야 하므로,
실패하면 기본 로고(logo.svg)를 쓰되 — 예전엔 기동 시 한 번만 시도해서 그 순간 봇이
꺼져 있었으면 다음 재시작까지 영영 기본 로고였다 — 이후 요청에서 백오프를 두고 다시 시도한다."""
import asyncio
import logging
import time

from webapp import config

logger = logging.getLogger("webapp")

_icon_url: str | None = None

_RETRY_MIN_SECONDS = 30
_RETRY_MAX_SECONDS = 600
_retry_delay = _RETRY_MIN_SECONDS
_next_attempt_at = 0.0  # time.monotonic() 기준
_inflight: asyncio.Task | None = None


async def refresh() -> None:
    global _icon_url, _retry_delay, _next_attempt_at
    from webapp.clients import bot_client

    try:
        info = await bot_client.get_guild_info(config.DISCORD_GUILD_ID)
        _icon_url = info.get("icon_url")
        _retry_delay = _RETRY_MIN_SECONDS
    except Exception:
        logger.warning("길드 아이콘 조회 실패 — 기본 로고를 사용합니다.", exc_info=True)
        _next_attempt_at = time.monotonic() + _retry_delay
        _retry_delay = min(_retry_delay * 2, _RETRY_MAX_SECONDS)


def get_name() -> str:
    return config.GUILD_NAME


def get_icon_url() -> str | None:
    """템플릿 전역 함수 — 아이콘이 아직 없으면(실패) 백오프 시간이 지난 뒤 백그라운드로 재시도한다.
    이번 렌더는 기다리지 않는다."""
    global _inflight
    if _icon_url is None and (_inflight is None or _inflight.done()) and time.monotonic() >= _next_attempt_at:
        try:
            _inflight = asyncio.get_running_loop().create_task(refresh())
        except RuntimeError:
            pass  # 이벤트 루프 밖에서 렌더(테스트 등) — 다음 기회에
    return _icon_url
