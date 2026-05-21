"""
/가이드 — 봇 사용법 안내
텍스트 embed와 이미지를 교차 전송하는 구조.
bot/assets/guide/ 폴더에 PNG 파일이 있으면 이미지 첨부, 없으면 텍스트만 표시.
"""
import os
import discord
from discord import app_commands
from discord.ext import commands

_GUIDE_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "guide")

# ─────────────────────────────────────────────────────
# 가이드 정의
# 각 항목: {"title", "color", "text", "image"}
#   image: assets/guide/ 내 파일명 (없으면 None)
#   color: 0x... hex (기본 인디고, 경고는 주황)
# ─────────────────────────────────────────────────────

_STEPS = [
    {
        "title": "🔑 API 키 발급",
        "color": 0x5865F2,
        "text": (
            "아래 사이트에서 API 키를 발급받으세요.\n"
            "https://developer-lostark.game.onstove.com\n\n"
            "**발급 순서**\n"
            "① 로그인\n"
            "② 우측 상단 **[내 정보]** → **[API Key 관리]**\n"
            "③ **[생성하기]** 버튼 클릭"
        ),
        "image": "guide_01_site.png",
    },
    {
        "title": "⚠️ 자동 번역 반드시 끄세요!",
        "color": 0xE67E22,
        "text": (
            "크롬·웨일 등 브라우저의 **자동 번역**이 켜져 있으면\n"
            "API 키가 한글로 변환되어 **등록이 실패**합니다.\n\n"
            "**해결 방법**\n"
            "주소창 옆 번역 아이콘 🌐 클릭 →\n"
            "**[영어 원문 표시]** 또는 **[이 사이트는 번역 안 함]** 선택\n\n"
            "번역을 끈 뒤 페이지를 새로고침하고 API 키를 다시 복사하세요."
        ),
        "image": "guide_02_translation.png",
    },
    {
        "title": "📝 API 키 등록",
        "color": 0x5865F2,
        "text": (
            "`/api등록` 명령어를 입력하면 창이 열립니다.\n\n"
            "**입력 항목**\n"
            "• **API 키** — 발급받은 키를 그대로 붙여넣기\n"
            "• **캐릭터 이름** — 내 캐릭터 이름 아무거나\n\n"
            "등록이 완료되면 원정대 캐릭터 **전체가 자동 등록**됩니다."
        ),
        "image": "guide_03_register.png",
    },
    {
        "title": "⚔️ 원정대 확인",
        "color": 0x2ECC71,
        "text": (
            "`/원정대` 명령어로 등록된 캐릭터 목록을 확인하세요.\n"
            "아이템 레벨과 직업 클래스가 표시됩니다.\n\n"
            "**캐릭터 관리**\n"
            "• `/캐릭터등록` — 원정대에 캐릭터 추가\n"
            "• `/캐릭터삭제` — 원정대에서 캐릭터 제거"
        ),
        "image": "guide_04_expedition.png",
    },
    {
        "title": "👥 공대 참여하기",
        "color": 0x2ECC71,
        "text": (
            "① `/공대확인` 명령어로 모집 중인 공대 목록 확인\n"
            "② 원하는 공대 스레드 클릭\n"
            "③ **[참여하기]** 버튼 → 캐릭터 선택 → 역할 선택 → 완료!\n\n"
            "• `/내공대` — 내가 참여 중인 공대 목록\n"
            "• `/공대모집` — 내 공대 직접 열기"
        ),
        "image": "guide_05_party.png",
    },
    {
        "title": "🔔 새 공대 알림 구독",
        "color": 0xF1C40F,
        "text": (
            "원하는 레이드+난이도를 구독하면\n"
            "새 공대가 열릴 때 **DM으로 자동 알림**을 받습니다.\n\n"
            "• `/레이드구독` — 구독 설정\n"
            "• `/구독목록` — 현재 구독 목록\n"
            "• `/구독취소` — 구독 해제"
        ),
        "image": "guide_06_subscription.png",
    },
    {
        "title": "✅ 주간 레이드 체크",
        "color": 0x1ABC9C,
        "text": (
            "`/레이드체크` 명령어로 이번 주 클리어 현황을 확인하고\n"
            "버튼으로 직접 체크·해제할 수 있습니다.\n\n"
            "공대 클리어 처리 시 자동으로 체크됩니다.\n"
            "매주 **수요일 06:00**에 자동 초기화됩니다."
        ),
        "image": "guide_07_checklist.png",
    },
]


def _file(filename: str) -> discord.File | None:
    path = os.path.join(_GUIDE_DIR, filename)
    return discord.File(path, filename=filename) if os.path.isfile(path) else None


async def send_guide(
    send_fn,
    *,
    header: str | None = None,
    ephemeral: bool = True,
) -> None:
    """가이드를 순서대로 전송한다.

    send_fn: `await send_fn(content=..., embed=..., file=..., ephemeral=...)` 형태의 callable
             (interaction.followup.send 또는 channel.send 등)
    header:  첫 메시지 앞에 붙일 텍스트 (None이면 생략)
    """
    if header:
        await send_fn(content=header, ephemeral=ephemeral)

    for step in _STEPS:
        embed = discord.Embed(
            title=step["title"],
            description=step["text"],
            color=step["color"],
        )
        f = _file(step["image"]) if step.get("image") else None
        if f:
            embed.set_image(url=f"attachment://{step['image']}")
            await send_fn(embed=embed, file=f, ephemeral=ephemeral)
        else:
            await send_fn(embed=embed, ephemeral=ephemeral)


class Guide(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="가이드", description="봇 사용법을 단계별로 안내합니다.")
    async def guide(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_guide(
            interaction.followup.send,
            header="📖 **봇 사용 가이드**\n아래 순서대로 따라오시면 됩니다!",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Guide(bot))
