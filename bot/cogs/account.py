"""
유저별 로스트아크 API 키 등록 및 관리
"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button

import config
import bot.api.lostark as loa
import bot.database.manager as db
from bot.cogs.guide import send_guide


class CharRegisterView(View):
    """API 등록 완료 후 캐릭터 등록 방식 선택."""

    def __init__(self, discord_id: str, verified_name: str, siblings: list[dict]) -> None:
        super().__init__(timeout=60)
        self.discord_id    = discord_id
        self.verified_name = verified_name
        self.siblings      = siblings

    async def _finish(self, interaction: discord.Interaction, header: str) -> None:
        await interaction.response.edit_message(content=header, view=None)
        await send_guide(interaction.followup.send)

    @discord.ui.button(label="이 캐릭터만 등록", style=discord.ButtonStyle.secondary, emoji="👤")
    async def register_one(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
            return
        await db.add_character(self.discord_id, self.verified_name)
        self.stop()
        await self._finish(
            interaction,
            f"✅ **{self.verified_name}** 캐릭터가 원정대에 등록되었습니다.\n"
            f"나머지 캐릭터는 `/캐릭터등록`으로 추가할 수 있습니다.\n\n"
            f"📖 아래 가이드를 따라 시작해보세요!",
        )

    @discord.ui.button(label="원정대 전체 등록", style=discord.ButtonStyle.primary, emoji="👥")
    async def register_all(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
            return
        added = sum(
            1 for char in self.siblings
            if char.get("CharacterName") and await db.add_character(self.discord_id, char["CharacterName"])
        )
        self.stop()
        await self._finish(
            interaction,
            f"✅ 원정대 캐릭터 **{added}개** 전체가 등록되었습니다.\n\n"
            f"📖 아래 가이드를 따라 시작해보세요!",
        )

    async def on_timeout(self) -> None:
        # 타임아웃 시 검증 캐릭터만 등록
        await db.add_character(self.discord_id, self.verified_name)


async def verify_and_register_api_key(
    discord_id: str, key: str, name: str
) -> tuple[bool, str, list[dict] | None]:
    """API 키 검증 + 길드 확인 + 저장까지 처리.
    (성공 여부, 유저에게 보낼 메시지, 원정대 캐릭터 목록) 반환.
    discord.Interaction 없이 동작해서 단위 테스트하기 쉽다."""
    try:
        siblings = await loa.get_siblings(key, name)
    except RuntimeError as e:
        return False, f"❌ API 키 검증 실패: {e}", None

    if siblings is None:
        # 캐릭터를 못 찾았지만 API 키는 유효할 수 있음 (404)
        # 401이었으면 RuntimeError가 발생했을 것
        return False, (
            f"⚠️ API 키는 유효하지만 **{name}** 캐릭터를 찾을 수 없습니다.\n"
            "캐릭터 이름을 다시 확인한 뒤 재시도해주세요.\n\n"
            "API 키는 저장되지 않았습니다."
        ), None

    # 길드 확인 — 실제 "동물롱장" 소속만 등록 허용 (디스코드 서버엔 길드원 아닌 인원도 있음)
    if config.REQUIRED_GUILD_NAME:
        try:
            armory = await loa.get_armory(key, name)
        except RuntimeError as e:
            return False, f"❌ 길드 확인 중 오류: {e}", None
        profile = (armory or {}).get("ArmoryProfile") or {}
        guild_name = profile.get("GuildName") or ""
        if guild_name != config.REQUIRED_GUILD_NAME:
            detail = f" (현재: {guild_name})" if guild_name else " (길드 미가입)"
            return False, (
                f"❌ **{name}** 캐릭터는 **{config.REQUIRED_GUILD_NAME}** 길드 소속이 아닙니다{detail}.\n"
                "API 키는 저장되지 않았습니다."
            ), None

    await db.set_user_api_key(discord_id, key)
    return True, (
        f"✅ **API 키 등록 완료!** (원정대 캐릭터 **{len(siblings)}개** 확인)\n\n"
        f"원정대에 등록할 캐릭터를 선택하세요:"
    ), siblings


class ApiKeyModal(Modal, title="로스트아크 API 키 등록"):
    api_key = TextInput(
        label="API 키",
        placeholder="developer-lostark.game.onstove.com 에서 발급된 키",
        min_length=10,
        max_length=1024,
        style=discord.TextStyle.paragraph,
    )
    character_name = TextInput(
        label="검증용 캐릭터 이름",
        placeholder="내 캐릭터 이름 (API 키 유효성 확인에 사용)",
        min_length=2,
        max_length=12,
    )

    def __init__(self, discord_id: str) -> None:
        super().__init__()
        self.discord_id = discord_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        key  = self.api_key.value.strip()
        name = self.character_name.value.strip()

        await interaction.response.defer(ephemeral=True, thinking=True)

        success, message, siblings = await verify_and_register_api_key(self.discord_id, key, name)
        if not success:
            await interaction.followup.send(message, ephemeral=True)
            return

        # 캐릭터 등록 방식 선택 (1개 vs 전체)
        view = CharRegisterView(self.discord_id, name, siblings)
        await interaction.followup.send(message, view=view, ephemeral=True)


class Account(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="api등록", description="로스트아크 API 키를 등록합니다. 캐릭터 조회에 사용됩니다.")
    async def register_api(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ApiKeyModal(str(interaction.user.id)))

    @app_commands.command(name="api확인", description="현재 등록된 API 키 상태를 확인합니다.")
    async def check_api(self, interaction: discord.Interaction) -> None:
        key = await db.get_user_api_key(str(interaction.user.id))
        if not key:
            await interaction.response.send_message(
                "등록된 API 키가 없습니다.\n`/api등록` 명령어로 등록해주세요.\n\n"
                "🔗 API 키 발급: https://developer-lostark.game.onstove.com",
                ephemeral=True,
            )
        else:
            # 키 일부 마스킹
            masked = key[:8] + "****" + key[-4:] if len(key) > 12 else "****"
            await interaction.response.send_message(
                f"✅ API 키가 등록되어 있습니다.\n`{masked}`",
                ephemeral=True,
            )

    @app_commands.command(name="api삭제", description="등록된 API 키를 삭제합니다.")
    async def delete_api(self, interaction: discord.Interaction) -> None:
        key = await db.get_user_api_key(str(interaction.user.id))
        if not key:
            await interaction.response.send_message("등록된 API 키가 없습니다.", ephemeral=True)
            return

        await db.delete_user(str(interaction.user.id))
        await interaction.response.send_message("🗑️ API 키가 삭제되었습니다.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Account(bot))
