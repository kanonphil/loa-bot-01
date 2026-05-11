import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select

import bot.api.lostark as loa
import bot.database.manager as db
from bot.ui.embeds import raid_checklist_embed
from bot.ui.views import RaidChecklistView


async def _show_checklist(
    interaction: discord.Interaction,
    discord_id: str,
    name: str,
    api_key: str,
    *,
    followup: bool = False,
) -> None:
    """캐릭터 이름으로 체크리스트를 렌더링. 캐시 우선, 없으면 API 호출."""
    cached = {c["character_name"]: c for c in await db.get_cached_characters(discord_id)}
    cache  = cached.get(name)

    if cache and cache["item_level"] is not None:
        item_level  = cache["item_level"]
    else:
        try:
            char = await loa.get_character_info(api_key, name)
        except RuntimeError as e:
            msg = str(e)
            if followup:
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        if char is None:
            msg = f"**{name}** 캐릭터를 찾을 수 없습니다."
            if followup:
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
            return
        item_level  = loa.parse_item_level(char)
        char_class  = char.get("CharacterClassName", "?")
        if item_level > 0:
            await db.update_character_cache(discord_id, name, item_level, char_class)

    completions = await db.get_completions(discord_id, name)
    embed = raid_checklist_embed(name, item_level, completions)
    view  = RaidChecklistView(discord_id, name, item_level, completions)

    if followup:
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)
    else:
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class Raid(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="레이드체크", description="이번 주 레이드 완료 여부를 버튼으로 체크합니다.")
    async def raid_check(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        api_key    = await db.get_user_api_key(discord_id)
        if not api_key:
            await interaction.response.send_message(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
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
            await _show_checklist(interaction, discord_id, chars[0], api_key, followup=True)
            return

        # 캐시 기반 Select 옵션 구성
        cached  = {c["character_name"]: c for c in await db.get_cached_characters(discord_id)}
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
                sel = Select(placeholder="체크할 캐릭터를 선택하세요", options=options)
                sel.callback = self._on_select
                self.add_item(sel)

            async def _on_select(self, inter: discord.Interaction) -> None:
                selected = inter.data["values"][0]
                await _show_checklist(inter, discord_id, selected, api_key)

        await interaction.response.send_message(
            "체크할 캐릭터를 선택하세요:", view=CharSelect(), ephemeral=True
        )

    @app_commands.command(name="전체레이드체크", description="등록된 모든 캐릭터의 레이드 현황을 확인합니다.")
    async def raid_check_all(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)

        discord_id = str(interaction.user.id)
        api_key = await db.get_user_api_key(discord_id)
        if not api_key:
            await interaction.followup.send(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
            )
            return

        char_names = await db.get_user_characters(discord_id)
        if not char_names:
            await interaction.followup.send(
                "등록된 캐릭터가 없습니다. `/캐릭터등록`으로 먼저 등록해주세요.", ephemeral=True
            )
            return

        embeds: list[discord.Embed] = []
        for name in char_names:
            try:
                char = await loa.get_character_info(api_key, name)
            except RuntimeError:
                continue
            if not char:
                continue
            item_level  = loa.parse_item_level(char)
            completions = await db.get_completions(discord_id, name)
            embeds.append(raid_checklist_embed(name, item_level, completions))

        if not embeds:
            await interaction.followup.send("캐릭터 정보를 불러올 수 없습니다.", ephemeral=True)
            return

        truncated = len(embeds) > 10
        await interaction.followup.send(
            content=f"⚠️ 캐릭터가 {len(embeds)}개라 처음 10개만 표시됩니다." if truncated else None,
            embeds=embeds[:10],
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Raid(bot))
