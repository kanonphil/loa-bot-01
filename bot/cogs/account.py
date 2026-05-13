"""
유저별 로스트아크 API 키 등록 및 관리
"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput

import bot.api.lostark as loa
import bot.database.manager as db


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

        # API 키 검증
        try:
            siblings = await loa.get_siblings(key, name)
        except RuntimeError as e:
            await interaction.followup.send(
                f"❌ API 키 검증 실패: {e}", ephemeral=True
            )
            return

        if siblings is None:
            # 캐릭터를 못 찾았지만 API 키는 유효할 수 있음 (404)
            # 401이었으면 RuntimeError가 발생했을 것
            await interaction.followup.send(
                f"⚠️ API 키는 유효하지만 **{name}** 캐릭터를 찾을 수 없습니다.\n"
                "캐릭터 이름을 다시 확인한 뒤 재시도해주세요.\n\n"
                "API 키는 저장되지 않았습니다.",
                ephemeral=True,
            )
            return

        # 저장
        await db.set_user_api_key(self.discord_id, key)

        # 원정대 전체 캐릭터 수
        char_count = len(siblings)

        # 검증에 사용한 캐릭터 자동 등록 여부 확인
        await db.add_character(self.discord_id, name)  # 이미 있으면 무시됨

        await interaction.followup.send(
            f"✅ **API 키 등록 완료!**\n\n"
            f"원정대 캐릭터 **{char_count}**개 확인 완료.\n"
            f"**{name}** 캐릭터가 원정대에 자동 등록되었습니다.\n\n"
            f"`/원정대` 명령어로 원정대를 관리하세요.",
            ephemeral=True,
        )


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
