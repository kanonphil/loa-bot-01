import discord
from discord import app_commands
from discord.ext import commands

import bot.database.manager as db
from bot.services.expedition import remove_character_and_leave_parties, sync_characters_for_discord_id
from bot.ui.embeds import expedition_embed, no_characters_embed
from bot.ui.views import ExpeditionView, AddCharacterModal


class Expedition(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="원정대", description="등록된 내 캐릭터 목록을 한눈에 확인합니다.")
    @app_commands.checks.cooldown(1, 30.0)
    async def expedition(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        discord_id = str(interaction.user.id)
        accounts = await db.list_user_api_keys(discord_id)
        if not accounts:
            await interaction.followup.send(
                "먼저 `/api등록` 명령어로 API 키를 등록해주세요.", ephemeral=True
            )
            return

        char_names = await db.get_user_characters(discord_id)
        view = ExpeditionView(discord_id)

        if not char_names:
            await interaction.followup.send(
                embed=no_characters_embed(interaction.user), view=view, ephemeral=True
            )
            return

        # 등록된 모든 계정(부계정 포함)을 그룹핑해서 조회하는 공용 로직 —
        # sync_btn/웹 동기화 API/일일 자동 동기화와 동일한 코드.
        await sync_characters_for_discord_id(discord_id)

        cached = await db.get_cached_characters(discord_id, max_age_hours=99999)
        characters = [
            {
                "CharacterName": c["character_name"],
                "CharacterClassName": c["character_class"] or "조회 실패",
                "ItemMaxLevel": str(c["item_level"] or 0),
                "ServerName": "?",
            }
            for c in cached
        ]

        await interaction.followup.send(
            embed=expedition_embed(interaction.user, characters), view=view, ephemeral=True
        )

    @app_commands.command(name="캐릭터등록", description="원정대에 캐릭터를 등록합니다.")
    async def register_char(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        accounts = await db.list_user_api_keys(discord_id)
        if not accounts:
            await interaction.response.send_message(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
            )
            return
        # 어느 계정(부계정 포함) 소속인지는 AddCharacterModal 제출 시 자동 판별된다.
        await interaction.response.send_modal(AddCharacterModal(discord_id))

    @app_commands.command(name="캐릭터삭제", description="원정대에서 캐릭터를 삭제합니다.")
    @app_commands.describe(char_name="삭제할 캐릭터 이름")
    @app_commands.rename(char_name="캐릭터명")
    async def unregister_char(self, interaction: discord.Interaction, char_name: str) -> None:
        removed = await remove_character_and_leave_parties(interaction.client, str(interaction.user.id), char_name)
        if removed:
            await interaction.response.send_message(f"🗑️ **{char_name}** 삭제 완료.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"**{char_name}**은(는) 등록된 캐릭터가 아닙니다.", ephemeral=True
            )


    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ {error.retry_after:.0f}초 후 다시 시도해주세요.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Expedition(bot))
