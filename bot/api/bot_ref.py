"""
FastAPI 라우터에서 Discord 봇 인스턴스와 시작 시각을 참조하기 위한 모듈.
bot.py의 setup_hook에서 set_bot()을 호출해 등록한다.
"""
from __future__ import annotations
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from discord.ext import commands

_bot: "commands.Bot | None" = None
start_time: float = time.time()


def set_bot(bot: "commands.Bot") -> None:
    global _bot
    _bot = bot


def get_bot() -> "commands.Bot | None":
    return _bot
