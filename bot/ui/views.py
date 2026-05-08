from __future__ import annotations

import discord
from discord.ui import View, Button, Select, Modal, TextInput
from datetime import datetime, timezone, timedelta

from bot.data.raids import RAIDS, get_applicable_raids, get_difficulty_info, SUPPORT_CLASSES, PROFICIENCY
import bot.database.manager as db
import bot.api.lostark as loa

KST = timezone(timedelta(hours=9))


# ─────────────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────────────

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
        for name in char_names:
            try:
                char = await loa.get_character_info(api_key, name)
            except RuntimeError:
                char = None
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
        await interaction.message.edit(
            embed=expedition_embed(interaction.user, characters), view=self
        )
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
# 공대 모집 — 생성 플로우
# ─────────────────────────────────────────────────────

class RaidSelectView(View):
    def __init__(self, leader_id: str, forum_channel_id: str) -> None:
        super().__init__(timeout=120)
        self.leader_id = leader_id
        self.forum_channel_id = forum_channel_id
        options = [
            discord.SelectOption(
                label=name,
                description=f"{info['category']}  |  최소 {min(d['min_level'] for d in info['difficulties'].values())}",
                emoji=info["icon"],
                value=name,
            )
            for name, info in RAIDS.items()
        ]
        sel = Select(placeholder="모집할 레이드를 선택하세요", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        raid_name = interaction.data["values"][0]
        diffs = list(RAIDS[raid_name]["difficulties"].keys())
        if len(diffs) == 1:
            view = ProficiencySelectView(self.leader_id, raid_name, diffs[0], self.forum_channel_id)
            await interaction.response.edit_message(
                content=f"**{raid_name} {diffs[0]}** — 숙련도를 선택하세요.", view=view
            )
        else:
            view = DifficultySelectView(self.leader_id, raid_name, self.forum_channel_id)
            await interaction.response.edit_message(
                content=f"**{raid_name}** 난이도를 선택하세요.", view=view
            )


class DifficultySelectView(View):
    def __init__(self, leader_id: str, raid_name: str, forum_channel_id: str) -> None:
        super().__init__(timeout=120)
        self.leader_id = leader_id
        self.raid_name = raid_name
        self.forum_channel_id = forum_channel_id
        options = [
            discord.SelectOption(
                label=diff,
                description=f"최소 {info['min_level']}  |  {info['total_slots']}인",
                value=diff,
            )
            for diff, info in RAIDS[raid_name]["difficulties"].items()
        ]
        sel = Select(placeholder="난이도를 선택하세요", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        difficulty = interaction.data["values"][0]
        view = ProficiencySelectView(self.leader_id, self.raid_name, difficulty, self.forum_channel_id)
        await interaction.response.edit_message(
            content=f"**{self.raid_name} {difficulty}** — 숙련도를 선택하세요.", view=view
        )


class ProficiencySelectView(View):
    def __init__(self, leader_id: str, raid_name: str, difficulty: str, forum_channel_id: str) -> None:
        super().__init__(timeout=120)
        self.leader_id = leader_id
        self.raid_name = raid_name
        self.difficulty = difficulty
        self.forum_channel_id = forum_channel_id
        options = [
            discord.SelectOption(label=p, description=desc, value=p)
            for p, desc in PROFICIENCY.items()
        ]
        sel = Select(placeholder="공격대 숙련도를 선택하세요", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.leader_id:
            await interaction.response.send_message("파티장만 설정할 수 있습니다.", ephemeral=True)
            return
        proficiency = interaction.data["values"][0]
        await interaction.response.send_modal(
            ScheduleModal(self.leader_id, self.raid_name, self.difficulty, proficiency, self.forum_channel_id)
        )


class ScheduleModal(Modal, title="모집 일정 설정"):
    date_input = TextInput(
        label="날짜 (YYYY/MM/DD)",
        placeholder="예) 2026/05/06",
        min_length=10,
        max_length=10,
    )
    time_input = TextInput(
        label="시간 (HH:MM, 24시간)",
        placeholder="예) 20:00",
        min_length=4,
        max_length=5,
    )

    def __init__(self, leader_id: str, raid_name: str, difficulty: str, proficiency: str, forum_channel_id: str) -> None:
        super().__init__()
        self.leader_id = leader_id
        self.raid_name = raid_name
        self.difficulty = difficulty
        self.proficiency = proficiency
        self.forum_channel_id = forum_channel_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        date_str = self.date_input.value.strip()
        time_str = self.time_input.value.strip()

        try:
            dt_kst = datetime.strptime(
                f"{date_str} {time_str}", "%Y/%m/%d %H:%M"
            ).replace(tzinfo=KST)
        except ValueError:
            await interaction.response.send_message(
                "날짜/시간 형식이 올바르지 않습니다.\n"
                "날짜: `2026/05/06` / 시간: `20:00` 형식으로 입력해주세요.",
                ephemeral=True,
            )
            return

        if dt_kst < datetime.now(KST):
            await interaction.response.send_message(
                "과거 날짜로는 모집할 수 없습니다. 날짜를 다시 확인해주세요.",
                ephemeral=True,
            )
            return

        # 사람이 읽기 편한 표시용 문자열 (12시간제)
        hour = dt_kst.hour
        ampm = "오전" if hour < 12 else "오후"
        display_hour = hour if hour <= 12 else hour - 12
        if display_hour == 0:
            display_hour = 12
        scheduled_time = f"{dt_kst.year}/{dt_kst.month:02d}/{dt_kst.day:02d} {ampm} {display_hour}시 {dt_kst.minute:02d}분"
        if dt_kst.minute == 0:
            scheduled_time = f"{dt_kst.year}/{dt_kst.month:02d}/{dt_kst.day:02d} {ampm} {display_hour}시 정각"

        await _post_party(
            interaction, self.raid_name, self.difficulty, self.proficiency,
            scheduled_time, dt_kst.isoformat(), self.forum_channel_id
        )


async def _post_party(
    interaction: discord.Interaction,
    raid_name: str,
    difficulty: str,
    proficiency: str,
    scheduled_time: str,
    scheduled_datetime: str | None = None,
    forum_channel_id: str | None = None,
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
        total_slots=total_slots, min_level=min_level,
    )

    # 실제 message_id 기반 embed 갱신
    party = await db.get_party(str(starter_msg.id))
    await starter_msg.edit(embed=party_embed(party, []), view=view)


# ─────────────────────────────────────────────────────
# 공대 모집 — 참여 기반 View
# ─────────────────────────────────────────────────────

class PartyView(View):
    """버튼 4개(참여하기 / 나가기 / 모집 마감 / 클리어) 기반 공대 뷰."""

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

        disband_btn = Button(
            label="모집 마감", emoji="🔒",
            style=discord.ButtonStyle.danger,
            custom_id="party:disband",
            disabled=closed,
            row=0,
        )
        disband_btn.callback = self._handle_disband
        self.add_item(disband_btn)

        clear_btn = Button(
            label="클리어", emoji="🏆",
            style=discord.ButtonStyle.success,
            custom_id="party:clear",
            row=0,
        )
        clear_btn.callback = self._handle_clear
        self.add_item(clear_btn)

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

        slots = await db.get_party_slots(message_id)
        if any(s["discord_id"] == discord_id for s in slots):
            await interaction.response.send_message("이미 파티에 참여 중입니다.", ephemeral=True)
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
        cached    = await db.get_cached_characters(discord_id)
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

        # 골드 완료 캐릭터 필터링 (같은 레이드 어떤 난이도든 클리어 시 제외)
        gold_done: list[str] = []
        filtered = []
        for q in qualifying:
            completions = await db.get_completions(discord_id, q["name"])
            if any(k.startswith(f"{party['raid_name']}_") for k in completions):
                gold_done.append(f"**{q['name']}**")
            else:
                filtered.append(q)
        qualifying = filtered

        if not qualifying:
            lines: list[str] = []
            if gold_done:
                lines.append(f"🏆 이번 주 골드 완료: {', '.join(gold_done)}")
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
            else:
                view = RoleSelectView(discord_id, q, message_id, party["total_slots"], self)
                await interaction.response.send_message(
                    f"**{q['name']}** ({q['class']}) — 역할을 선택하세요:",
                    view=view, ephemeral=True,
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

        await self._refresh_party(interaction.message, was_full=was_full)

    # ── 모집 종료 ───────────────────────────────────

    async def _handle_disband(self, interaction: discord.Interaction) -> None:
        party = await db.get_party_by_channel(str(interaction.channel.id))
        if not party:
            await interaction.response.send_message("유효하지 않은 파티입니다.", ephemeral=True)
            return
        if party["leader_id"] != str(interaction.user.id):
            await interaction.response.send_message("파티장만 모집을 마감할 수 있습니다.", ephemeral=True)
            return
        if party["status"] == "closed":
            await interaction.response.send_message("이미 모집이 마감된 파티입니다.", ephemeral=True)
            return
        if party["status"] == "disbanded":
            await interaction.response.send_message("이미 종료된 파티입니다.", ephemeral=True)
            return
        message_id = party["message_id"]
        await db.close_party(message_id)
        party["status"] = "closed"
        slots = await db.get_party_slots(message_id)
        from bot.ui.embeds import party_embed
        embed = party_embed(party, slots)
        closed_view = PartyView(total_slots=self.total_slots, closed=True)
        await interaction.response.edit_message(embed=embed, view=closed_view)
        try:
            await interaction.channel.edit(locked=True)
        except discord.HTTPException:
            pass

    # ── 클리어 ─────────────────────────────────────

    async def _handle_clear(self, interaction: discord.Interaction) -> None:
        party = await db.get_party_by_channel(str(interaction.channel.id))
        if not party:
            await interaction.response.send_message("유효하지 않은 파티입니다.", ephemeral=True)
            return
        if party["leader_id"] != str(interaction.user.id):
            await interaction.response.send_message("파티장만 클리어 처리할 수 있습니다.", ephemeral=True)
            return
        if party["status"] == "disbanded":
            await interaction.response.send_message("이미 종료된 파티입니다.", ephemeral=True)
            return
        if party["status"] not in ("recruiting", "full", "closed"):
            await interaction.response.send_message("유효하지 않은 파티 상태입니다.", ephemeral=True)
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
        await interaction.response.edit_message(embed=party_embed(party, slots), view=None)

        raid_title = f"{party['raid_name']} {party['difficulty']}"
        mentions   = " ".join(f"<@{s['discord_id']}>" for s in slots)
        await interaction.channel.send(
            f"🏆 **{raid_title}** 클리어!\n"
            f"{mentions}\n"
            f"파티원 **{count}명**의 레이드 체크가 자동 완료되었습니다."
        )
        try:
            await interaction.channel.edit(archived=True, locked=True)
        except discord.HTTPException:
            pass

    # ── 공통 갱신 ───────────────────────────────────

    async def _refresh_party(self, message: discord.Message, *, was_full: bool = False) -> None:
        party = await db.get_party_by_channel(str(message.channel.id))
        if not party:
            return
        slots = await db.get_party_slots(party["message_id"])

        from bot.ui.embeds import party_embed
        embed = party_embed(party, slots)
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
        else:
            view = RoleSelectView(self.discord_id, char_info, self.message_id, self.total_slots, self.party_view)
            await interaction.response.edit_message(
                content=f"**{char_name}** ({char_info['class']}) — 역할을 선택하세요:",
                view=view,
            )
        try:
            view.message = await interaction.original_response()
        except discord.HTTPException:
            pass


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
            try:
                msg = await interaction.channel.fetch_message(int(self.message_id))
                await self.party_view._refresh_party(msg)
            except discord.HTTPException:
                pass
        return cb
