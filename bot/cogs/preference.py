"""유저 알림 설정 — /알림시간설정"""
import discord
from discord import app_commands
from discord.ext import commands

import bot.database.manager as db


class Preference(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="알림시간설정",
        description="공대 시작 몇 시간 전에 사전 알림을 받을지 설정합니다.",
    )
    @app_commands.describe(hours="알림을 받을 시간 (예: 1 = 1시간 전, 0.5 = 30분 전)")
    @app_commands.rename(hours="시간")
    @app_commands.choices(hours=[
        app_commands.Choice(name="30분 전",  value=0.5),
        app_commands.Choice(name="1시간 전", value=1.0),
        app_commands.Choice(name="2시간 전", value=2.0),
        app_commands.Choice(name="3시간 전", value=3.0),
        app_commands.Choice(name="알림 끄기", value=0.0),
    ])
    async def set_pre_notify(self, interaction: discord.Interaction, hours: float) -> None:
        discord_id = str(interaction.user.id)
        await db.set_pre_notify_hours(discord_id, hours)

        if hours == 0.0:
            msg = "🔕 사전 알림을 껐습니다. 공대 시작 시각에만 알림이 옵니다."
        else:
            h = int(hours)
            m = int((hours - h) * 60)
            time_str = f"{h}시간" if m == 0 else f"{h}시간 {m}분" if h > 0 else f"{m}분"
            msg = f"🔔 공대 시작 **{time_str} 전**에 사전 알림을 드립니다."

        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(
        name="알림설정확인",
        description="현재 사전 알림 설정을 확인합니다.",
    )
    async def check_pre_notify(self, interaction: discord.Interaction) -> None:
        hours = await db.get_pre_notify_hours(str(interaction.user.id))
        if hours == 0.0:
            msg = "🔕 현재 사전 알림이 꺼져 있습니다."
        else:
            h = int(hours)
            m = int((hours - h) * 60)
            time_str = f"{h}시간" if m == 0 else f"{h}시간 {m}분" if h > 0 else f"{m}분"
            msg = f"🔔 현재 공대 시작 **{time_str} 전**에 알림을 받도록 설정되어 있습니다."
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Preference(bot))
