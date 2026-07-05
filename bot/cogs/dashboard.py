from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select

import bot.api.lostark as loa
import bot.database.manager as db
from bot.ui.embeds import character_embed


async def _resolve_api_key_for_character(discord_id: str, char_name: str, fallback_key: str) -> str:
    """캐릭터가 연결된 계정(api_key_id)의 키를 우선 사용 — 부계정 캐릭터도 올바른 키로 조회.
    api_key_id가 없는(레거시) 캐릭터는 fallback_key(레거시 단일 키)를 그대로 사용."""
    key_id = await db.get_character_api_key_id(discord_id, char_name)
    if key_id is not None:
        resolved = await db.get_user_api_key_by_id(key_id)
        if resolved:
            return resolved
    return fallback_key


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
        await interaction.followup.send(embed=embed, ephemeral=True)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=None)


class Dashboard(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="대시보드", description="캐릭터의 아이템 레벨, 각인, 보석 정보를 카드로 표시합니다.")
    @app_commands.checks.cooldown(1, 30.0)
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
            await interaction.response.defer(thinking=True, ephemeral=True)
            resolved_key = await _resolve_api_key_for_character(discord_id, chars[0], api_key)
            await _send_dashboard(interaction, resolved_key, chars[0], followup=True)
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
                resolved_key = await _resolve_api_key_for_character(discord_id, selected, api_key)
                await _send_dashboard(inter, resolved_key, selected, followup=True)

        await interaction.response.send_message(
            "조회할 캐릭터를 선택하세요:", view=CharSelect(), ephemeral=True
        )


    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            await interaction.response.send_message(
                f"⏳ {error.retry_after:.0f}초 후 다시 시도해주세요.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Dashboard(bot))
