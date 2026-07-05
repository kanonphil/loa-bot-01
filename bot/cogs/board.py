import discord
from discord import app_commands
from discord.ext import commands

import bot.database.manager as db


class Board(commands.Cog):
    """길드 커뮤니티 게시판 — 게시글 자체는 웹에서만 작성하고, 이 코그는 디스코드
    알림을 보낼 채널/역할을 지정하는 관리자 설정 커맨드만 담당한다."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="게시판설정",
        description="게시판 이벤트 알림을 올릴 채널과 멘션할 역할을 설정합니다. (관리자 전용)",
    )
    @app_commands.describe(채널="이벤트 게시글이 올라올 때 알림을 보낼 채널", 역할="알림에서 멘션할 역할 (선택)")
    @app_commands.default_permissions(administrator=True)
    async def set_board_channel(
        self,
        interaction: discord.Interaction,
        채널: discord.TextChannel,
        역할: discord.Role | None = None,
    ) -> None:
        await db.set_board_channel(
            str(interaction.guild_id), str(채널.id), str(역할.id) if 역할 else None
        )
        role_text = f", 멘션 역할 {역할.mention}" if 역할 else ""
        await interaction.response.send_message(
            f"✅ 게시판 알림 채널이 {채널.mention}으로 설정되었습니다{role_text}.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Board(bot))
