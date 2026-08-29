"""디스코드 슬래시 커맨드로 원정대 랭킹 확인.
db.get_expedition_ranking은 이미 구현돼 있고 웹 /ranking만 쓰고 있었다 —
웹을 안 쓰는 길드원도 디스코드에서 바로 볼 수 있게 슬래시 커맨드로 노출한다."""
import discord
from discord import app_commands
from discord.ext import commands

import bot.database.manager as db

_METRIC_LABELS = {
    "combat_power": "전투력",
    "item_level": "아이템 레벨",
    "weekly_clears": "주간 클리어 수",
}
_ROLE_LABELS = {"dps": "딜러", "support": "서포터"}


class Ranking(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="랭킹", description="원정대 랭킹을 확인합니다.")
    @app_commands.describe(role="딜러/서포터 필터 (전투력 기준에서만 적용)")
    @app_commands.rename(metric="기준", role="역할")
    @app_commands.choices(
        metric=[app_commands.Choice(name=label, value=key) for key, label in _METRIC_LABELS.items()],
        role=[app_commands.Choice(name=label, value=key) for key, label in _ROLE_LABELS.items()],
    )
    async def ranking(
        self, interaction: discord.Interaction,
        metric: str = "combat_power", role: str | None = None,
    ) -> None:
        await interaction.response.defer(thinking=True, ephemeral=True)
        entries = await db.get_expedition_ranking(metric, limit=10, role=role)
        if not entries:
            await interaction.followup.send("랭킹 데이터가 없습니다.", ephemeral=True)
            return

        title = f"🏆 원정대 랭킹 — {_METRIC_LABELS[metric]}"
        if role and metric == "combat_power":
            title += f" ({_ROLE_LABELS[role]})"

        lines = []
        for i, e in enumerate(entries, start=1):
            value = e["value"]
            value_str = f"{int(value)}회" if metric == "weekly_clears" else f"{value:,.2f}"
            lines.append(f"**{i}.** {e['character_name']} ({e['character_class']}) — {value_str}")

        embed = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold())
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Ranking(bot))
