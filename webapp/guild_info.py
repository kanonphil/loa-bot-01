"""사이드바에 쓸 길드 아이콘을 앱 시작 시 한 번만 봇 서버에서 가져와 메모리에 캐시.
길드 아이콘은 거의 안 바뀌니 매 페이지 요청마다 봇 서버를 호출할 필요가 없다.
봇 서버가 응답 안 해도(오프라인/재시작 중) 앱 자체는 정상 기동해야 하므로,
실패하면 그냥 기본 로고(logo.svg)를 계속 쓴다."""
import logging

from webapp import config

logger = logging.getLogger("webapp")

_icon_url: str | None = None


async def refresh() -> None:
    global _icon_url
    from webapp.clients import bot_client

    try:
        info = await bot_client.get_guild_info(config.DISCORD_GUILD_ID)
        _icon_url = info.get("icon_url")
    except Exception:
        logger.warning("길드 아이콘 조회 실패 — 기본 로고를 사용합니다.", exc_info=True)


def get_name() -> str:
    return config.GUILD_NAME


def get_icon_url() -> str | None:
    return _icon_url
