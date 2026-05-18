"""
레이드 구독 알림 시스템
유저가 특정 레이드+난이도를 구독하면 새 공대 모집 시 DM으로 알림을 받는다.
"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Select

import bot.database.manager as db
from bot.data.raids import RAIDS


# ── 구독 선택 뷰 ─────────────────────────────────────────

class RaidSelectView(View):
    """레이드 선택 → 난이도 선택 순으로 구독 처리."""

    def __init__(self, discord_id: str) -> None:
        super().__init__(timeout=120)
        self.discord_id = discord_id
        self._build_raid_select()

    def _build_raid_select(self) -> None:
        self.clear_items()
        options = [
            discord.SelectOption(
                label=name,
                description=info.get("category", ""),
                emoji=info.get("icon", "⚔️"),
                value=name,
            )
            for name, info in RAIDS.items()
            if info.get("is_active", True)
        ]
        if not options:
            return
        sel = Select(placeholder="구독할 레이드를 선택하세요", options=options[:25])
        sel.callback = self._on_raid_select
        self.add_item(sel)

    async def _on_raid_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 사용할 수 있습니다.", ephemeral=True)
            return
        self.selected_raid = interaction.data["values"][0]
        self._build_diff_select(self.selected_raid)
        await interaction.response.edit_message(
            content=f"**{self.selected_raid}** — 구독할 난이도를 선택하세요:", view=self
        )

    def _build_diff_select(self, raid_name: str) -> None:
        self.clear_items()
        diffs = RAIDS.get(raid_name, {}).get("difficulties", {})
        options = [
            discord.SelectOption(
                label=diff,
                description=f"최소 {info['min_level']} | {info['total_slots']}인",
                value=diff,
            )
            for diff, info in diffs.items()
        ]
        sel = Select(placeholder="난이도 선택", options=options)
        sel.callback = self._on_diff_select
        self.add_item(sel)

    async def _on_diff_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 사용할 수 있습니다.", ephemeral=True)
            return
        difficulty = interaction.data["values"][0]
        added = await db.subscribe_raid(self.discord_id, self.selected_raid, difficulty)
        if added:
            await interaction.response.edit_message(
                content=(
                    f"✅ **{self.selected_raid} {difficulty}** 구독 완료!\n"
                    f"새 공대 모집 시 DM으로 알려드립니다."
                ),
                view=None,
            )
        else:
            await interaction.response.edit_message(
                content=f"이미 **{self.selected_raid} {difficulty}**를 구독 중입니다.",
                view=None,
            )


# ── 구독 취소 뷰 ─────────────────────────────────────────

class UnsubscribeView(View):
    def __init__(self, discord_id: str, subs: list[dict]) -> None:
        super().__init__(timeout=60)
        self.discord_id = discord_id
        options = [
            discord.SelectOption(
                label=f"{s['raid_name']} {s['difficulty']}",
                value=f"{s['raid_name']}|{s['difficulty']}",
            )
            for s in subs
        ]
        sel = Select(placeholder="취소할 구독을 선택하세요", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 사용할 수 있습니다.", ephemeral=True)
            return
        raid_name, difficulty = interaction.data["values"][0].split("|", 1)
        removed = await db.unsubscribe_raid(self.discord_id, raid_name, difficulty)
        msg = (
            f"🗑️ **{raid_name} {difficulty}** 구독이 취소되었습니다."
            if removed else "구독 정보를 찾을 수 없습니다."
        )
        await interaction.response.edit_message(content=msg, view=None)


# ── 코그 ─────────────────────────────────────────────────

class Subscription(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="레이드구독", description="새 공대 모집 시 DM 알림을 받을 레이드를 구독합니다.")
    async def subscribe(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        view = RaidSelectView(discord_id)
        await interaction.response.send_message(
            "구독할 레이드를 선택하세요:", view=view, ephemeral=True
        )

    @app_commands.command(name="구독목록", description="현재 구독 중인 레이드 목록을 확인합니다.")
    async def sub_list(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        subs = await db.get_user_subscriptions(discord_id)
        if not subs:
            await interaction.response.send_message(
                "구독 중인 레이드가 없습니다.\n`/레이드구독`으로 구독해보세요!", ephemeral=True
            )
            return
        lines = [f"🔔 **{s['raid_name']} {s['difficulty']}**" for s in subs]
        await interaction.response.send_message(
            "**📋 구독 중인 레이드**\n" + "\n".join(lines), ephemeral=True
        )

    @app_commands.command(name="구독취소", description="레이드 구독을 취소합니다.")
    async def unsubscribe(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        subs = await db.get_user_subscriptions(discord_id)
        if not subs:
            await interaction.response.send_message(
                "구독 중인 레이드가 없습니다.", ephemeral=True
            )
            return
        view = UnsubscribeView(discord_id, subs)
        await interaction.response.send_message(
            "취소할 구독을 선택하세요:", view=view, ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Subscription(bot))
