"""파티 초대 기능 — /파티초대"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import View, Button, Select

import bot.database.manager as db
from bot.data.raids import SUPPORT_CLASSES
from bot.ui.embeds import party_embed


async def _refresh_party_embed(client: discord.Client, party: dict) -> None:
    """공대 embed를 예약 슬롯 포함하여 갱신."""
    try:
        thread = client.get_channel(int(party["channel_id"]))
        if thread is None:
            thread = await client.fetch_channel(int(party["channel_id"]))
        msg      = await thread.fetch_message(int(party["message_id"]))
        slots    = await db.get_party_slots(party["message_id"])
        reserved = await db.get_reserved_slots(party["message_id"])
        from bot.ui.views import PartyView
        closed = party["status"] == "closed"
        await msg.edit(
            embed=party_embed(party, slots, reserved),
            view=PartyView(total_slots=party["total_slots"], closed=closed),
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


# ── 수락 후 역할 선택 뷰 ──────────────────────────────────

class InviteRoleSelectView(View):
    def __init__(self, message_id: str, party: dict, invitee_id: str,
                 char_name: str, char_class: str) -> None:
        super().__init__(timeout=300)
        self.message_id = message_id
        self.party      = party
        self.invitee_id = invitee_id
        self.char_name  = char_name
        self.char_class = char_class

        is_support = char_class in SUPPORT_CLASSES
        dps_btn = Button(label="딜러", emoji="⚔️", style=discord.ButtonStyle.secondary)
        dps_btn.callback = self._make_cb("dps")
        self.add_item(dps_btn)

        sup_btn = Button(
            label="서포터 (추천)" if is_support else "서포터",
            emoji="🛡️",
            style=discord.ButtonStyle.primary,
        )
        sup_btn.callback = self._make_cb("support")
        self.add_item(sup_btn)

    def _make_cb(self, role: str):
        async def cb(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.invitee_id:
                await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
                return
            ok, msg = await db.assign_invite_slot(
                self.message_id, self.invitee_id,
                self.char_name, self.char_class, role,
            )
            role_text = "서포터" if role == "support" else "딜러"
            if ok:
                await interaction.response.edit_message(
                    content=f"✅ **{self.char_name}** ({role_text})로 공대에 참여했습니다!", view=None
                )
                party = await db.get_party(self.message_id)
                if party:
                    await _refresh_party_embed(interaction.client, party)
                    try:
                        leader = await interaction.client.fetch_user(int(party["leader_id"]))
                        await leader.send(
                            f"✅ **{self.char_name}**({self.char_class}/{role_text})님이 "
                            f"**{party['raid_name']} {party['difficulty']}** 공대에 참여했습니다!"
                        )
                    except discord.HTTPException:
                        pass
            else:
                await interaction.response.edit_message(content=f"❌ {msg}", view=None)
            self.stop()
        return cb


# ── 수락 후 캐릭터 선택 뷰 ───────────────────────────────

class InviteCharSelectView(View):
    def __init__(self, message_id: str, party: dict, invitee_id: str,
                 qualifying: list[dict]) -> None:
        super().__init__(timeout=300)
        self.message_id = message_id
        self.party      = party
        self.invitee_id = invitee_id
        self.char_map   = {q["name"]: q for q in qualifying}

        options = [
            discord.SelectOption(
                label=q["name"],
                description=f"{q['class']} | {q['level']:.0f}",
                value=q["name"],
            )
            for q in qualifying
        ]
        sel = Select(placeholder="참여할 캐릭터를 선택하세요", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.invitee_id:
            await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
            return
        char_name = interaction.data["values"][0]
        char_info = self.char_map[char_name]

        if char_info["class"] in SUPPORT_CLASSES:
            view = InviteRoleSelectView(
                self.message_id, self.party, self.invitee_id,
                char_name, char_info["class"],
            )
            await interaction.response.edit_message(
                content=f"**{char_name}** ({char_info['class']}) — 역할을 선택하세요:",
                view=view,
            )
        else:
            ok, msg = await db.assign_invite_slot(
                self.message_id, self.invitee_id,
                char_name, char_info["class"], "dps",
            )
            if ok:
                await interaction.response.edit_message(
                    content=f"✅ **{char_name}**으로 공대에 참여했습니다!", view=None
                )
                party = await db.get_party(self.message_id)
                if party:
                    await _refresh_party_embed(interaction.client, party)
                    try:
                        leader = await interaction.client.fetch_user(int(party["leader_id"]))
                        await leader.send(
                            f"✅ **{char_name}**({char_info['class']})님이 "
                            f"**{party['raid_name']} {party['difficulty']}** 공대에 참여했습니다!"
                        )
                    except discord.HTTPException:
                        pass
            else:
                await interaction.response.edit_message(content=f"❌ {msg}", view=None)
        self.stop()


# ── 초대 DM 수락/거절 뷰 ────────────────────────────────

class InviteResponseView(View):
    def __init__(self, message_id: str, party: dict, invitee_id: str) -> None:
        super().__init__(timeout=3600)
        self.message_id = message_id
        self.party      = party
        self.invitee_id = invitee_id

    async def on_timeout(self) -> None:
        await db.delete_invite(self.message_id, self.invitee_id)

    @discord.ui.button(label="수락", style=discord.ButtonStyle.success, emoji="✅")
    async def accept(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.invitee_id:
            await interaction.response.send_message("본인만 응답할 수 있습니다.", ephemeral=True)
            return

        party = await db.get_party(self.message_id)
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="❌ 이미 종료된 공대입니다.", view=None)
            self.stop()
            return

        discord_id = str(interaction.user.id)
        api_key    = await db.get_user_api_key(discord_id)
        if not api_key:
            await interaction.response.edit_message(
                content="❌ `/api등록`으로 API 키를 먼저 등록해주세요.", view=None
            )
            self.stop()
            return

        registered = await db.get_user_characters(discord_id)
        if not registered:
            await interaction.response.edit_message(
                content="❌ `/원정대`에서 캐릭터를 먼저 등록해주세요.", view=None
            )
            self.stop()
            return

        cached    = await db.get_cached_characters(discord_id, max_age_hours=99999)
        cache_map = {c["character_name"]: c for c in cached}
        min_level = party["min_level"]

        qualifying = [
            {"name": n, "level": cache_map[n]["item_level"], "class": cache_map[n]["character_class"]}
            for n in registered
            if n in cache_map and cache_map[n]["item_level"] and cache_map[n]["item_level"] >= min_level
        ]

        if not qualifying:
            await interaction.response.edit_message(
                content=f"❌ 최소 아이템 레벨({min_level}) 이상의 캐릭터가 없습니다.", view=None
            )
            self.stop()
            return

        if len(qualifying) == 1:
            q = qualifying[0]
            if q["class"] in SUPPORT_CLASSES:
                view = InviteRoleSelectView(
                    self.message_id, party, discord_id, q["name"], q["class"]
                )
                await interaction.response.edit_message(
                    content=f"**{q['name']}** ({q['class']}) — 역할을 선택하세요:",
                    view=view,
                )
            else:
                ok, msg = await db.assign_invite_slot(
                    self.message_id, discord_id, q["name"], q["class"], "dps"
                )
                if ok:
                    await interaction.response.edit_message(
                        content=f"✅ **{q['name']}**으로 공대에 참여했습니다!", view=None
                    )
                    await _refresh_party_embed(interaction.client, party)
                    try:
                        leader = await interaction.client.fetch_user(int(party["leader_id"]))
                        await leader.send(
                            f"✅ **{q['name']}**({q['class']})님이 "
                            f"**{party['raid_name']} {party['difficulty']}** 공대에 참여했습니다!"
                        )
                    except discord.HTTPException:
                        pass
                else:
                    await interaction.response.edit_message(content=f"❌ {msg}", view=None)
        else:
            view = InviteCharSelectView(self.message_id, party, discord_id, qualifying)
            await interaction.response.edit_message(
                content="참여할 캐릭터를 선택하세요:", view=view
            )
        self.stop()

    @discord.ui.button(label="거절", style=discord.ButtonStyle.danger, emoji="❌")
    async def decline(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.invitee_id:
            await interaction.response.send_message("본인만 응답할 수 있습니다.", ephemeral=True)
            return
        await db.delete_invite(self.message_id, self.invitee_id)
        await interaction.response.edit_message(content="❌ 초대를 거절했습니다.", view=None)
        party = await db.get_party(self.message_id)
        if party:
            await _refresh_party_embed(interaction.client, party)
        try:
            leader = await interaction.client.fetch_user(int(self.party["leader_id"]))
            await leader.send(
                f"❌ <@{self.invitee_id}>님이 "
                f"**{self.party['raid_name']} {self.party['difficulty']}** 초대를 거절했습니다."
            )
        except discord.HTTPException:
            pass
        self.stop()


# ── 코그 ────────────────────────────────────────────────

class Invite(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="파티초대",
        description="내 공대의 특정 슬롯을 예약하고 유저를 DM으로 초대합니다.",
    )
    @app_commands.describe(
        user="초대할 디스코드 유저",
        slot="예약할 슬롯 번호 (1 ~ 전체 인원수)",
    )
    @app_commands.rename(user="유저", slot="슬롯")
    async def invite(self, interaction: discord.Interaction, user: discord.Member, slot: int) -> None:
        discord_id = str(interaction.user.id)

        parties = await db.get_user_parties(discord_id)
        leader_parties = [p for p in parties if p["leader_id"] == discord_id]

        if not leader_parties:
            await interaction.response.send_message(
                "현재 파티장으로 있는 공대가 없습니다.", ephemeral=True
            )
            return

        if len(leader_parties) > 1:
            await interaction.response.send_message(
                "파티장인 공대가 여러 개입니다.\n공대 게시물의 ⚙️ 관리에서 초대해주세요.", ephemeral=True
            )
            return

        party = leader_parties[0]

        if not (1 <= slot <= party["total_slots"]):
            await interaction.response.send_message(
                f"슬롯 번호는 1 ~ {party['total_slots']} 사이여야 합니다.", ephemeral=True
            )
            return

        if user.bot or str(user.id) == discord_id:
            await interaction.response.send_message("초대할 수 없는 유저입니다.", ephemeral=True)
            return

        slots = await db.get_party_slots(party["message_id"])
        if any(s["discord_id"] == str(user.id) for s in slots):
            await interaction.response.send_message(
                f"**{user.display_name}**님은 이미 공대에 참여 중입니다.", ephemeral=True
            )
            return

        if any(s["slot_number"] == slot for s in slots):
            await interaction.response.send_message(
                f"**{slot}번** 슬롯은 이미 점유되어 있습니다.", ephemeral=True
            )
            return

        reserved = await db.get_reserved_slots(party["message_id"])
        if slot in reserved:
            await interaction.response.send_message(
                f"**{slot}번** 슬롯은 이미 다른 유저에게 예약되어 있습니다.", ephemeral=True
            )
            return

        added = await db.create_invite(party["message_id"], str(user.id), slot)
        if not added:
            await interaction.response.send_message(
                f"**{user.display_name}**님은 이미 초대된 상태입니다.", ephemeral=True
            )
            return

        await _refresh_party_embed(interaction.client, party)

        raid_title = f"{party['raid_name']} {party['difficulty']} {party['proficiency']}"
        view       = InviteResponseView(party["message_id"], party, str(user.id))
        try:
            await user.send(
                f"⚔️ **{interaction.user.display_name}**님이 "
                f"**{raid_title}** 공대 **{slot}번** 슬롯에 초대했습니다!\n"
                f"일정: **{party['scheduled_time']}** | <#{party['channel_id']}>\n\n"
                f"참여 의사를 알려주세요:",
                view=view,
            )
            await interaction.response.send_message(
                f"✅ **{user.display_name}**님에게 **{slot}번** 슬롯 초대를 발송했습니다.", ephemeral=True
            )
        except discord.Forbidden:
            await db.delete_invite(party["message_id"], str(user.id))
            await _refresh_party_embed(interaction.client, party)
            await interaction.response.send_message(
                f"❌ **{user.display_name}**님의 DM이 비활성화되어 있습니다.", ephemeral=True
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Invite(bot))
