from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput

import bot.database.manager as db
from bot.data import raids as raids_module
from bot.ui.views import _parse_schedule, _format_schedule


# ── 소유자 체크 헬퍼 ─────────────────────────────────────

async def _check_owner(interaction: discord.Interaction) -> bool:
    if not await interaction.client.is_owner(interaction.user):
        await interaction.response.send_message(
            "봇 소유자만 사용할 수 있습니다.", ephemeral=True
        )
        return False
    return True


# ── 자동완성 ─────────────────────────────────────────────

async def _category_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    cats = await db.get_categories()
    return [
        app_commands.Choice(name=c["name"], value=c["name"])
        for c in cats if current.lower() in c["name"].lower()
    ][:25]


async def _raid_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    return [
        app_commands.Choice(name=name, value=name)
        for name in raids_module.RAIDS
        if current.lower() in name.lower()
    ][:25]


async def _difficulty_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    raid_name = interaction.namespace.레이드명 or ""
    raid = raids_module.RAIDS.get(raid_name, {})
    diffs = list(raid.get("difficulties", {}).keys())
    return [
        app_commands.Choice(name=d, value=d)
        for d in diffs if current.lower() in d.lower()
    ][:25]


async def _class_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    classes = await db.get_all_job_classes()
    return [
        app_commands.Choice(name=c["name"], value=c["name"])
        for c in classes if current.lower() in c["name"].lower()
    ][:25]


# ── 레이드 기간 설정 Modal ────────────────────────────────

class RaidPeriodModal(Modal, title="운영 기간 설정"):
    from_date  = TextInput(label="시작 날짜", placeholder="예) 0514  /  20260514", min_length=3, max_length=10)
    from_time  = TextInput(label="시작 시간", placeholder="예) 0600  /  06:00",    min_length=1, max_length=5)
    until_date = TextInput(label="종료 날짜", placeholder="예) 0613  /  20260613", min_length=3, max_length=10)
    until_time = TextInput(label="종료 시간", placeholder="예) 0600  /  06:00",    min_length=1, max_length=5)

    def __init__(self, raid_name: str) -> None:
        super().__init__()
        self.raid_name = raid_name

    async def on_submit(self, interaction: discord.Interaction) -> None:
        from_dt  = _parse_schedule(self.from_date.value,  self.from_time.value)
        until_dt = _parse_schedule(self.until_date.value, self.until_time.value)

        if from_dt is None or until_dt is None:
            await interaction.response.send_message(
                "❌ 날짜/시간 형식이 올바르지 않습니다.\n"
                "날짜: `0514` `20260514` / 시간: `0600` `06:00`",
                ephemeral=True,
            )
            return
        if from_dt >= until_dt:
            await interaction.response.send_message(
                "❌ 시작 시각이 종료 시각보다 늦습니다.", ephemeral=True
            )
            return

        await db.set_raid_period(self.raid_name, from_dt.isoformat(), until_dt.isoformat())
        await raids_module.reload()

        fmt = "%Y/%m/%d %H:%M"
        await interaction.response.send_message(
            f"✅ **{self.raid_name}** 운영 기간 설정 완료.\n"
            f"`{from_dt.strftime(fmt)}` ~ `{until_dt.strftime(fmt)}`",
            ephemeral=True,
        )


# ── 레이드 추가 Modal ────────────────────────────────────

class AddRaidModal(Modal, title="레이드 추가"):
    name_input     = TextInput(label="레이드명",         placeholder="예) 에기르(1막)", max_length=50)
    short_input    = TextInput(label="약칭",             placeholder="예) 1막",         max_length=20)
    icon_input     = TextInput(label="아이콘 (이모지)",  placeholder="예) 🔥",          max_length=10)
    category_input = TextInput(label="카테고리",         placeholder="예) 카제로스",    max_length=30)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        name     = self.name_input.value.strip()
        short    = self.short_input.value.strip()
        icon     = self.icon_input.value.strip() or "⚔️"
        category = self.category_input.value.strip()

        cats = {c["name"] for c in await db.get_categories()}
        if category not in cats:
            cat_list = ", ".join(sorted(cats)) or "(없음)"
            await interaction.response.send_message(
                f"❌ **{category}** 카테고리가 없습니다.\n"
                f"현재 카테고리: {cat_list}\n\n"
                f"`/관리 카테고리추가`로 먼저 추가해주세요.",
                ephemeral=True,
            )
            return

        added = await db.add_raid(name, short, icon, category)
        if not added:
            await interaction.response.send_message(
                f"❌ **{name}** 레이드가 이미 존재합니다.", ephemeral=True
            )
            return

        await raids_module.reload()
        await interaction.response.send_message(
            f"✅ **{name}** `{icon}` ({category}) 레이드 추가 완료.\n"
            f"`/관리 난이도추가`로 난이도를 추가하세요.",
            ephemeral=True,
        )


# ── Admin 코그 ───────────────────────────────────────────

class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    manage = app_commands.Group(name="관리", description="봇 소유자 전용 데이터 관리")

    # ── 카테고리 ─────────────────────────────────────────

    @manage.command(name="카테고리추가", description="레이드 카테고리를 추가합니다.")
    @app_commands.describe(이름="카테고리명 (예: 카제로스)", 순서="표시 순서 (작을수록 위)")
    async def add_category(self, interaction: discord.Interaction, 이름: str, 순서: int) -> None:
        if not await _check_owner(interaction):
            return
        added = await db.add_category(이름, 순서)
        if not added:
            await interaction.response.send_message(
                f"❌ **{이름}** 카테고리가 이미 존재합니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        await interaction.response.send_message(
            f"✅ 카테고리 **{이름}** (순서 {순서}) 추가 완료.", ephemeral=True
        )

    @manage.command(name="카테고리삭제", description="레이드 카테고리를 삭제합니다.")
    @app_commands.describe(이름="삭제할 카테고리명")
    @app_commands.autocomplete(이름=_category_autocomplete)
    async def del_category(self, interaction: discord.Interaction, 이름: str) -> None:
        if not await _check_owner(interaction):
            return
        raids = await db.get_raids_dict()
        using = [r for r, info in raids.items() if info["category"] == 이름]
        if using:
            await interaction.response.send_message(
                f"❌ 이 카테고리를 사용 중인 레이드가 있습니다: {', '.join(using)}\n"
                f"레이드를 먼저 삭제해주세요.",
                ephemeral=True,
            )
            return
        removed = await db.remove_category(이름)
        if not removed:
            await interaction.response.send_message(
                f"❌ **{이름}** 카테고리를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        await interaction.response.send_message(
            f"🗑️ 카테고리 **{이름}** 삭제 완료.", ephemeral=True
        )

    @manage.command(name="카테고리순서", description="카테고리 표시 순서를 변경합니다.")
    @app_commands.describe(이름="대상 카테고리명", 순서="새 표시 순서")
    @app_commands.autocomplete(이름=_category_autocomplete)
    async def sort_category(self, interaction: discord.Interaction, 이름: str, 순서: int) -> None:
        if not await _check_owner(interaction):
            return
        updated = await db.update_category_sort(이름, 순서)
        if not updated:
            await interaction.response.send_message(
                f"❌ **{이름}** 카테고리를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        await interaction.response.send_message(
            f"✅ **{이름}** 카테고리 순서 → {순서} 변경 완료.", ephemeral=True
        )

    @manage.command(name="카테고리목록", description="현재 카테고리 목록을 확인합니다.")
    async def list_categories(self, interaction: discord.Interaction) -> None:
        if not await _check_owner(interaction):
            return
        cats = await db.get_categories()
        if not cats:
            await interaction.response.send_message("등록된 카테고리가 없습니다.", ephemeral=True)
            return
        lines = [f"`{c['sort_order']}` **{c['name']}**" for c in cats]
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # ── 레이드 ───────────────────────────────────────────

    @manage.command(name="레이드추가", description="새 레이드를 추가합니다.")
    async def add_raid(self, interaction: discord.Interaction) -> None:
        if not await _check_owner(interaction):
            return
        await interaction.response.send_modal(AddRaidModal())

    @manage.command(name="레이드삭제", description="레이드와 모든 난이도를 삭제합니다.")
    @app_commands.describe(레이드명="삭제할 레이드명")
    @app_commands.autocomplete(레이드명=_raid_autocomplete)
    async def del_raid(self, interaction: discord.Interaction, 레이드명: str) -> None:
        if not await _check_owner(interaction):
            return
        removed = await db.remove_raid(레이드명)
        if not removed:
            await interaction.response.send_message(
                f"❌ **{레이드명}** 레이드를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        await interaction.response.send_message(
            f"🗑️ **{레이드명}** 및 모든 난이도 삭제 완료.", ephemeral=True
        )

    # ── 난이도 ───────────────────────────────────────────

    @manage.command(name="난이도추가", description="레이드에 난이도를 추가합니다.")
    @app_commands.describe(
        레이드명="대상 레이드명",
        난이도명="예) 노말, 하드, 나이트메어",
        최소레벨="입장 최소 아이템 레벨",
        인원수="전체 파티원 수 (4 또는 8)",
        파티분할="파티 분할 인원 (없으면 0)",
        관문수="관문 수",
        표시순서="난이도 표시 순서 (작을수록 위)",
    )
    @app_commands.autocomplete(레이드명=_raid_autocomplete)
    async def add_difficulty(
        self,
        interaction: discord.Interaction,
        레이드명: str,
        난이도명: str,
        최소레벨: int,
        인원수: int,
        파티분할: int = 0,
        관문수: int = 1,
        표시순서: int = 0,
    ) -> None:
        if not await _check_owner(interaction):
            return
        if not await db.raid_exists(레이드명):
            await interaction.response.send_message(
                f"❌ **{레이드명}** 레이드가 없습니다. 먼저 `/관리 레이드추가`로 추가해주세요.",
                ephemeral=True,
            )
            return
        split = 파티분할 if 파티분할 > 0 else None
        added = await db.add_difficulty(레이드명, 난이도명, 최소레벨, 인원수, split, 관문수, 표시순서)
        if not added:
            await interaction.response.send_message(
                f"❌ **{레이드명} {난이도명}** 난이도가 이미 존재합니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        split_str = f"{파티분할}인 분할" if 파티분할 > 0 else "단일 파티"
        await interaction.response.send_message(
            f"✅ **{레이드명} {난이도명}** "
            f"(최소 {최소레벨} / {인원수}인 / {split_str} / {관문수}관문) 추가 완료.",
            ephemeral=True,
        )

    @manage.command(name="난이도삭제", description="레이드 난이도를 삭제합니다.")
    @app_commands.describe(레이드명="대상 레이드명", 난이도명="삭제할 난이도명")
    @app_commands.autocomplete(레이드명=_raid_autocomplete, 난이도명=_difficulty_autocomplete)
    async def del_difficulty(
        self, interaction: discord.Interaction, 레이드명: str, 난이도명: str
    ) -> None:
        if not await _check_owner(interaction):
            return
        removed = await db.remove_difficulty(레이드명, 난이도명)
        if not removed:
            await interaction.response.send_message(
                f"❌ **{레이드명} {난이도명}** 난이도를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        await interaction.response.send_message(
            f"🗑️ **{레이드명} {난이도명}** 난이도 삭제 완료.", ephemeral=True
        )

    # ── 익스트림 관리 ──────────────────────────────────────

    @manage.command(name="카테고리익스트림", description="카테고리의 익스트림 여부를 설정합니다.")
    @app_commands.describe(이름="카테고리명", 익스트림="True = 익스트림, False = 일반")
    @app_commands.autocomplete(이름=_category_autocomplete)
    async def set_category_extreme(
        self, interaction: discord.Interaction, 이름: str, 익스트림: bool
    ) -> None:
        if not await _check_owner(interaction):
            return
        updated = await db.update_category_extreme(이름, 익스트림)
        if not updated:
            await interaction.response.send_message(
                f"❌ **{이름}** 카테고리를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        label = "익스트림" if 익스트림 else "일반"
        await interaction.response.send_message(
            f"✅ **{이름}** 카테고리 → {label} 설정 완료.", ephemeral=True
        )

    @manage.command(name="레이드활성화", description="레이드를 활성화하거나 비활성화합니다.")
    @app_commands.describe(레이드명="대상 레이드명", 활성화="True = 활성화, False = 비활성화")
    @app_commands.autocomplete(레이드명=_raid_autocomplete)
    async def set_raid_active(
        self, interaction: discord.Interaction, 레이드명: str, 활성화: bool
    ) -> None:
        if not await _check_owner(interaction):
            return
        updated = await db.set_raid_active(레이드명, 활성화)
        if not updated:
            await interaction.response.send_message(
                f"❌ **{레이드명}** 레이드를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        label = "활성화" if 활성화 else "비활성화"
        await interaction.response.send_message(
            f"✅ **{레이드명}** {label} 완료.", ephemeral=True
        )

    @manage.command(name="레이드기간설정", description="익스트림 레이드 운영 기간을 설정합니다.")
    @app_commands.describe(레이드명="대상 레이드명")
    @app_commands.autocomplete(레이드명=_raid_autocomplete)
    async def set_raid_period(
        self, interaction: discord.Interaction, 레이드명: str
    ) -> None:
        if not await _check_owner(interaction):
            return
        if not await db.raid_exists(레이드명):
            await interaction.response.send_message(
                f"❌ **{레이드명}** 레이드를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await interaction.response.send_modal(RaidPeriodModal(레이드명))

    @manage.command(name="레이드기간삭제", description="익스트림 레이드 운영 기간을 삭제합니다.")
    @app_commands.describe(레이드명="대상 레이드명")
    @app_commands.autocomplete(레이드명=_raid_autocomplete)
    async def clear_raid_period(
        self, interaction: discord.Interaction, 레이드명: str
    ) -> None:
        if not await _check_owner(interaction):
            return
        updated = await db.set_raid_period(레이드명, None, None)
        if not updated:
            await interaction.response.send_message(
                f"❌ **{레이드명}** 레이드를 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        await interaction.response.send_message(
            f"✅ **{레이드명}** 운영 기간 삭제 완료.", ephemeral=True
        )

    # ── 직업 ─────────────────────────────────────────────

    @manage.command(name="직업추가", description="직업을 추가합니다.")
    @app_commands.describe(직업명="직업 이름 (예: 신규직업)", 서포터="서포터 여부")
    async def add_class(
        self, interaction: discord.Interaction, 직업명: str, 서포터: bool
    ) -> None:
        if not await _check_owner(interaction):
            return
        added = await db.add_job_class(직업명, 서포터)
        if not added:
            await interaction.response.send_message(
                f"❌ **{직업명}** 직업이 이미 존재합니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        role = "서포터" if 서포터 else "딜러"
        await interaction.response.send_message(
            f"✅ **{직업명}** ({role}) 직업 추가 완료.", ephemeral=True
        )

    @manage.command(name="직업삭제", description="직업을 삭제합니다.")
    @app_commands.describe(직업명="삭제할 직업 이름")
    @app_commands.autocomplete(직업명=_class_autocomplete)
    async def del_class(self, interaction: discord.Interaction, 직업명: str) -> None:
        if not await _check_owner(interaction):
            return
        removed = await db.remove_job_class(직업명)
        if not removed:
            await interaction.response.send_message(
                f"❌ **{직업명}** 직업을 찾을 수 없습니다.", ephemeral=True
            )
            return
        await raids_module.reload()
        await interaction.response.send_message(
            f"🗑️ **{직업명}** 직업 삭제 완료.", ephemeral=True
        )

    @manage.command(name="직업목록", description="등록된 직업 목록을 확인합니다.")
    async def list_classes(self, interaction: discord.Interaction) -> None:
        if not await _check_owner(interaction):
            return
        classes = await db.get_all_job_classes()
        if not classes:
            await interaction.response.send_message("등록된 직업이 없습니다.", ephemeral=True)
            return
        supports = [c["name"] for c in classes if c["is_support"]]
        dealers  = [c["name"] for c in classes if not c["is_support"]]
        lines = []
        if supports:
            lines.append(f"🛡️ **서포터** ({len(supports)}): {', '.join(supports)}")
        if dealers:
            lines.append(f"⚔️ **딜러** ({len(dealers)}): {', '.join(dealers)}")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Admin(bot))
