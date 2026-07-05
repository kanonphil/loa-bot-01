"""
유저별 로스트아크 API 키 등록 및 관리
"""
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Modal, TextInput, View, Button

import bot.database.manager as db
from bot.cogs.guide import send_guide
from bot.services.expedition import verify_and_register_api_key


class CharRegisterView(View):
    """API 등록 완료 후 캐릭터 등록 방식 선택."""

    def __init__(
        self, discord_id: str, verified_name: str, siblings: list[dict],
        api_key_id: int | None = None,
    ) -> None:
        super().__init__(timeout=60)
        self.discord_id    = discord_id
        self.verified_name = verified_name
        self.siblings      = siblings
        self.api_key_id    = api_key_id

    async def _finish(self, interaction: discord.Interaction, header: str) -> None:
        await interaction.response.edit_message(content=header, view=None)
        await send_guide(interaction.followup.send)

    @discord.ui.button(label="이 캐릭터만 등록", style=discord.ButtonStyle.secondary, emoji="👤")
    async def register_one(self, interaction: discord.Interaction, button: Button) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
            return
        await db.add_character(self.discord_id, self.verified_name, api_key_id=self.api_key_id)
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
        added = 0
        for char in self.siblings:
            name = char.get("CharacterName")
            if name and await db.add_character(self.discord_id, name, api_key_id=self.api_key_id):
                added += 1
        self.stop()
        await self._finish(
            interaction,
            f"✅ 원정대 캐릭터 **{added}개** 전체가 등록되었습니다.\n\n"
            f"📖 아래 가이드를 따라 시작해보세요!",
        )

    async def on_timeout(self) -> None:
        # 타임아웃 시 검증 캐릭터만 등록
        await db.add_character(self.discord_id, self.verified_name, api_key_id=self.api_key_id)


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

        success, message, siblings, api_key_id = await verify_and_register_api_key(
            self.discord_id, key, name
        )
        if not success:
            await interaction.followup.send(message, ephemeral=True)
            return

        # 캐릭터 등록 방식 선택 (1개 vs 전체)
        view = CharRegisterView(self.discord_id, name, siblings, api_key_id=api_key_id)
        await interaction.followup.send(message, view=view, ephemeral=True)


def _mask_key(key: str) -> str:
    return key[:8] + "****" + key[-4:] if len(key) > 12 else "****"


class RemoveApiKeySelectView(View):
    """등록된 계정이 여러 개일 때 삭제할 계정을 고르는 선택 메뉴."""

    def __init__(self, discord_id: str, accounts: list[dict]) -> None:
        super().__init__(timeout=60)
        self.discord_id = discord_id
        options = [
            discord.SelectOption(label=acc["label"], value=str(acc["id"]))
            for acc in accounts[:25]
        ]
        sel = Select(placeholder="삭제할 계정을 선택하세요", options=options)
        sel.callback = self._on_select
        self.add_item(sel)

    async def _on_select(self, interaction: discord.Interaction) -> None:
        if str(interaction.user.id) != self.discord_id:
            await interaction.response.send_message("본인만 선택할 수 있습니다.", ephemeral=True)
            return
        key_id = int(interaction.data["values"][0])
        removed = await db.remove_user_api_key(self.discord_id, key_id)
        msg = "🗑️ 선택한 계정이 삭제되었습니다." if removed else "계정을 찾을 수 없습니다."
        await interaction.response.edit_message(content=msg, view=None)
        self.stop()


class Account(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="api등록", description="로스트아크 API 키를 등록합니다. 이미 등록되어 있다면 부계정으로 추가 등록됩니다.")
    async def register_api(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(ApiKeyModal(str(interaction.user.id)))

    @app_commands.command(name="api확인", description="현재 등록된 API 키(계정) 목록을 확인합니다.")
    async def check_api(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        accounts = await db.list_user_api_keys(discord_id)
        if not accounts:
            await interaction.response.send_message(
                "등록된 API 키가 없습니다.\n`/api등록` 명령어로 등록해주세요.\n\n"
                "🔗 API 키 발급: https://developer-lostark.game.onstove.com",
                ephemeral=True,
            )
            return

        lines = ["✅ 등록된 계정 목록:"]
        for acc in accounts:
            key = await db.get_user_api_key_by_id(acc["id"])
            masked = _mask_key(key) if key else "****"
            lines.append(f"- **{acc['label']}** — `{masked}`")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @app_commands.command(name="api삭제", description="등록된 API 키(계정)를 삭제합니다.")
    async def delete_api(self, interaction: discord.Interaction) -> None:
        discord_id = str(interaction.user.id)
        accounts = await db.list_user_api_keys(discord_id)
        if not accounts:
            await interaction.response.send_message("등록된 API 키가 없습니다.", ephemeral=True)
            return

        if len(accounts) == 1:
            # 계정이 하나뿐이면 기존과 동일하게 바로 삭제 (선택 메뉴로 번거롭게 하지 않음)
            await db.remove_user_api_key(discord_id, accounts[0]["id"])
            await interaction.response.send_message("🗑️ API 키가 삭제되었습니다.", ephemeral=True)
            return

        view = RemoveApiKeySelectView(discord_id, accounts)
        await interaction.response.send_message(
            "삭제할 계정을 선택해주세요.", view=view, ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Account(bot))
