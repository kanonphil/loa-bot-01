import discord
from discord import app_commands
from discord.ext import commands

import bot.api.lostark as loa
import bot.database.manager as db
from bot.ui.embeds import character_embed


class Dashboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="대시보드", description="캐릭터의 아이템 레벨, 각인, 보석 정보를 카드로 표시합니다.")
    @app_commands.describe(캐릭터명="조회할 캐릭터 이름 (미입력시 첫 번째 등록 캐릭터)")
    async def dashboard(self, interaction: discord.Interaction, 캐릭터명: str | None = None) -> None:
        await interaction.response.defer(thinking=True)

        discord_id = str(interaction.user.id)
        api_key = await db.get_user_api_key(discord_id)
        if not api_key:
            await interaction.followup.send(
                "먼저 `/api등록` 명령어로 API 키를 등록해주세요.", ephemeral=True
            )
            return

        name = 캐릭터명
        if not name:
            chars = await db.get_user_characters(discord_id)
            if not chars:
                await interaction.followup.send(
                    "조회할 캐릭터 이름을 입력하거나 `/캐릭터등록`으로 캐릭터를 먼저 등록해주세요.",
                    ephemeral=True,
                )
                return
            name = chars[0]

        try:
            armory = await loa.get_armory(api_key, name)
        except RuntimeError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        if armory is None:
            await interaction.followup.send(
                f"**{name}** 캐릭터를 찾을 수 없습니다. 이름을 확인해주세요.", ephemeral=True
            )
            return

        await interaction.followup.send(embed=character_embed(armory))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Dashboard(bot))
