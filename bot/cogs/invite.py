"""파티 초대 기능 — /파티초대"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button

import bot.database.manager as db


class InviteResponseView(View):
    """초대 DM에 붙는 수락/거절 버튼."""

    def __init__(self, message_id: str, party: dict, invitee_id: str) -> None:
        super().__init__(timeout=3600)  # 1시간 유효
        self.message_id = message_id
        self.party      = party
        self.invitee_id = invitee_id

    @discord.ui.button(label="수락", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.invitee_id:
            await interaction.response.send_message("본인만 응답할 수 있습니다.", ephemeral=True)
            return

        await db.delete_invite(self.message_id, self.invitee_id)
        link = f"<#{self.party['channel_id']}>"
        await interaction.response.edit_message(
            content=(
                f"✅ **{self.party['raid_name']} {self.party['difficulty']}** 공대 초대를 수락했습니다!\n"
                f"공대에 직접 참여해주세요: {link}"
            ),
            view=None,
        )
        # 파티장에게 수락 알림
        raid_title = f"{self.party['raid_name']} {self.party['difficulty']}"
        try:
            leader = await interaction.client.fetch_user(int(self.party["leader_id"]))
            await leader.send(
                f"✅ <@{self.invitee_id}>님이 **{raid_title}** 공대 초대를 수락했습니다!"
            )
        except discord.HTTPException:
            pass
        self.stop()

    @discord.ui.button(label="거절", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.invitee_id:
            await interaction.response.send_message("본인만 응답할 수 있습니다.", ephemeral=True)
            return

        await db.delete_invite(self.message_id, self.invitee_id)
        await interaction.response.edit_message(
            content="❌ 초대를 거절했습니다.", view=None
        )
        # 파티장에게 거절 알림
        raid_title = f"{self.party['raid_name']} {self.party['difficulty']}"
        try:
            leader = await interaction.client.fetch_user(int(self.party["leader_id"]))
            await leader.send(
                f"❌ <@{self.invitee_id}>님이 **{raid_title}** 공대 초대를 거절했습니다."
            )
        except discord.HTTPException:
            pass
        self.stop()


class Invite(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="파티초대",
        description="현재 내가 파티장인 공대에 특정 유저를 DM으로 초대합니다.",
    )
    @app_commands.describe(유저="초대할 디스코드 유저")
    async def invite(self, interaction: discord.Interaction, 유저: discord.Member) -> None:
        discord_id = str(interaction.user.id)

        # 파티장인 공대 목록 조회
        parties = await db.get_user_parties(discord_id)
        leader_parties = [p for p in parties if p["leader_id"] == discord_id]

        if not leader_parties:
            await interaction.response.send_message(
                "현재 파티장으로 있는 공대가 없습니다.", ephemeral=True
            )
            return

        if 유저.bot:
            await interaction.response.send_message("봇은 초대할 수 없습니다.", ephemeral=True)
            return

        if str(유저.id) == discord_id:
            await interaction.response.send_message("자신을 초대할 수 없습니다.", ephemeral=True)
            return

        # 공대가 1개면 바로, 여러 개면 선택
        party = leader_parties[0]
        if len(leader_parties) > 1:
            await interaction.response.send_message(
                "파티장인 공대가 여러 개입니다. 현재 채널의 공대에서 초대해주세요.", ephemeral=True
            )
            return

        # 이미 참여 중인지 확인
        slots = await db.get_party_slots(party["message_id"])
        if any(s["discord_id"] == str(유저.id) for s in slots):
            await interaction.response.send_message(
                f"**{유저.display_name}**님은 이미 공대에 참여 중입니다.", ephemeral=True
            )
            return

        # 초대 DM 발송
        added = await db.create_invite(party["message_id"], str(유저.id))
        if not added:
            await interaction.response.send_message(
                f"**{유저.display_name}**님은 이미 초대된 상태입니다.", ephemeral=True
            )
            return

        raid_title = f"{party['raid_name']} {party['difficulty']} {party['proficiency']}"
        link       = f"<#{party['channel_id']}>"
        view       = InviteResponseView(party["message_id"], party, str(유저.id))

        try:
            await 유저.send(
                f"⚔️ **{interaction.user.display_name}**님이 **{raid_title}** 공대에 초대했습니다!\n"
                f"일정: **{party['scheduled_time']}** | {link}\n\n"
                f"참여 의사를 알려주세요:",
                view=view,
            )
            await interaction.response.send_message(
                f"✅ **{유저.display_name}**님에게 초대 DM을 발송했습니다.", ephemeral=True
            )
        except discord.Forbidden:
            await db.delete_invite(party["message_id"], str(유저.id))
            await interaction.response.send_message(
                f"❌ **{유저.display_name}**님의 DM이 비활성화되어 있습니다.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Invite(bot))
