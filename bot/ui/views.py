from __future__ import annotations

import discord
from discord.ui import View, Button, Select, Modal, TextInput
from datetime import datetime, timezone, timedelta

from bot.data.raids import RAIDS, get_applicable_raids, get_difficulty_info, SUPPORT_CLASSES, PROFICIENCY
import bot.database.manager as db
import bot.api.lostark as loa

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────────────
# 파티 초대 — 응답 뷰 (ManageView에서 사용)
# ─────────────────────────────────────────────────────

async def _refresh_party_embed_with_reserved(client: discord.Client, party: dict) -> None:
    from bot.ui.embeds import party_embed as _party_embed
    try:
        thread = client.get_channel(int(party["channel_id"]))
        if thread is None:
            thread = await client.fetch_channel(int(party["channel_id"]))
        msg      = await thread.fetch_message(int(party["message_id"]))
        slots    = await db.get_party_slots(party["message_id"])
        reserved = await db.get_reserved_slots(party["message_id"])
        closed   = party["status"] == "closed"
        await msg.edit(
            embed=_party_embed(party, slots, reserved),
            view=PartyView(total_slots=party["total_slots"], closed=closed),
        )
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


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
            emoji="🛡️", style=discord.ButtonStyle.primary,
        )
        sup_btn.callback = self._make_cb("support")
        self.add_item(sup_btn)

    def _make_cb(self, role: str):
        async def cb(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.invitee_id:
                await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
                return
            ok, msg = await db.assign_invite_slot(
                self.message_id, self.invitee_id, self.char_name, self.char_class, role,
            )
            role_text = "서포터" if role == "support" else "딜러"
            if ok:
                await interaction.response.edit_message(
                    content=f"✅ **{self.char_name}** ({role_text})로 공대에 참여했습니다!", view=None
                )
                party = await db.get_party(self.message_id)
                if party:
                    await _refresh_party_embed_with_reserved(interaction.client, party)
                    try:
                        leader = await interaction.client.fetch_user(int(party["leader_id"]))
                        await leader.send(
                            f"✅ **{self.char_name}**({self.char_class}/{role_text})님이 "
                            f"**{party['raid_name']} {party['difficulty']}** 공대에 참여했습니다!\n{_party_url(party)}"
                        )
                    except discord.HTTPException:
                        pass
            else:
                await interaction.response.edit_message(content=f"❌ {msg}", view=None)
            self.stop()
        return cb


class InviteCharSelectView(View):
    def __init__(self, message_id: str, party: dict, invitee_id: str,
                 qualifying: list[dict]) -> None:
        super().__init__(timeout=300)
        self.message_id = message_id
        self.party      = party
        self.invitee_id = invitee_id
        self.char_map   = {q["name"]: q for q in qualifying}

        options = [
            discord.SelectOption(label=q["name"], description=f"{q['class']} | {q['level']:.0f}", value=q["name"])
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
            view = InviteRoleSelectView(self.message_id, self.party, self.invitee_id, char_name, char_info["class"])
            await interaction.response.edit_message(
                content=f"**{char_name}** ({char_info['class']}) — 역할을 선택하세요:", view=view
            )
        else:
            ok, msg = await db.assign_invite_slot(self.message_id, self.invitee_id, char_name, char_info["class"], "dps")
            if ok:
                await interaction.response.edit_message(content=f"✅ **{char_name}**으로 공대에 참여했습니다!", view=None)
                party = await db.get_party(self.message_id)
                if party:
                    await _refresh_party_embed_with_reserved(interaction.client, party)
                    try:
                        leader = await interaction.client.fetch_user(int(party["leader_id"]))
                        await leader.send(
                            f"✅ **{char_name}**({char_info['class']})님이 "
                            f"**{party['raid_name']} {party['difficulty']}** 공대에 참여했습니다!\n{_party_url(party)}"
                        )
                    except discord.HTTPException:
                        pass
            else:
                await interaction.response.edit_message(content=f"❌ {msg}", view=None)
        self.stop()


class InviteResponseView(View):
    def __init__(self, message_id: str, party: dict, invitee_id: str,
                 client: discord.Client | None = None) -> None:
        super().__init__(timeout=3600)
        self.message_id = message_id
        self.party      = party
        self.invitee_id = invitee_id
        self._client    = client

    async def on_timeout(self) -> None:
        await db.delete_invite(self.message_id, self.invitee_id)
        # 초대 만료 시 파티 embed의 예약 슬롯 표시 제거
        if self._client:
            party = await db.get_party(self.message_id)
            if party:
                await _refresh_party_embed_with_reserved(self._client, party)

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
            await interaction.response.edit_message(content="❌ `/api등록`으로 API 키를 먼저 등록해주세요.", view=None)
            self.stop()
            return
        registered = await db.get_user_characters(discord_id)
        if not registered:
            await interaction.response.edit_message(content="❌ `/원정대`에서 캐릭터를 먼저 등록해주세요.", view=None)
            self.stop()
            return
        cached    = await db.get_cached_characters(discord_id, max_age_hours=99999)
        cache_map = {c["character_name"]: c for c in cached}
        qualifying = [
            {"name": n, "level": cache_map[n]["item_level"], "class": cache_map[n]["character_class"]}
            for n in registered
            if n in cache_map and cache_map[n]["item_level"] and cache_map[n]["item_level"] >= party["min_level"]
        ]
        if not qualifying:
            # 캐시가 전혀 없는 캐릭터가 있으면 원인을 구체적으로 안내
            no_cache = [n for n in registered if n not in cache_map or not cache_map[n].get("item_level")]
            if no_cache:
                await interaction.response.edit_message(
                    content=(
                        f"❌ 캐릭터 정보가 아직 로드되지 않았습니다.\n"
                        f"`/원정대` 명령어를 한 번 실행한 후 다시 시도해주세요."
                    ),
                    view=None,
                )
            else:
                await interaction.response.edit_message(
                    content=f"❌ 최소 아이템 레벨 **{party['min_level']}** 이상의 캐릭터가 없습니다.",
                    view=None,
                )
            self.stop()
            return
        if len(qualifying) == 1:
            q = qualifying[0]
            if q["class"] in SUPPORT_CLASSES:
                view = InviteRoleSelectView(self.message_id, party, discord_id, q["name"], q["class"])
                await interaction.response.edit_message(content=f"**{q['name']}** ({q['class']}) — 역할을 선택하세요:", view=view)
            else:
                ok, msg = await db.assign_invite_slot(self.message_id, discord_id, q["name"], q["class"], "dps")
                if ok:
                    await interaction.response.edit_message(content=f"✅ **{q['name']}**으로 공대에 참여했습니다!", view=None)
                    await _refresh_party_embed_with_reserved(interaction.client, party)
                    try:
                        leader = await interaction.client.fetch_user(int(party["leader_id"]))
                        await leader.send(f"✅ **{q['name']}**({q['class']})님이 **{party['raid_name']} {party['difficulty']}** 공대에 참여했습니다!\n{_party_url(party)}")
                    except discord.HTTPException:
                        pass
                else:
                    await interaction.response.edit_message(content=f"❌ {msg}", view=None)
        else:
            view = InviteCharSelectView(self.message_id, party, discord_id, qualifying)
            await interaction.response.edit_message(content="참여할 캐릭터를 선택하세요:", view=view)
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
            await _refresh_party_embed_with_reserved(interaction.client, party)
        try:
            leader = await interaction.client.fetch_user(int(self.party["leader_id"]))
            await leader.send(
                f"❌ <@{self.invitee_id}>님이 **{self.party['raid_name']} {self.party['difficulty']}** 초대를 거절했습니다.\n{_party_url(self.party)}"
            )
        except discord.HTTPException:
            pass
        self.stop()


class InviteSlotSelectView(View):
    """유저 선택 후 슬롯 선택."""

    def __init__(self, party: dict, original_message: discord.Message,
                 total_slots: int, target_id: str, target_name: str,
                 occupied: set[int], reserved: set[int]) -> None:
        super().__init__(timeout=60)
        self.party           = party
        self.original_message = original_message
        self.total_slots_count = total_slots
        self.target_id       = target_id
        self.target_name     = target_name

        available = [
            sn for sn in range(1, total_slots + 1)
            if sn not in occupied and sn not in reserved
        ]
        options = [
            discord.SelectOption(label=f"{sn}번 슬롯", value=str(sn))
            for sn in available
        ]
        if not options:
            options = [discord.SelectOption(label="빈 슬롯 없음", value="none")]

        sel = Select(
            placeholder="예약할 슬롯을 선택하세요",
            options=options,
            disabled=not available,
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        val = interaction.data["values"][0]
        if val == "none":
            await interaction.response.edit_message(content="❌ 빈 슬롯이 없습니다.", view=None)
            return

        slot = int(val)
        added = await db.create_invite(self.party["message_id"], self.target_id, slot)
        if not added:
            await interaction.response.edit_message(content="❌ 이미 초대된 유저입니다.", view=None)
            return

        party = await db.get_party(self.party["message_id"])
        if party:
            await _refresh_party_embed_with_reserved(interaction.client, party)

        raid_title = f"{self.party['raid_name']} {self.party['difficulty']} {self.party['proficiency']}"
        view = InviteResponseView(self.party["message_id"], self.party, self.target_id,
                                  client=interaction.client)
        try:
            target_user = await interaction.client.fetch_user(int(self.target_id))
            await target_user.send(
                f"⚔️ **{interaction.user.display_name}**님이 "
                f"**{raid_title}** 공대 **{slot}번** 슬롯에 초대했습니다!\n"
                f"일정: **{self.party['scheduled_time']}** | {_party_url(self.party)}\n\n"
                f"참여 의사를 알려주세요:",
                view=view,
            )
            await interaction.response.edit_message(
                content=f"✅ **{self.target_name}**님에게 **{slot}번** 슬롯 초대를 발송했습니다.",
                view=None,
            )
        except discord.Forbidden:
            await db.delete_invite(self.party["message_id"], self.target_id)
            if party:
                await _refresh_party_embed_with_reserved(interaction.client, party)
            await interaction.response.edit_message(content="❌ 해당 유저의 DM이 비활성화되어 있습니다.", view=None)
        self.stop()


class InviteUserSelectView(View):
    """API 등록 유저 목록에서 초대할 유저 선택."""

    def __init__(self, party: dict, original_message: discord.Message,
                 total_slots: int, users: list[dict],
                 occupied: set[int], reserved: set[int]) -> None:
        super().__init__(timeout=60)
        self.party            = party
        self.original_message = original_message
        self.total_slots_count = total_slots
        self.occupied         = occupied
        self.reserved         = reserved
        self.user_map         = {u["discord_id"]: u.get("representative") or u["discord_id"] for u in users}

        options = [
            discord.SelectOption(
                label=u.get("representative") or u["discord_id"],
                description=u["discord_id"],
                value=u["discord_id"],
            )
            for u in users[:25]
        ]
        sel = Select(placeholder="초대할 유저를 선택하세요", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        target_id   = interaction.data["values"][0]
        target_name = self.user_map.get(target_id, target_id)
        view = InviteSlotSelectView(
            self.party, self.original_message, self.total_slots_count,
            target_id, target_name, self.occupied, self.reserved,
        )
        await interaction.response.edit_message(
            content=f"**{target_name}**님을 초대할 슬롯을 선택하세요:",
            view=view,
        )
        self.stop()


# ─────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────

async def _send_dm(client: discord.Client, discord_id: str, content: str) -> None:
    try:
        user = await client.fetch_user(int(discord_id))
        await user.send(content)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        pass


def _party_url(party: dict) -> str:
    """DM용 공대 스레드 직접 링크 — 채널 멘션(<#id>)은 포럼 스레드에서 알 수 없음으로 표시."""
    return f"https://discord.com/channels/{party['guild_id']}/{party['channel_id']}"


async def _notify_waitlist(client: discord.Client, party: dict) -> None:
    waitlist = await db.get_waitlist(party["message_id"])
    if not waitlist:
        return
    raid_title = f"{party['raid_name']} {party['difficulty']}"
    link = _party_url(party)
    for discord_id in waitlist:
        await _send_dm(
            client, discord_id,
            f"🔔 **{raid_title}** 공대에 빈 자리가 생겼습니다!\n{link}",
        )
    await db.clear_waitlist(party["message_id"])


def _parse_schedule(date_str: str, time_str: str) -> datetime | None:
    """날짜/시간 문자열을 유연하게 파싱. 실패 시 None 반환.

    날짜: YYYYMMDD | MMDD | MDD | YYYY/MM/DD | YYYY-MM-DD
    시간: HHMM | HH | HH:MM
    """
    d = date_str.strip().replace("/", "").replace("-", "").replace(".", "").replace(" ", "")
    t = time_str.strip().replace(":", "").replace(" ", "")
    now = datetime.now(KST)
    try:
        if len(d) == 8:
            year, month, day = int(d[:4]), int(d[4:6]), int(d[6:8])
        elif len(d) == 4:
            year, month, day = now.year, int(d[:2]), int(d[2:4])
        elif len(d) == 3:
            year, month, day = now.year, int(d[:1]), int(d[1:3])
        else:
            return None
        if len(t) == 4:
            hour, minute = int(t[:2]), int(t[2:4])
        elif len(t) in (1, 2):
            hour, minute = int(t), 0
        else:
            return None
        dt = datetime(year, month, day, hour, minute, tzinfo=KST)
        # 연도 미지정(3~4자리) 입력에서 이미 지난 날짜면 내년으로 자동 전진
        if len(d) in (3, 4) and dt < now:
            dt = dt.replace(year=now.year + 1)
        return dt
    except (ValueError, IndexError):
        return None


def _is_extreme_expired(info: dict) -> bool:
    """익스트림 레이드의 운영 기간이 지났으면 True."""
    if not info.get("is_extreme"):
        return False
    until = info.get("available_until")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) < datetime.now(KST)
    except ValueError:
        return False


def _format_schedule(dt: datetime) -> str:
    """datetime → 12시간제 한국어 표시 문자열."""
    hour = dt.hour
    ampm = "오전" if hour < 12 else "오후"
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12
    if dt.minute == 0:
        return f"{dt.year}/{dt.month:02d}/{dt.day:02d} {ampm} {display_hour}시 정각"
    return f"{dt.year}/{dt.month:02d}/{dt.day:02d} {ampm} {display_hour}시 {dt.minute:02d}분"


async def _refresh_expedition(
    message: discord.Message,
    discord_id: str,
    user: discord.User | discord.Member,
) -> None:
    """캐시 기반으로 원정대 embed를 즉시 갱신. ServerName은 '?'로 표시."""
    char_names = await db.get_user_characters(discord_id)
    cache_map  = {
        c["character_name"]: c
        for c in await db.get_cached_characters(discord_id, max_age_hours=99999)
    }
    characters = [
        {
            "CharacterName":      name,
            "CharacterClassName": (cache_map.get(name) or {}).get("character_class") or "?",
            "ItemMaxLevel":       str((cache_map.get(name) or {}).get("item_level") or 0),
            "ServerName":         "?",
        }
        for name in char_names
    ]
    from bot.ui.embeds import expedition_embed, no_characters_embed
    embed = expedition_embed(user, characters) if characters else no_characters_embed(user)
    await message.edit(embed=embed)


# ─────────────────────────────────────────────────────
# 레이드 체크리스트
# ─────────────────────────────────────────────────────

class RaidChecklistView(View):
    def __init__(self, discord_id: str, char: str, item_level: float, completions: set[str]) -> None:
        super().__init__(timeout=300)
        self.discord_id = discord_id
        self.char = char
        self.item_level = item_level
        self.completions = completions
        self._build()

    def _build(self) -> None:
        self.clear_items()
        applicable = get_applicable_raids(self.item_level)

        # 카테고리별 그룹 → 각 카테고리를 하나의 버튼 행으로
        by_cat: dict[str, list] = {}
        for raid_name, diff_name, _ in applicable:
            cat = RAIDS[raid_name]["category"]
            by_cat.setdefault(cat, []).append((raid_name, diff_name))

        for row_idx, (_, raids) in enumerate(by_cat.items()):
            if row_idx > 4:
                break
            for raid_name, diff_name in raids:
                key  = f"{raid_name}_{diff_name}"
                done = key in self.completions
                short = RAIDS[raid_name].get("short_name", raid_name)
                btn = Button(
                    label=f"{short} {diff_name}",
                    emoji="✅" if done else "⬜",
                    style=discord.ButtonStyle.success if done else discord.ButtonStyle.secondary,
                    row=row_idx,
                )
                btn.callback = self._make_toggle(raid_name, diff_name, key)
                self.add_item(btn)

    def _make_toggle(self, raid_name: str, diff_name: str, key: str):
        async def cb(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.discord_id:
                await interaction.response.send_message("본인의 체크리스트만 수정할 수 있습니다.", ephemeral=True)
                return
            now_done = await db.toggle_completion(self.discord_id, self.char, raid_name, diff_name)
            if now_done:
                self.completions.add(key)
            else:
                self.completions.discard(key)
            self._build()
            from bot.ui.embeds import raid_checklist_embed
            await interaction.response.edit_message(
                embed=raid_checklist_embed(self.char, self.item_level, self.completions),
                view=self,
            )
        return cb


# ─────────────────────────────────────────────────────
# 원정대 관리
# ─────────────────────────────────────────────────────

class ExpeditionView(View):
    def __init__(self, discord_id: str) -> None:
        super().__init__(timeout=300)
        self.discord_id = discord_id

    @discord.ui.button(label="캐릭터 추가", emoji="➕", style=discord.ButtonStyle.primary)
    async def add_btn(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 수정할 수 있습니다.", ephemeral=True)
            return
        key = await db.get_user_api_key(self.discord_id)
        if not key:
            await interaction.response.send_message(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
            )
            return
        await interaction.response.send_modal(AddCharacterModal(self.discord_id, key, interaction.message))

    @discord.ui.button(label="캐릭터 삭제", emoji="➖", style=discord.ButtonStyle.danger)
    async def remove_btn(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 수정할 수 있습니다.", ephemeral=True)
            return
        chars = await db.get_user_characters(self.discord_id)
        if not chars:
            await interaction.response.send_message("등록된 캐릭터가 없습니다.", ephemeral=True)
            return
        view = RemoveCharacterView(self.discord_id, chars, interaction.message)
        await interaction.response.send_message("삭제할 캐릭터를 선택해주세요.", view=view, ephemeral=True)

    @discord.ui.button(label="동기화", emoji="🔄", style=discord.ButtonStyle.secondary)
    async def sync_btn(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 동기화할 수 있습니다.", ephemeral=True)
            return
        api_key = await db.get_user_api_key(self.discord_id)
        if not api_key:
            await interaction.response.send_message(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
            )
            return

        await interaction.response.defer(thinking=True, ephemeral=True)

        char_names = await db.get_user_characters(self.discord_id)
        characters: list[dict] = []
        updated = 0

        # 원정대 목록 1회만 호출 (캐릭터 수만큼 반복 호출 → 단건 호출)
        try:
            siblings = await loa.get_siblings(api_key, char_names[0]) if char_names else None
            siblings_map = {c["CharacterName"]: c for c in siblings} if siblings else {}
        except Exception:
            siblings_map = {}

        for name in char_names:
            char = siblings_map.get(name)
            if char:
                lv  = loa.parse_item_level(char)
                cls = char.get("CharacterClassName", "?")
                if lv > 0:
                    await db.update_character_cache(self.discord_id, name, lv, cls)
                    updated += 1
                characters.append(char)
            else:
                characters.append({
                    "CharacterName": name, "CharacterClassName": "조회 실패",
                    "ItemMaxLevel": "0", "ServerName": "?",
                })

        from bot.ui.embeds import expedition_embed
        try:
            await interaction.message.edit(
                embed=expedition_embed(interaction.user, characters), view=self
            )
        except Exception:
            pass

        await interaction.followup.send(
            f"🔄 **{updated}/{len(char_names)}**개 캐릭터 동기화 완료!", ephemeral=True
        )


class AddCharacterModal(Modal, title="캐릭터 등록"):
    char_name = TextInput(label="캐릭터 이름", placeholder="정확한 캐릭터 이름", min_length=2, max_length=12)

    def __init__(self, discord_id: str, api_key: str, expedition_message: discord.Message | None = None) -> None:
        super().__init__()
        self.discord_id = discord_id
        self.api_key = api_key
        self.expedition_message = expedition_message

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name = self.char_name.value.strip()
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            siblings = await loa.get_siblings(self.api_key, name)
        except RuntimeError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return
        if siblings is None:
            await interaction.followup.send(
                f"**{name}** 캐릭터를 찾을 수 없습니다.\n이름과 API 키를 확인해주세요.", ephemeral=True
            )
            return

        # 본인 원정대 캐릭터인지 확인
        sibling_names = {c["CharacterName"] for c in siblings}
        registered = await db.get_user_characters(self.discord_id)
        if registered and not any(r in sibling_names for r in registered):
            await interaction.followup.send(
                "본인 원정대의 캐릭터만 등록할 수 있습니다.", ephemeral=True
            )
            return

        char = next((c for c in siblings if c["CharacterName"] == name), None)
        if char is None:
            await interaction.followup.send(
                f"**{name}** 캐릭터를 찾을 수 없습니다.\n이름과 API 키를 확인해주세요.", ephemeral=True
            )
            return

        added = await db.add_character(self.discord_id, name)
        if not added:
            await interaction.followup.send(f"**{name}**은(는) 이미 등록된 캐릭터입니다.", ephemeral=True)
            return
        level      = loa.parse_item_level(char)
        char_class = char.get("CharacterClassName", "?")
        if level > 0:
            await db.update_character_cache(self.discord_id, name, level, char_class)
        level_str = f"{level:,.2f}" if level > 0 else "?"
        await interaction.followup.send(
            f"✅ **{name}** ({char_class} / {level_str}) 등록 완료!",
            ephemeral=True,
        )
        if self.expedition_message:
            await _refresh_expedition(self.expedition_message, self.discord_id, interaction.user)


class RemoveCharacterView(View):
    def __init__(self, discord_id: str, characters: list[str], expedition_message: discord.Message | None = None) -> None:
        super().__init__(timeout=60)
        self.discord_id = discord_id
        self.expedition_message = expedition_message
        sel = Select(
            placeholder="삭제할 캐릭터 선택",
            options=[discord.SelectOption(label=c, value=c) for c in characters],
        )
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        name    = interaction.data["values"][0]
        removed = await db.remove_character(self.discord_id, name)
        msg     = f"🗑️ **{name}** 삭제 완료." if removed else "캐릭터를 찾을 수 없습니다."
        await interaction.response.edit_message(content=msg, view=None)
        if removed and self.expedition_message:
            await _refresh_expedition(self.expedition_message, self.discord_id, interaction.user)


# ─────────────────────────────────────────────────────
# 공대 모집 — 통합 생성 뷰
# ─────────────────────────────────────────────────────

class RecruitView(View):
    """레이드·난이도·숙련도·일정을 한 화면에서 설정하는 공대 모집 뷰."""

    def __init__(self, leader_id: str, forum_channel_id: str) -> None:
        super().__init__(timeout=300)
        self.leader_id       = leader_id
        self.forum_channel_id = forum_channel_id
        self.selected_raid:       str | None = None
        self.selected_difficulty: str | None = None
        self.selected_proficiency:str | None = None
        self.scheduled_time:      str | None = None
        self.scheduled_datetime:  str | None = None
        self.memo:                str | None = None
        self._uid = f"{id(self):x}"  # 인스턴스마다 고유 — custom_id 일관성 유지
        self._original_interaction: discord.Interaction | None = None
        self._creating = False  # 공대 생성 중복 실행 방지
        self._build()

    # ── 뷰 재구성 ──────────────────────────────────

    def _build(self) -> None:
        self.clear_items()

        # 레이드 Select (비활성·기간만료 레이드 제외)
        raid_options = []
        for name, info in RAIDS.items():
            if not info.get("is_active", True):
                continue
            if _is_extreme_expired(info):
                continue
            min_lv = min(d["min_level"] for d in info["difficulties"].values())
            desc = f"{info['category']} | 최소 {min_lv}"
            if info.get("is_extreme") and info.get("available_until"):
                try:
                    until_dt = datetime.fromisoformat(info["available_until"])
                    desc += f" | ~{until_dt.month}/{until_dt.day} 까지"
                except ValueError:
                    pass
            raid_options.append(discord.SelectOption(
                label=name, description=desc, emoji=info["icon"],
                value=name, default=(name == self.selected_raid),
            ))
        u = self._uid
        raid_sel = Select(
            custom_id=f"rc:{u}:r",
            placeholder="레이드 선택", options=raid_options, row=0,
        )
        raid_sel.callback = self._on_raid
        self.add_item(raid_sel)

        # 난이도 Select — 레이드 선택 전엔 비활성
        if self.selected_raid and self.selected_raid in RAIDS:
            diff_options = [
                discord.SelectOption(
                    label=diff,
                    description=f"최소 {info['min_level']} | {info['total_slots']}인",
                    value=diff,
                    default=(diff == self.selected_difficulty),
                )
                for diff, info in RAIDS[self.selected_raid]["difficulties"].items()
            ]
            diff_sel = Select(
                custom_id=f"rc:{u}:d",
                placeholder="난이도 선택", options=diff_options, row=1,
            )
        else:
            diff_sel = Select(
                custom_id=f"rc:{u}:d",
                placeholder="레이드를 먼저 선택하세요",
                options=[discord.SelectOption(label="-", value="-")],
                disabled=True, row=1,
            )
        diff_sel.callback = self._on_difficulty
        self.add_item(diff_sel)

        # 숙련도 Select
        prof_options = [
            discord.SelectOption(
                label=p, description=desc, value=p,
                default=(p == self.selected_proficiency),
            )
            for p, desc in PROFICIENCY.items()
        ]
        prof_sel = Select(
            custom_id=f"rc:{u}:p",
            placeholder="숙련도 선택", options=prof_options, row=2,
        )
        prof_sel.callback = self._on_proficiency
        self.add_item(prof_sel)

        # 일정·메모 버튼
        schedule_label = f"📅 {self.scheduled_time}" if self.scheduled_time else "📅 날짜 · 시간 · 메모 설정"
        schedule_btn = Button(
            custom_id=f"rc:{u}:s",
            label=schedule_label,
            style=discord.ButtonStyle.secondary if not self.scheduled_time else discord.ButtonStyle.primary,
            row=3,
        )
        schedule_btn.callback = self._on_schedule
        self.add_item(schedule_btn)

        # 공대 생성 버튼 — 모두 선택 시 활성화
        all_set = all([self.selected_raid, self.selected_difficulty,
                       self.selected_proficiency, self.scheduled_time])
        create_btn = Button(
            custom_id=f"rc:{u}:c",
            label="✅ 공대 생성",
            style=discord.ButtonStyle.success,
            disabled=not all_set,
            row=4,
        )
        create_btn.callback = self._on_create
        self.add_item(create_btn)

    async def on_timeout(self) -> None:
        if self._original_interaction:
            try:
                await self._original_interaction.edit_original_response(
                    content="⏱️ 공대 모집 설정이 만료되었습니다. `/공대모집`으로 다시 시작해주세요.",
                    view=None,
                )
            except discord.HTTPException:
                pass

    def _status_text(self) -> str:
        def v(val: str | None, label: str) -> str:
            return f"{label}: **{val}**" if val else f"{label}: `미선택`"

        lines = [
            "**⚔️ 공대 모집 설정**\n",
            v(self.selected_raid,        "레이드"),
            v(self.selected_difficulty,  "난이도"),
            v(self.selected_proficiency, "숙련도"),
            f"일정: **{self.scheduled_time}**" if self.scheduled_time else "일정: `미설정`",
        ]
        if self.memo:
            lines.append(f"메모: {self.memo}")
        if not all([self.selected_raid, self.selected_difficulty,
                    self.selected_proficiency, self.scheduled_time]):
            lines.append("\n모든 항목을 설정하면 **공대 생성** 버튼이 활성화됩니다.")
        return "\n".join(lines)

    # ── 콜백 ──────────────────────────────────────

    async def _on_raid(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        self.selected_raid = interaction.data["values"][0]
        self.selected_difficulty = None
        self._build()
        await interaction.response.edit_message(content=self._status_text(), view=self)

    async def _on_difficulty(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        self.selected_difficulty = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(content=self._status_text(), view=self)

    async def _on_proficiency(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        self.selected_proficiency = interaction.data["values"][0]
        self._build()
        await interaction.response.edit_message(content=self._status_text(), view=self)

    async def _on_schedule(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        raid_info = RAIDS.get(self.selected_raid, {}) if self.selected_raid else {}
        await interaction.response.send_modal(ScheduleAndMemoModal(self, raid_info))

    async def _on_create(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        if self._creating:
            await interaction.response.send_message("이미 공대를 생성 중입니다.", ephemeral=True)
            return
        self._creating = True  # 첫 번째 await 이전에 플래그 설정 — 경쟁 조건 방지
        self.stop()  # 생성 완료 후 타임아웃 핸들러가 메시지를 덮지 않도록 중단
        await _post_party(
            interaction,
            self.selected_raid, self.selected_difficulty, self.selected_proficiency,
            self.scheduled_time, self.scheduled_datetime, self.forum_channel_id,
            memo=self.memo,
        )


class ScheduleAndMemoModal(Modal, title="일정 및 메모 설정"):
    date_input = TextInput(
        label="날짜",
        placeholder="예) 0514  /  20260514  /  2026/05/14",
        min_length=3,
        max_length=10,
    )
    time_input = TextInput(
        label="시간",
        placeholder="예) 2000  /  20  /  20:00",
        min_length=1,
        max_length=5,
    )
    memo_input = TextInput(
        label="공지/메모 (선택사항)",
        placeholder="예) 신규 환영, 헤드셋 필수, 도구 챙겨오세요",
        required=False,
        max_length=150,
        style=discord.TextStyle.short,
    )

    def __init__(self, recruit_view: "RecruitView", raid_info: dict | None = None) -> None:
        super().__init__()
        self.recruit_view = recruit_view
        self.raid_info = raid_info or {}

    async def on_submit(self, interaction: discord.Interaction) -> None:
        dt = _parse_schedule(self.date_input.value, self.time_input.value)
        if dt is None:
            await interaction.response.send_message(
                "❌ 날짜/시간 형식이 올바르지 않습니다.\n"
                "날짜: `0514` `20260514` `2026/05/14`\n"
                "시간: `2000` `20` `20:00`",
                ephemeral=True,
            )
            return
        if dt < datetime.now(KST):
            await interaction.response.send_message(
                "❌ 과거 날짜로는 설정할 수 없습니다.", ephemeral=True
            )
            return

        # 익스트림 레이드 기간 검증 — 파티 일정이 운영 기간 안에 있어야 함
        if self.raid_info.get("is_extreme"):
            avail_from  = self.raid_info.get("available_from")
            avail_until = self.raid_info.get("available_until")
            if avail_from:
                try:
                    from_dt = datetime.fromisoformat(avail_from)
                    if dt < from_dt:
                        await interaction.response.send_message(
                            f"❌ 이 익스트림 레이드는 **{from_dt.month}/{from_dt.day}**부터 진행 가능합니다.\n"
                            f"공대 모집은 가능하지만 일정은 그 이후로 잡아주세요.",
                            ephemeral=True,
                        )
                        return
                except ValueError:
                    pass
            if avail_until:
                try:
                    until_dt = datetime.fromisoformat(avail_until)
                    if dt > until_dt:
                        await interaction.response.send_message(
                            f"❌ 이 익스트림 레이드는 **{until_dt.month}/{until_dt.day}**까지 진행 가능합니다.",
                            ephemeral=True,
                        )
                        return
                except ValueError:
                    pass

        self.recruit_view.scheduled_time     = _format_schedule(dt)
        self.recruit_view.scheduled_datetime = dt.isoformat()
        self.recruit_view.memo = self.memo_input.value.strip() or None
        self.recruit_view._build()

        await interaction.response.defer()
        orig = self.recruit_view._original_interaction
        if orig:
            await orig.edit_original_response(
                content=self.recruit_view._status_text(),
                view=self.recruit_view,
            )


class CancelModal(Modal, title="공대 취소"):
    reason = TextInput(
        label="취소 사유 (선택사항)",
        placeholder="예) 인원 부족, 일정 변경, 개인 사정 등",
        required=False,
        max_length=200,
        style=discord.TextStyle.short,
    )

    def __init__(self, party: dict) -> None:
        super().__init__()
        self.party = party

    async def on_submit(self, interaction: discord.Interaction) -> None:
        message_id = self.party["message_id"]
        slots      = await db.get_party_slots(message_id)
        raid_title = f"{self.party['raid_name']} {self.party['difficulty']}"
        reason_text = self.reason.value.strip()

        await db.purge_party(message_id)
        await interaction.response.send_message("❌ 공대가 취소되었습니다.", ephemeral=True)

        leader_id = self.party["leader_id"]
        dm_content = f"❌ **{raid_title}** 공대가 파티장에 의해 취소되었습니다."
        if reason_text:
            dm_content += f"\n📌 사유: {reason_text}"

        for s in slots:
            if s["discord_id"] != leader_id:
                await _send_dm(interaction.client, s["discord_id"], dm_content)

        # embed를 종료 상태로 갱신 — 채널 삭제 실패 시에도 embed가 방치되지 않도록
        try:
            from bot.ui.embeds import party_embed
            cancelled_party = {**self.party, "status": "disbanded"}
            msg = await interaction.channel.fetch_message(int(message_id))
            await msg.edit(embed=party_embed(cancelled_party, slots), view=None)
        except discord.HTTPException:
            pass

        try:
            await interaction.channel.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass


class ScheduleChangeModal(Modal, title="일정 및 메모 변경"):
    date_input = TextInput(
        label="날짜",
        placeholder="예) 0514  /  20260514  /  2026/05/14",
        min_length=3,
        max_length=10,
    )
    time_input = TextInput(
        label="시간",
        placeholder="예) 2000  /  20  /  20:00",
        min_length=1,
        max_length=5,
    )
    memo_input = TextInput(
        label="공지/메모 (비워두면 기존 메모 삭제)",
        required=False,
        max_length=150,
        style=discord.TextStyle.short,
    )

    def __init__(self, party: dict, message: discord.Message) -> None:
        super().__init__()
        self.party   = party
        self.message = message
        if party.get("memo"):
            self.memo_input.default = party["memo"]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        dt_kst = _parse_schedule(self.date_input.value, self.time_input.value)
        if dt_kst is None:
            await interaction.response.send_message(
                "❌ 날짜/시간 형식이 올바르지 않습니다.\n"
                "날짜: `0514` `20260514` `2026/05/14`\n"
                "시간: `2000` `20` `20:00`",
                ephemeral=True,
            )
            return

        if dt_kst < datetime.now(KST):
            await interaction.response.send_message(
                "❌ 과거 날짜로는 변경할 수 없습니다.", ephemeral=True
            )
            return

        scheduled_time = _format_schedule(dt_kst)

        message_id = self.party["message_id"]
        await db.update_party_schedule(message_id, scheduled_time, dt_kst.isoformat())
        await db.update_party_memo(message_id, self.memo_input.value.strip() or None)

        party    = await db.get_party(message_id)
        slots    = await db.get_party_slots(message_id)
        reserved = await db.get_reserved_slots(message_id)
        from bot.ui.embeds import party_embed
        embed = party_embed(party, slots, reserved)

        closed = party["status"] == "closed"
        await self.message.edit(
            embed=embed,
            view=PartyView(total_slots=self.party["total_slots"], closed=closed),
        )

        raid_info = RAIDS.get(party["raid_name"], {})
        short_name = raid_info.get("short_name", party["raid_name"])
        new_name = f"{short_name} {party['difficulty']} {party['proficiency']} — {scheduled_time}"
        try:
            await interaction.channel.edit(name=new_name)
        except discord.HTTPException:
            pass

        await interaction.response.send_message(
            f"📅 일정이 **{scheduled_time}**으로 변경되었습니다.", ephemeral=True
        )
        await interaction.channel.send(f"📅 일정이 **{scheduled_time}**으로 변경되었습니다.")

        # 파티원(파티장 제외)에게 DM
        raid_title = f"{party['raid_name']} {party['difficulty']}"
        link = _party_url(party)
        leader_id = party["leader_id"]
        for s in slots:
            if s["discord_id"] != leader_id:
                reason = self.memo_input.value.strip()
                reason_text = f"\n📝 사유: {reason}" if reason else ""
                await _send_dm(
                    interaction.client, s["discord_id"],
                    f"📅 **{raid_title}** 공대 일정이 변경되었습니다.\n"
                    f"새 일정: **{scheduled_time}**{reason_text}\n{link}",
                )


async def _post_party(
    interaction: discord.Interaction,
    raid_name: str,
    difficulty: str,
    proficiency: str,
    scheduled_time: str,
    scheduled_datetime: str | None = None,
    forum_channel_id: str | None = None,
    memo: str | None = None,
) -> None:
    diff_info   = get_difficulty_info(raid_name, difficulty)
    total_slots = diff_info["total_slots"]
    min_level   = diff_info["min_level"]
    leader_id   = str(interaction.user.id)

    raid_info  = RAIDS.get(raid_name, {})
    short_name = raid_info.get("short_name", raid_name)

    tmp_party = {
        "message_id": "0", "channel_id": "0", "guild_id": "0",
        "leader_id": leader_id, "raid_name": raid_name,
        "difficulty": difficulty, "proficiency": proficiency,
        "scheduled_time": scheduled_time, "total_slots": total_slots,
        "min_level": min_level, "status": "recruiting",
    }

    from bot.ui.embeds import party_embed
    embed = party_embed(tmp_party, [])
    view  = PartyView(total_slots=total_slots)

    await interaction.response.edit_message(content="✅ 공대 모집 게시물을 생성합니다.", view=None)

    forum = interaction.client.get_channel(int(forum_channel_id))
    thread_name = f"{short_name} {difficulty} {proficiency} — {scheduled_time}"
    thread, starter_msg = await forum.create_thread(name=thread_name, embed=embed, view=view)

    await db.create_party(
        message_id=str(starter_msg.id), channel_id=str(thread.id),
        guild_id=str(interaction.guild_id), leader_id=leader_id,
        raid_name=raid_name, difficulty=difficulty, proficiency=proficiency,
        scheduled_time=scheduled_time, scheduled_datetime=scheduled_datetime,
        total_slots=total_slots, min_level=min_level, memo=memo,
    )

    # 실제 message_id 기반 embed 갱신
    party = await db.get_party(str(starter_msg.id))
    await starter_msg.edit(embed=party_embed(party, []), view=view)

    # 구독자 DM 발송 (생성자·이미 해당 레이드 참여 중인 유저 제외)
    subscribers = await db.get_raid_subscribers(raid_name, difficulty)
    if subscribers:
        # 이번 주 해당 레이드에 이미 참여 중인 유저 집합
        party_week_key = db.get_week_key_for_dt(scheduled_datetime) if scheduled_datetime else db.get_week_key()
        already_in: set[str] = set()
        new_msg_id = str(starter_msg.id)
        for sub_id in subscribers:
            slots = await db.get_user_active_slots_in_raid(sub_id, raid_name, new_msg_id, party_week_key)
            if slots:
                already_in.add(sub_id)

        dm_embed = discord.Embed(
            title=f"🔔 {raid_name} {difficulty} 새 공대가 모집을 시작했습니다!",
            url=f"https://discord.com/channels/{interaction.guild_id}/{thread.id}/{starter_msg.id}",
            description=f"숙련도: **{proficiency}** | 일정: **{scheduled_time}**",
            color=0x3498DB,
        )
        for sub_id in subscribers:
            if sub_id != leader_id and sub_id not in already_in:
                try:
                    user = await interaction.client.fetch_user(int(sub_id))
                    await user.send(embed=dm_embed)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    pass
                await db.log_notification(sub_id, raid_name, difficulty, new_msg_id)


async def _auto_join_dps(
    interaction: discord.Interaction,
    discord_id: str,
    char_info: dict,
    message_id: str,
    total_slots: int,
    party_view: "PartyView",
    *,
    party_group: int | None = None,
    party_split: int | None = None,
    responded: bool = False,
) -> None:
    """딜러 클래스 자동 딜러 배정 후 참여."""
    ok, slot_number, msg_text = await db.auto_assign_slot(
        message_id, discord_id,
        char_info["name"], char_info["class"], "dps", total_slots,
        party_group=party_group,
        party_split=party_split,
    )
    result = (
        f"✅ **{char_info['name']}** ({char_info['class']}) ⚔️ 딜러로 "
        f"**{slot_number}번** 슬롯에 참여했습니다!"
        if ok else f"❌ {msg_text}"
    )
    if responded:
        await interaction.response.edit_message(content=result, view=None)
    else:
        await interaction.response.send_message(result, ephemeral=True)

    if ok:
        await db.remove_waitlist(message_id, discord_id)
        party_info = await db.get_party(message_id)
        # embed 갱신을 리더 DM보다 먼저 — Discord 클라이언트가 즉시 반영하도록
        try:
            msg = await interaction.channel.fetch_message(int(message_id))
            await party_view._refresh_party(msg)
        except discord.HTTPException:
            pass
        if party_info and party_info["leader_id"] != discord_id:
            raid_title = f"{party_info['raid_name']} {party_info['difficulty']}"
            link = _party_url(party_info)
            await _send_dm(
                interaction.client, party_info["leader_id"],
                f"⚔️ **{raid_title}** 공대에 **{char_info['name']}**({char_info['class']})이(가) 참여했습니다!\n{link}",
            )


# ─────────────────────────────────────────────────────
# 공대 모집 — 참여 기반 View
# ─────────────────────────────────────────────────────

class PartyView(View):
    """공대 뷰 — 참여하기 / 나가기 / 빈자리 알림 / ⚙️ 관리(파티장 전용 패널)."""

    def __init__(self, total_slots: int = 8, closed: bool = False) -> None:
        super().__init__(timeout=None)
        self.total_slots = total_slots

        join_btn = Button(
            label="참여하기", emoji="⚔️",
            style=discord.ButtonStyle.primary,
            custom_id="party:join",
            disabled=closed,
            row=0,
        )
        join_btn.callback = self._handle_join
        self.add_item(join_btn)

        leave_btn = Button(
            label="나가기", emoji="🚪",
            style=discord.ButtonStyle.secondary,
            custom_id="party:leave",
            row=0,
        )
        leave_btn.callback = self._handle_leave
        self.add_item(leave_btn)

        waitlist_btn = Button(
            label="빈자리 알림", emoji="🔔",
            style=discord.ButtonStyle.secondary,
            custom_id="party:waitlist",
            row=1,
        )
        waitlist_btn.callback = self._handle_waitlist
        self.add_item(waitlist_btn)

        manage_btn = Button(
            label="관리", emoji="⚙️",
            style=discord.ButtonStyle.secondary,
            custom_id="party:manage",
            row=1,
        )
        manage_btn.callback = self._handle_manage
        self.add_item(manage_btn)

    # ── 참여하기 ────────────────────────────────────

    async def _handle_join(self, interaction: discord.Interaction) -> None:
        party = await db.get_party_by_channel(str(interaction.channel.id))
        if not party or party["status"] == "disbanded":
            await interaction.response.send_message("유효하지 않은 파티입니다.", ephemeral=True)
            return
        if party["status"] == "closed":
            await interaction.response.send_message("모집이 마감된 파티입니다.", ephemeral=True)
            return
        if party["status"] == "full":
            await interaction.response.send_message("파티가 이미 꽉 찼습니다.", ephemeral=True)
            return

        message_id = party["message_id"]
        discord_id = str(interaction.user.id)
        party_week_key = (
            db.get_week_key_for_dt(party["scheduled_datetime"])
            if party.get("scheduled_datetime")
            else db.get_week_key()
        )

        slots = await db.get_party_slots(message_id)
        if any(s["discord_id"] == discord_id for s in slots):
            await interaction.response.send_message("이미 파티에 참여 중입니다.", ephemeral=True)
            return


        # ── 익스트림 레이드 추가 검증 ─────────────────────
        raid_info = RAIDS.get(party["raid_name"], {})
        if raid_info.get("is_extreme"):
            now         = datetime.now(KST)
            avail_from  = raid_info.get("available_from")
            avail_until = raid_info.get("available_until")
            sdt         = party.get("scheduled_datetime")

            # 파티 일정이 운영 기간 시작 전이면 참여 불가
            if sdt and avail_from:
                try:
                    if datetime.fromisoformat(sdt) < datetime.fromisoformat(avail_from):
                        from_dt = datetime.fromisoformat(avail_from)
                        await interaction.response.send_message(
                            f"이 공대 일정은 운영 기간 시작({from_dt.month}/{from_dt.day}) 전입니다.",
                            ephemeral=True,
                        )
                        return
                except ValueError:
                    pass

            # 현재 시각이 운영 기간 종료 이후이면 참여 불가
            if avail_until:
                try:
                    if datetime.fromisoformat(avail_until) < now:
                        await interaction.response.send_message(
                            "운영 기간이 종료된 레이드입니다.", ephemeral=True
                        )
                        return
                except ValueError:
                    pass
            # 원정대 1캐릭터 제한
            extreme_slot = await db.get_user_extreme_slot_this_week(discord_id, party_week_key)
            if extreme_slot:
                await interaction.response.send_message(
                    f"이번 주 익스트림 레이드는 **{extreme_slot['character_name']}**으로 이미 참여 중입니다.\n"
                    f"원정대당 1캐릭터만 참여할 수 있습니다.",
                    ephemeral=True,
                )
                return

        api_key = await db.get_user_api_key(discord_id)
        if not api_key:
            await interaction.response.send_message(
                "먼저 `/api등록`으로 API 키를 등록해주세요.", ephemeral=True
            )
            return

        registered = await db.get_user_characters(discord_id)
        if not registered:
            await interaction.response.send_message(
                "먼저 `/캐릭터등록`으로 캐릭터를 등록해주세요.", ephemeral=True
            )
            return

        min_level: int = party["min_level"]
        cached    = await db.get_cached_characters(discord_id, max_age_hours=99999)
        cache_map = {c["character_name"]: c for c in cached}

        # 캐시 기반 필터 (API 호출 없음 → defer 불필요, 현재 메시지 위치에서 바로 응답)
        qualifying: list[dict] = []
        level_too_low: list[str] = []
        no_cache: list[str] = []
        raid_key = f"{party['raid_name']}_{party['difficulty']}"

        for char_name in registered:
            c = cache_map.get(char_name)
            if not c or c["item_level"] is None:
                no_cache.append(char_name)
            elif c["item_level"] < min_level:
                level_too_low.append(f"**{char_name}** ({c['item_level']:.0f})")
            else:
                qualifying.append({"name": char_name, "level": c["item_level"], "class": c["character_class"]})

        # 골드 완료 캐릭터 필터링 — 파티 주차 기준으로 확인
        gold_done: list[str] = []
        filtered = []
        for q in qualifying:
            completions = await db.get_completions(discord_id, q["name"], week_key=party_week_key)
            if any(k.startswith(f"{party['raid_name']}_") for k in completions):
                gold_done.append(f"**{q['name']}**")
            else:
                filtered.append(q)
        qualifying = filtered

        # 같은 레이드·같은 주차의 다른 공대에 이미 참여 중인 캐릭터 필터링
        # (discord_id 전체 차단 → 캐릭터 단위 차단으로 변경)
        already_slots = await db.get_user_active_slots_in_raid(
            discord_id, party["raid_name"], message_id, party_week_key=party_week_key
        )
        already_chars = {s["character_name"] for s in already_slots}
        in_other_party: list[str] = []
        filtered2 = []
        for q in qualifying:
            if q["name"] in already_chars:
                in_other_party.append(f"**{q['name']}**")
            else:
                filtered2.append(q)
        qualifying = filtered2

        if not qualifying:
            lines: list[str] = []
            if gold_done:
                lines.append(f"🏆 이번 주 골드 완료: {', '.join(gold_done)}")
            if in_other_party:
                lines.append(f"⚔️ 다른 공대 참여 중: {', '.join(in_other_party)}")
            if level_too_low:
                lines.append(f"📉 레벨 미달 (최소 {min_level}): {', '.join(level_too_low)}")
            if no_cache:
                names = ', '.join(f"**{n}**" for n in no_cache)
                lines.append(f"❓ 레벨 미확인: {names} — `/원정대`에서 동기화 후 다시 시도해주세요.")
            detail = "\n".join(lines) if lines else "(원인 불명)"
            await interaction.response.send_message(
                f"**{party['raid_name']} {party['difficulty']}** 에 참여 가능한 캐릭터가 없습니다.\n{detail}",
                ephemeral=True,
            )
            return

        raid_info = RAIDS.get(party["raid_name"], {})
        p_split   = (raid_info.get("difficulties") or {}).get(party["difficulty"], {}).get("party_split")

        if len(qualifying) == 1:
            q = qualifying[0]
            if p_split and party["total_slots"] > p_split:
                current_slots = await db.get_party_slots(message_id)
                view = PartyGroupSelectView(
                    discord_id, q, message_id, party["total_slots"],
                    p_split, current_slots, self,
                )
                await interaction.response.send_message(
                    f"**{q['name']}** ({q['class']}) — 참여할 파티를 선택하세요:",
                    view=view, ephemeral=True,
                )
                try:
                    view.message = await interaction.original_response()
                except discord.HTTPException:
                    pass
            elif q["class"] in SUPPORT_CLASSES:
                view = RoleSelectView(discord_id, q, message_id, party["total_slots"], self)
                await interaction.response.send_message(
                    f"**{q['name']}** ({q['class']}) — 역할을 선택하세요:",
                    view=view, ephemeral=True,
                )
                try:
                    view.message = await interaction.original_response()
                except discord.HTTPException:
                    pass
            else:
                await _auto_join_dps(
                    interaction, discord_id, q, message_id, party["total_slots"], self,
                )
        else:
            view = CharSelectView(discord_id, qualifying, message_id, party["total_slots"], self)
            await interaction.response.send_message("참여할 캐릭터를 선택하세요:", view=view, ephemeral=True)
            try:
                view.message = await interaction.original_response()
            except discord.HTTPException:
                pass

    # ── 나가기 ─────────────────────────────────────

    async def _handle_leave(self, interaction: discord.Interaction) -> None:
        party = await db.get_party_by_channel(str(interaction.channel.id))
        if not party or party["status"] == "disbanded":
            await interaction.response.send_message("유효하지 않은 파티입니다.", ephemeral=True)
            return

        message_id    = party["message_id"]
        discord_id    = str(interaction.user.id)
        is_leader     = party["leader_id"] == discord_id
        was_full      = party["status"] == "full"

        removed = await db.leave_slot(message_id, discord_id)
        if not removed:
            await interaction.response.send_message("파티에 참여하지 않았습니다.", ephemeral=True)
            return

        # 파티장이 나가면 다음 참여자에게 리더십 양도
        if is_leader:
            remaining = await db.get_party_slots(message_id)
            if remaining:
                new_leader = remaining[0]["discord_id"]
                await db.transfer_leader(message_id, new_leader)
                await interaction.response.send_message(
                    f"파티에서 나갔습니다. <@{new_leader}>님이 새 파티장이 되었습니다.", ephemeral=True
                )
                await interaction.channel.send(
                    f"👑 **파티장 변경** — <@{new_leader}>님이 새 파티장이 되었습니다."
                )
                # embed 갱신을 리더 DM보다 먼저 — Discord 클라이언트가 즉시 반영하도록
                await self._refresh_party(interaction.message, was_full=was_full, client=interaction.client)
                await _send_dm(
                    interaction.client, new_leader,
                    f"👑 **{party['raid_name']} {party['difficulty']}** 공대의 파티장이 되었습니다!\n{_party_url(party)}",
                )
                return
            else:
                # 마지막 멤버였으면 파티 자동 종료
                await db.disband_party(message_id)
                party["status"] = "disbanded"
                slots = await db.get_party_slots(message_id)
                from bot.ui.embeds import party_embed
                await interaction.response.edit_message(embed=party_embed(party, slots), view=None)
                raid_title = f"{party['raid_name']} {party['difficulty']}"
                await interaction.channel.send(
                    f"🔒 **{raid_title}** 파티원이 모두 나가 공대가 종료되었습니다."
                )
                try:
                    await interaction.channel.edit(archived=True, locked=True)
                except discord.HTTPException:
                    pass
                return
        else:
            await interaction.response.send_message("파티에서 나갔습니다.", ephemeral=True)

        await self._refresh_party(interaction.message, was_full=was_full, client=interaction.client)

    # ── 관리 패널 오픈 ───────────────────────────────

    async def _handle_manage(self, interaction: discord.Interaction) -> None:
        party = await db.get_party_by_channel(str(interaction.channel.id))
        if not party or party["status"] == "disbanded":
            await interaction.response.send_message("유효하지 않은 파티입니다.", ephemeral=True)
            return
        if party["leader_id"] != str(interaction.user.id):
            await interaction.response.send_message("파티장만 사용할 수 있습니다.", ephemeral=True)
            return
        view = ManageView(party, interaction.message, self.total_slots)
        await interaction.response.send_message("⚙️ **공대 관리**", view=view, ephemeral=True)
        view._manage_interaction = interaction

    # ── 빈자리 알림 ──────────────────────────────────

    async def _handle_waitlist(self, interaction: discord.Interaction) -> None:
        party = await db.get_party_by_channel(str(interaction.channel.id))
        if not party or party["status"] == "disbanded":
            await interaction.response.send_message("유효하지 않은 파티입니다.", ephemeral=True)
            return
        discord_id = str(interaction.user.id)
        message_id = party["message_id"]

        # 이미 파티에 참여 중이면 알림 불필요
        slots = await db.get_party_slots(message_id)
        if any(s["discord_id"] == discord_id for s in slots):
            await interaction.response.send_message(
                "이미 파티에 참여 중입니다.", ephemeral=True
            )
            return

        waitlist = await db.get_waitlist(message_id)
        if discord_id in waitlist:
            await db.remove_waitlist(message_id, discord_id)
            await interaction.response.send_message(
                "🔕 빈자리 알림이 취소되었습니다.", ephemeral=True
            )
        else:
            await db.add_waitlist(message_id, discord_id)
            await interaction.response.send_message(
                "🔔 빈자리가 생기면 DM으로 알려드립니다.", ephemeral=True
            )

    # ── 공통 갱신 ───────────────────────────────────

    async def _refresh_party(
        self, message: discord.Message, *, was_full: bool = False,
        client: discord.Client | None = None,
    ) -> None:
        party = await db.get_party_by_channel(str(message.channel.id))
        if not party:
            return
        slots = await db.get_party_slots(party["message_id"])

        from bot.ui.embeds import party_embed
        reserved = await db.get_reserved_slots(party["message_id"])
        embed = party_embed(party, slots, reserved)
        if party["status"] == "disbanded":
            await message.edit(embed=embed, view=None)
            return
        view  = PartyView(total_slots=self.total_slots, closed=(party["status"] == "closed"))
        await message.edit(embed=embed, view=view)

        if party["status"] == "full":
            mentions = " ".join(f"<@{s['discord_id']}>" for s in slots)
            await message.channel.send(
                f"🎉 **{party['raid_name']} {party['difficulty']}** 파티가 완성되었습니다!\n{mentions}"
            )
        elif was_full and party["status"] == "recruiting":
            raid_title = f"{party['raid_name']} {party['difficulty']} {party['proficiency']}"
            await message.channel.send(
                f"📢 **{raid_title}** 파티에 빈 자리가 생겼습니다! "
                f"`{len(slots)}/{party['total_slots']}`"
            )
            if client:
                await _notify_waitlist(client, party)


# ─────────────────────────────────────────────────────
# 공대 모집 — 캐릭터 선택 → 파티 선택 → 역할 선택 플로우
# ─────────────────────────────────────────────────────

class PartyGroupSelectView(View):
    """다중 파티일 때 참여할 파티(1파티/2파티)를 선택하는 뷰."""

    def __init__(
        self,
        discord_id: str,
        char_info: dict,
        message_id: str,
        total_slots: int,
        party_split: int,
        current_slots: list[dict],
        party_view: PartyView,
    ) -> None:
        super().__init__(timeout=60)
        self.discord_id  = discord_id
        self.char_info   = char_info
        self.message_id  = message_id
        self.total_slots = total_slots
        self.party_split = party_split
        self.party_view  = party_view
        self.message: discord.Message | None = None

        slot_map    = {s["slot_number"]: s for s in current_slots}
        num_parties = total_slots // party_split

        for p in range(num_parties):
            start  = p * party_split + 1
            filled = sum(1 for sn in range(start, start + party_split) if sn in slot_map)
            is_full = filled >= party_split
            btn = Button(
                label=f"{p + 1}파티  {filled}/{party_split}" + ("  (만석)" if is_full else ""),
                style=discord.ButtonStyle.secondary if is_full else discord.ButtonStyle.primary,
                disabled=is_full,
            )
            btn.callback = self._make_cb(p + 1)
            self.add_item(btn)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(content="⏱️ 선택 시간(60초)이 초과되었습니다.", view=None)
            except discord.HTTPException:
                pass

    def _make_cb(self, party_group: int):
        async def cb(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.discord_id:
                await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
                return
            party = await db.get_party(self.message_id)
            if not party or party["status"] == "disbanded":
                await interaction.response.edit_message(content="❌ 파티가 이미 종료되었습니다.", view=None)
                return
            if party["status"] == "closed":
                await interaction.response.edit_message(content="❌ 모집이 마감되어 참여할 수 없습니다.", view=None)
                return
            if self.char_info["class"] in SUPPORT_CLASSES:
                view = RoleSelectView(
                    self.discord_id, self.char_info, self.message_id,
                    self.total_slots, self.party_view,
                    party_group=party_group, party_split=self.party_split,
                )
                await interaction.response.edit_message(
                    content=(
                        f"**{self.char_info['name']}** ({self.char_info['class']}) "
                        f"{party_group}파티 — 역할을 선택하세요:"
                    ),
                    view=view,
                )
                try:
                    view.message = await interaction.original_response()
                except discord.HTTPException:
                    pass
            else:
                await _auto_join_dps(
                    interaction, self.discord_id, self.char_info,
                    self.message_id, self.total_slots, self.party_view,
                    party_group=party_group, party_split=self.party_split,
                    responded=True,
                )
        return cb


class CharSelectView(View):
    def __init__(
        self,
        discord_id: str,
        qualifying: list[dict],
        message_id: str,
        total_slots: int,
        party_view: PartyView,
    ) -> None:
        super().__init__(timeout=60)
        self.discord_id = discord_id
        self.char_map = {q["name"]: q for q in qualifying}
        self.message_id = message_id
        self.total_slots = total_slots
        self.party_view = party_view
        self.message: discord.Message | None = None

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

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(content="⏱️ 선택 시간(60초)이 초과되었습니다.", view=None)
            except discord.HTTPException:
                pass

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
            return
        char_name = interaction.data["values"][0]
        char_info = self.char_map[char_name]

        party = await db.get_party(self.message_id)
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="❌ 파티가 이미 종료되었습니다.", view=None)
            return
        if party["status"] == "closed":
            await interaction.response.edit_message(content="❌ 모집이 마감되어 참여할 수 없습니다.", view=None)
            return

        p_split = None
        raid_info = RAIDS.get(party["raid_name"], {})
        p_split = (raid_info.get("difficulties") or {}).get(party["difficulty"], {}).get("party_split")

        if p_split and self.total_slots > p_split:
            current_slots = await db.get_party_slots(self.message_id)
            view = PartyGroupSelectView(
                self.discord_id, char_info, self.message_id,
                self.total_slots, p_split, current_slots, self.party_view,
            )
            await interaction.response.edit_message(
                content=f"**{char_name}** ({char_info['class']}) — 참여할 파티를 선택하세요:",
                view=view,
            )
            try:
                view.message = await interaction.original_response()
            except discord.HTTPException:
                pass
        elif char_info["class"] in SUPPORT_CLASSES:
            view = RoleSelectView(self.discord_id, char_info, self.message_id, self.total_slots, self.party_view)
            await interaction.response.edit_message(
                content=f"**{char_name}** ({char_info['class']}) — 역할을 선택하세요:",
                view=view,
            )
            try:
                view.message = await interaction.original_response()
            except discord.HTTPException:
                pass
        else:
            await _auto_join_dps(
                interaction, self.discord_id, char_info,
                self.message_id, self.total_slots, self.party_view,
                responded=True,
            )


class RoleSelectView(View):
    def __init__(
        self,
        discord_id: str,
        char_info: dict,
        message_id: str,
        total_slots: int,
        party_view: PartyView,
        *,
        party_group: int | None = None,
        party_split: int | None = None,
    ) -> None:
        super().__init__(timeout=60)
        self.discord_id  = discord_id
        self.char_info   = char_info
        self.message_id  = message_id
        self.total_slots = total_slots
        self.party_view  = party_view
        self.party_group = party_group
        self.party_split = party_split
        self.message: discord.Message | None = None

        is_support = char_info["class"] in SUPPORT_CLASSES

        dps_btn = Button(label="딜러", emoji="⚔️", style=discord.ButtonStyle.secondary)
        dps_btn.callback = self._make_role_cb("dps")
        self.add_item(dps_btn)

        support_btn = Button(
            label="서포터 (추천)" if is_support else "서포터",
            emoji="🛡️",
            style=discord.ButtonStyle.primary,
        )
        support_btn.callback = self._make_role_cb("support")
        self.add_item(support_btn)

    async def on_timeout(self) -> None:
        if self.message:
            try:
                await self.message.edit(content="⏱️ 선택 시간(60초)이 초과되었습니다.", view=None)
            except discord.HTTPException:
                pass

    def _make_role_cb(self, role: str):
        async def cb(interaction: discord.Interaction) -> None:
            if str(interaction.user.id) != self.discord_id:
                await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
                return

            # 역할 선택 시점에 party 상태 재확인
            party = await db.get_party(self.message_id)
            if not party or party["status"] == "disbanded":
                await interaction.response.edit_message(content="❌ 파티가 이미 종료되었습니다.", view=None)
                return
            if party["status"] == "closed":
                await interaction.response.edit_message(content="❌ 모집이 마감되어 참여할 수 없습니다.", view=None)
                return

            char = self.char_info
            ok, slot_number, msg_text = await db.auto_assign_slot(
                self.message_id, self.discord_id,
                char["name"], char["class"], role, self.total_slots,
                party_group=self.party_group,
                party_split=self.party_split,
            )
            if not ok:
                await interaction.response.edit_message(content=f"❌ {msg_text}", view=None)
                return
            role_icon = "🛡️" if role == "support" else "⚔️"
            role_text = "서포터" if role == "support" else "딜러"
            await interaction.response.edit_message(
                content=(
                    f"✅ **{char['name']}** ({char['class']}) {role_icon} {role_text}로 "
                    f"**{slot_number}번** 슬롯에 참여했습니다!"
                ),
                view=None,
            )
            await db.remove_waitlist(self.message_id, self.discord_id)
            # embed 갱신을 리더 DM보다 먼저 — Discord 클라이언트가 즉시 반영하도록
            try:
                msg = await interaction.channel.fetch_message(int(self.message_id))
                await self.party_view._refresh_party(msg)
            except discord.HTTPException:
                pass
            if party and party["leader_id"] != self.discord_id:
                raid_title = f"{party['raid_name']} {party['difficulty']}"
                role_icon = "🛡️" if role == "support" else "⚔️"
                await _send_dm(
                    interaction.client, party["leader_id"],
                    f"{role_icon} **{raid_title}** 공대에 **{char['name']}**({char['class']})이(가) 참여했습니다!\n{_party_url(party)}",
                )
        return cb


# ─────────────────────────────────────────────────────
# 강제 퇴장 선택 뷰
# ─────────────────────────────────────────────────────

class KickSelectView(View):
    def __init__(
        self, message_id: str, slots: list[dict], total_slots: int,
        original_message: discord.Message | None = None,
    ) -> None:
        super().__init__(timeout=60)
        self.message_id       = message_id
        self.total_slots      = total_slots
        self.original_message = original_message
        self.char_map         = {s["discord_id"]: s["character_name"] for s in slots}

        options = [
            discord.SelectOption(
                label=s["character_name"],
                description=f"{s['character_class']} | {'서포터' if s['role'] == 'support' else '딜러'} | {s['slot_number']}번 슬롯",
                value=s["discord_id"],
            )
            for s in slots
        ]
        sel = Select(placeholder="퇴장시킬 파티원 선택", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        target_id = interaction.data["values"][0]
        char_name = self.char_map.get(target_id, "알 수 없음")
        pre_party = await db.get_party(self.message_id)
        was_full  = (pre_party or {}).get("status") == "full"
        removed   = await db.leave_slot(self.message_id, target_id)
        if not removed:
            await interaction.response.edit_message(content="❌ 파티원을 찾을 수 없습니다.", view=None)
            return
        # 퇴장 대상에게 DM
        if pre_party:
            raid_title = f"{pre_party['raid_name']} {pre_party['difficulty']}"
            await _send_dm(
                interaction.client, target_id,
                f"⚠️ **{raid_title}** 공대에서 파티장에 의해 퇴장되었습니다.",
            )
        # 공대 embed 갱신
        try:
            msg = await interaction.channel.fetch_message(int(self.message_id))
            tmp = PartyView(total_slots=self.total_slots)
            await tmp._refresh_party(msg, was_full=was_full, client=interaction.client)
        except discord.HTTPException:
            pass
        # 관리 패널로 복귀
        if self.original_message:
            post_party = await db.get_party(self.message_id)
            if post_party and post_party["status"] != "disbanded":
                manage_view = ManageView(post_party, self.original_message, self.total_slots)
                await interaction.response.edit_message(
                    content=f"✅ **{char_name}**을(를) 강제 퇴장시켰습니다.",
                    view=manage_view,
                )
                manage_view._manage_interaction = interaction
                return
        await interaction.response.edit_message(
            content=f"✅ **{char_name}**을(를) 강제 퇴장시켰습니다.", view=None
        )


# ─────────────────────────────────────────────────────
# 파티장 전용 관리 패널
# ─────────────────────────────────────────────────────

class ManageView(View):
    """⚙️ 관리 버튼으로 열리는 파티장 전용 ephemeral 패널."""

    def __init__(self, party: dict, original_message: discord.Message, total_slots: int) -> None:
        super().__init__(timeout=120)
        self.party            = party
        self.original_message = original_message
        self.total_slots      = total_slots
        self._manage_interaction: discord.Interaction | None = None
        self._build()

    async def on_timeout(self) -> None:
        if self._manage_interaction:
            try:
                await self._manage_interaction.edit_original_response(
                    content="⏱️ 관리 패널 시간이 초과되었습니다. ⚙️ 관리 버튼을 다시 눌러주세요.",
                    view=None,
                )
            except discord.HTTPException:
                pass

    def _build(self) -> None:
        self.clear_items()
        closed = self.party["status"] == "closed"

        if closed:
            reopen_btn = Button(label="모집 재개", emoji="🔓",
                                style=discord.ButtonStyle.primary, row=0)
            reopen_btn.callback = self._handle_reopen
            self.add_item(reopen_btn)
        else:
            disband_btn = Button(label="모집 마감", emoji="🔒",
                                 style=discord.ButtonStyle.danger, row=0)
            disband_btn.callback = self._handle_disband
            self.add_item(disband_btn)

        clear_btn = Button(label="클리어", emoji="🏆",
                           style=discord.ButtonStyle.success, row=0)
        clear_btn.callback = self._handle_clear
        self.add_item(clear_btn)

        cancel_btn = Button(label="파티 취소", emoji="❌",
                            style=discord.ButtonStyle.danger, row=1)
        cancel_btn.callback = self._handle_cancel
        self.add_item(cancel_btn)

        kick_btn = Button(label="강제 퇴장", emoji="🚫",
                          style=discord.ButtonStyle.secondary, row=1)
        kick_btn.callback = self._handle_kick
        self.add_item(kick_btn)

        reschedule_btn = Button(label="일정 변경", emoji="📅",
                                style=discord.ButtonStyle.secondary, row=2)
        reschedule_btn.callback = self._handle_reschedule
        self.add_item(reschedule_btn)

        delegate_btn = Button(label="파티장 위임", emoji="👑",
                              style=discord.ButtonStyle.secondary, row=2)
        delegate_btn.callback = self._handle_delegate
        self.add_item(delegate_btn)

        invite_btn = Button(label="초대", emoji="👥",
                            style=discord.ButtonStyle.primary, row=3)
        invite_btn.callback = self._handle_invite
        self.add_item(invite_btn)


    async def _refresh_original(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party:
            return
        slots    = await db.get_party_slots(party["message_id"])
        reserved = await db.get_reserved_slots(party["message_id"])
        from bot.ui.embeds import party_embed
        closed = party["status"] == "closed"
        try:
            await self.original_message.edit(
                embed=party_embed(party, slots, reserved),
                view=PartyView(total_slots=self.total_slots, closed=closed),
            )
        except discord.HTTPException:
            pass

    # ── 모집 마감 ─────────────────────────────────────

    async def _handle_disband(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] in ("closed", "disbanded"):
            await interaction.response.edit_message(content="처리할 수 없는 상태입니다.", view=None)
            return
        await db.close_party(party["message_id"])
        self.party = await db.get_party(party["message_id"])
        self._build()
        await interaction.response.edit_message(content="🔒 모집이 마감되었습니다. 추가 작업이 필요하면 아래 버튼을 이용하세요.", view=self)
        await self._refresh_original(interaction)

    # ── 모집 재개 ─────────────────────────────────────

    async def _handle_reopen(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] != "closed":
            await interaction.response.edit_message(content="처리할 수 없는 상태입니다.", view=None)
            return
        await db.reopen_party(party["message_id"])
        self.party = await db.get_party(party["message_id"])
        self._build()
        await interaction.response.edit_message(content="🔓 모집이 재개되었습니다. 추가 작업이 필요하면 아래 버튼을 이용하세요.", view=self)
        await self._refresh_original(interaction)
        await _notify_waitlist(interaction.client, self.party)

    # ── 클리어 ───────────────────────────────────────

    async def _handle_clear(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="이미 종료된 파티입니다.", view=None)
            return
        message_id = party["message_id"]
        slots = await db.get_party_slots(message_id)
        if not slots:
            await interaction.response.send_message("파티원이 없어 클리어 처리할 수 없습니다.", ephemeral=True)
            return
        count = await db.complete_raid_for_party(message_id)
        await db.disband_party(message_id)
        party["status"] = "disbanded"
        from bot.ui.embeds import party_embed
        try:
            await self.original_message.edit(embed=party_embed(party, slots), view=None)
        except discord.HTTPException:
            pass
        await interaction.response.edit_message(content="🏆 클리어 처리 완료!", view=None)
        raid_title = f"{party['raid_name']} {party['difficulty']}"
        mentions   = " ".join(f"<@{s['discord_id']}>" for s in slots)
        await interaction.channel.send(
            f"🏆 **{raid_title}** 클리어!\n{mentions}\n"
            f"파티원 **{count}명**의 레이드 체크가 자동 완료되었습니다."
        )
        try:
            await interaction.channel.edit(archived=True, locked=True)
        except discord.HTTPException:
            pass

    # ── 파티 취소 ─────────────────────────────────────

    async def _handle_cancel(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="이미 종료된 파티입니다.", view=None)
            return
        await interaction.response.send_modal(CancelModal(party))

    # ── 강제 퇴장 ─────────────────────────────────────

    async def _handle_kick(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="이미 종료된 파티입니다.", view=None)
            return
        slots    = await db.get_party_slots(party["message_id"])
        kickable = [s for s in slots if s["discord_id"] != str(interaction.user.id)]
        if not kickable:
            await interaction.response.send_message("강제 퇴장시킬 파티원이 없습니다.", ephemeral=True)
            return
        view = KickSelectView(party["message_id"], kickable, self.total_slots, self.original_message)
        await interaction.response.edit_message(content="퇴장시킬 파티원을 선택하세요:", view=view)

    # ── 일정 변경 ─────────────────────────────────────

    async def _handle_reschedule(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="이미 종료된 파티입니다.", view=None)
            return
        await interaction.response.send_modal(
            ScheduleChangeModal(party, self.original_message)
        )

    # ── 초대 ──────────────────────────────────────────

    async def _handle_invite(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="이미 종료된 파티입니다.", view=None)
            return

        slots_in_party = await db.get_party_slots(party["message_id"])
        reserved       = await db.get_reserved_slots(party["message_id"])
        occupied       = {s["slot_number"] for s in slots_in_party}
        in_party_ids   = {s["discord_id"] for s in slots_in_party} | set(reserved.values())
        in_party_ids.add(party["leader_id"])

        # API 등록 유저 목록 (이미 참여/예약된 유저 제외)
        import aiosqlite
        async with aiosqlite.connect(db.DB_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cur = await conn.execute(
                "SELECT u.discord_id, "
                "COALESCE("
                "  (SELECT uc.character_name FROM user_characters uc WHERE uc.discord_id=u.discord_id ORDER BY uc.added_at LIMIT 1),"
                "  (SELECT ps.character_name FROM party_slots ps WHERE ps.discord_id=u.discord_id ORDER BY ps.joined_at DESC LIMIT 1)"
                ") AS representative "
                "FROM users u ORDER BY u.registered_at DESC"
            )
            all_users = [dict(r) for r in await cur.fetchall()]

        invitable = [u for u in all_users if u["discord_id"] not in in_party_ids]
        if not invitable:
            await interaction.response.send_message("초대 가능한 유저가 없습니다.", ephemeral=True)
            return

        view = InviteUserSelectView(
            party, self.original_message, self.total_slots,
            invitable, occupied, set(reserved.keys()),
        )
        await interaction.response.edit_message(content="초대할 유저를 선택하세요:", view=view)

    # ── 파티장 위임 ───────────────────────────────────

    async def _handle_delegate(self, interaction: discord.Interaction) -> None:
        party = await db.get_party(self.party["message_id"])
        if not party or party["status"] == "disbanded":
            await interaction.response.edit_message(content="이미 종료된 파티입니다.", view=None)
            return
        slots     = await db.get_party_slots(party["message_id"])
        delegable = [s for s in slots if s["discord_id"] != str(interaction.user.id)]
        if not delegable:
            await interaction.response.send_message("위임할 파티원이 없습니다.", ephemeral=True)
            return
        view = DelegateSelectView(party, delegable, self.original_message, self.total_slots)
        await interaction.response.edit_message(content="👑 파티장을 위임할 파티원을 선택하세요:", view=view)


# ─────────────────────────────────────────────────────
# 파티장 위임 선택 뷰
# ─────────────────────────────────────────────────────

class DelegateSelectView(View):
    def __init__(
        self, party: dict, slots: list[dict],
        original_message: discord.Message, total_slots: int,
    ) -> None:
        super().__init__(timeout=60)
        self.party            = party
        self.original_message = original_message
        self.total_slots      = total_slots
        self.member_map       = {s["discord_id"]: s["character_name"] for s in slots}

        options = [
            discord.SelectOption(
                label=s["character_name"],
                description=s["character_class"],
                value=s["discord_id"],
            )
            for s in slots
        ]
        sel = Select(placeholder="파티장을 넘겨줄 파티원 선택", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        new_leader_id = interaction.data["values"][0]
        char_name     = self.member_map.get(new_leader_id, "알 수 없음")

        await db.transfer_leader(self.party["message_id"], new_leader_id)

        await interaction.response.edit_message(
            content=f"✅ **{char_name}**님께 파티장을 위임했습니다.", view=None
        )

        # 원본 공대 embed 갱신
        try:
            party    = await db.get_party(self.party["message_id"])
            slots    = await db.get_party_slots(self.party["message_id"])
            reserved = await db.get_reserved_slots(self.party["message_id"])
            from bot.ui.embeds import party_embed
            closed = (party or {}).get("status") == "closed"
            await self.original_message.edit(
                embed=party_embed(party, slots, reserved),
                view=PartyView(total_slots=self.total_slots, closed=closed),
            )
        except discord.HTTPException:
            pass

        # 채널 공지 + 새 파티장 DM
        await interaction.channel.send(
            f"👑 **파티장 변경** — <@{new_leader_id}>님이 새 파티장이 되었습니다."
        )
        await _send_dm(
            interaction.client, new_leader_id,
            f"👑 **{self.party['raid_name']} {self.party['difficulty']}** 공대의 파티장이 되었습니다!\n{_party_url(self.party)}",
        )
