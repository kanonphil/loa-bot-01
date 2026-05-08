import discord
from discord import app_commands
from discord.ext import commands

import bot.api.lostark as loa
import bot.database.manager as db
from bot.ui.embeds import expedition_embed, no_characters_embed
from bot.ui.views import ExpeditionView, AddCharacterModal


class Expedition(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="원정대", description="등록된 내 캐릭터 목록을 한눈에 확인합니다.")
    async def expedition(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        discord_id = str(interaction.user.id)
        api_key = await db.get_user_api_key(discord_id)
        if not api_key:
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

        characters: list[dict] = []
        for name in char_names:
            try:
                char = await loa.get_character_info(api_key, name)
            except RuntimeError:
                char = None
            if char:
                lv  = loa.parse_item_level(char)
                cls = char.get("CharacterClassName", "?")
                if lv > 0:
                    await db.update_character_cache(discord_id, name, lv, cls)
                characters.append(char)
            else:
                characters.append({
                    "CharacterName": name, "CharacterClassName": "조회 실패",
                    "ItemMaxLevel": "0", "ServerName": "?",
                })

        await interaction.followup.send(
            embed=expedition_embed(interaction.user, characters), view=view, ephemeral=True
        )

    @app_commands.command(name="캐릭터등록", description="원정대에 캐릭터를 등록합니다.")
    async def register_char(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        api_key = await db.get_user_api_key(discord_id)
        if not api_key:
            await interaction.response.send_message(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
            )
            return
        await interaction.response.send_modal(AddCharacterModal(discord_id, api_key))

    @app_commands.command(name="캐릭터삭제", description="원정대에서 캐릭터를 삭제합니다.")
    @app_commands.describe(캐릭터명="삭제할 캐릭터 이름")
    async def unregister_char(self, interaction: discord.Interaction, 캐릭터명: str) -> None:
        removed = await db.remove_character(str(interaction.user.id), 캐릭터명)
        if removed:
            await interaction.response.send_message(f"🗑️ **{캐릭터명}** 삭제 완료.", ephemeral=True)
        else:
            await interaction.response.send_message(
                f"**{캐릭터명}**은(는) 등록된 캐릭터가 아닙니다.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Expedition(bot))
