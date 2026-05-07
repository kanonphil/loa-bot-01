from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select

import bot.api.lostark as loa
import bot.database.manager as db
from bot.ui.embeds import character_embed


async def _send_dashboard(
    interaction: discord.Interaction,
    api_key: str,
    char_name: str,
    *,
    followup: bool = False,
) -> None:
    try:
        armory = await loa.get_armory(api_key, char_name)
    except RuntimeError as e:
        msg = str(e)
        if followup:
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return
    if armory is None:
        msg = f"**{char_name}** 캐릭터를 찾을 수 없습니다."
        if followup:
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return
    embed = character_embed(armory)
    if followup:
        await interaction.followup.send(embed=embed)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=None)


class Dashboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="대시보드", description="캐릭터의 아이템 레벨, 각인, 보석 정보를 카드로 표시합니다.")
    async def dashboard(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        api_key    = await db.get_user_api_key(discord_id)
        if not api_key:
            await interaction.response.send_message(
                "먼저 `/api등록` 명령어로 API 키를 등록해주세요.", ephemeral=True
            )
            return

        chars = await db.get_user_characters(discord_id)
        if not chars:
            await interaction.response.send_message(
                "먼저 `/캐릭터등록`으로 캐릭터를 등록해주세요.", ephemeral=True
            )
            return

        if len(chars) == 1:
            await interaction.response.defer(thinking=True)
            await _send_dashboard(interaction, api_key, chars[0], followup=True)
            return

        # 캐시 기반 Select 옵션
        cached  = {c["character_name"]: c for c in await db.get_cached_characters(discord_id, max_age_hours=99999)}
        options = []
        for name in chars:
            c    = cached.get(name, {})
            lv   = c.get("item_level")
            cls  = c.get("character_class") or "?"
            desc = f"{cls} | {lv:.0f}" if lv else cls
            options.append(discord.SelectOption(label=name, description=desc, value=name))

        class CharSelect(View):
            def __init__(self) -> None:
                super().__init__(timeout=60)
                sel = Select(placeholder="조회할 캐릭터를 선택하세요", options=options)
                sel.callback = self._on_select
                self.add_item(sel)

            async def _on_select(self, inter: discord.Interaction) -> None:
                selected = inter.data["values"][0]
                await inter.response.defer()
                await _send_dashboard(inter, api_key, selected)

        await interaction.response.send_message(
            "조회할 캐릭터를 선택하세요:", view=CharSelect(), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Dashboard(bot))
