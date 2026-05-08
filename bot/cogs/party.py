import discord
from discord import app_commands
from discord.ext import commands

import bot.database.manager as db
from bot.ui.views import RaidSelectView


class Party(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="공대채널설정",
        description="공대 모집글이 올라갈 포럼 채널을 설정합니다. (관리자 전용)",
    )
    @app_commands.describe(채널="공대 모집글을 올릴 포럼 채널")
    @app_commands.default_permissions(administrator=True)
    async def set_forum(self, interaction: discord.Interaction, 채널: discord.ForumChannel) -> None:
        await db.set_forum_channel(str(interaction.guild_id), str(채널.id))
        await interaction.response.send_message(
            f"✅ 공대 모집 포럼 채널이 {채널.mention}으로 설정되었습니다.", ephemeral=True
        )

    @app_commands.command(
        name="공대모집",
        description="레이드 공대를 모집합니다. 레이드 → 난이도 → 숙련도 → 일정 순으로 설정됩니다.",
    )
    async def recruit(self, interaction: discord.Interaction) -> None:
        guild_id  = str(interaction.guild_id)
        forum_id  = await db.get_forum_channel_id(guild_id)
        if not forum_id:
            await interaction.response.send_message(
                "먼저 `/공대채널설정`으로 포럼 채널을 지정해주세요. (관리자 전용)", ephemeral=True
            )
            return
        leader_id = str(interaction.user.id)
        api_key = await db.get_user_api_key(leader_id)
        if not api_key:
            await interaction.response.send_message(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
            )
            return
        view = RaidSelectView(leader_id=leader_id, forum_channel_id=forum_id)
        await interaction.response.send_message(
            "모집할 레이드를 선택해주세요:", view=view, ephemeral=True
        )

    @app_commands.command(
        name="공대확인",
        description="공대 모집 포럼 채널로 이동합니다.",
    )
    async def party_list(self, interaction: discord.Interaction) -> None:
        guild_id = str(interaction.guild_id)
        forum_id = await db.get_forum_channel_id(guild_id)
        if not forum_id:
            await interaction.response.send_message(
                "공대 모집 포럼 채널이 설정되지 않았습니다.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"<#{forum_id}>", ephemeral=True
        )

    @app_commands.command(
        name="내공대",
        description="내가 참여 중인 공대 목록을 확인합니다.",
    )
    async def my_parties(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        parties    = await db.get_user_parties(discord_id)
        if not parties:
            await interaction.response.send_message(
                "현재 참여 중인 공대가 없습니다.", ephemeral=True
            )
            return
        pairs = [(p, await db.get_party_slots(p["message_id"])) for p in parties]
        await interaction.response.send_message(embed=party_list_embed(pairs), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Party(bot))
