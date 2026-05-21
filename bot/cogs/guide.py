"""
/가이드 — 봇 사용법 안내
모든 단계를 embed 배열로 묶어 메시지 1개로 전송.
bot/assets/guide/ 폴더에 PNG 파일이 있으면 이미지도 같이 첨부.
"""
import os
import discord
from discord import app_commands
from discord.ext import commands

_GUIDE_DIR = os.path.join(os.path.dirname(__file__), "..", "assets", "guide")

# ─────────────────────────────────────────────────────
# 가이드 단계 정의
# image: assets/guide/ 내 파일명 (파일 없으면 이미지 생략)
# ─────────────────────────────────────────────────────

_STEPS = [
    {
        "title": "STEP 1 ·  API 키 발급 및 등록",
        "color": 0x5865F2,
        "text": (
            "**① 아래 사이트에서 API 키를 발급받으세요**\n"
            "https://developer-lostark.game.onstove.com\n"
            "로그인 → **[내 정보]** → **[API Key 관리]** → **[생성하기]**\n\n"
            "⚠️ **자동 번역을 반드시 꺼주세요!**\n"
            "크롬·웨일 등의 자동 번역이 켜져 있으면 API 키가 한글로 변환되어 등록에 실패합니다.\n"
            "주소창 옆 번역 아이콘 클릭 → **[영어 원문 표시]** 선택 후 페이지 새로고침\n\n"
            "**② `/api등록` 명령어로 키를 등록하세요**\n"
            "• **API 키** — 발급받은 키 그대로 붙여넣기\n"
            "• **캐릭터 이름** — API 키 검증용 (본인 캐릭터 아무거나)\n\n"
            "등록 완료 후 **이 캐릭터만 등록** 또는 **원정대 전체 등록** 중 선택할 수 있습니다."
        ),
        "image": "guide_01_api.png",
    },
    {
        "title": "STEP 2 · 원정대 캐릭터 등록",
        "color": 0x2ECC71,
        "text": (
            "`/원정대` 명령어로 등록된 캐릭터 목록과 아이템 레벨을 확인하세요.\n\n"
            "**캐릭터가 빠졌거나 추가하고 싶다면**\n"
            "• `/캐릭터등록` — 원정대에 캐릭터 추가\n"
            "• `/캐릭터삭제` — 원정대에서 캐릭터 제거\n\n"
            "공대 참여 시 여기 등록된 캐릭터 목록에서 선택하게 됩니다."
        ),
        "image": "guide_02_expedition.png",
    },
    {
        "title": "STEP 3 · 공대 모집하기",
        "color": 0x9B59B6,
        "text": (
            "`/공대모집` 명령어로 직접 공대를 열 수 있습니다.\n\n"
            "**설정 순서**\n"
            "① 레이드 선택\n"
            "② 난이도 선택\n"
            "③ 숙련도 선택 (숙련 / 반숙 / 트라이)\n"
            "④ 일정 입력 (날짜·시간)\n"
            "⑤ 메모 입력 (선택)\n\n"
            "설정 완료 후 공대 포럼에 모집 게시물이 자동으로 올라갑니다.\n"
            "게시물에서 **[관리]** 버튼으로 파티원 초대·강제퇴장·일정변경 등을 할 수 있습니다."
        ),
        "image": "guide_03_recruit.png",
    },
    {
        "title": "STEP 4 · 공대 참여하기",
        "color": 0x2ECC71,
        "text": (
            "① `/공대확인` 명령어로 현재 모집 중인 공대 목록 확인\n"
            "② 원하는 공대 스레드로 이동\n"
            "③ **[참여하기]** 버튼 클릭\n"
            "④ 참여할 캐릭터 선택 → 역할(딜러/서포터) 선택 → 완료!\n\n"
            "• `/내공대` — 내가 참여 중인 공대 목록 확인\n"
            "• `/공대확인` 결과에서 **[→ 공대 게시물 바로가기]** 링크로 이동 가능"
        ),
        "image": "guide_04_party.png",
    },
    {
        "title": "STEP 5 · 새 공대 알림 구독",
        "color": 0xF1C40F,
        "text": (
            "원하는 레이드+난이도를 구독하면\n"
            "새 공대가 열릴 때 **DM으로 자동 알림**을 받습니다.\n\n"
            "• `/레이드구독` — 구독 설정\n"
            "• `/구독목록` — 현재 구독 중인 목록\n"
            "• `/구독취소` — 구독 해제\n\n"
            "이미 해당 레이드 공대에 참여 중이면 알림이 오지 않습니다."
        ),
        "image": "guide_05_subscription.png",
    },
    {
        "title": "STEP 6 · 주간 레이드 체크",
        "color": 0x1ABC9C,
        "text": (
            "`/레이드체크` 명령어로 이번 주 클리어 현황을 확인하고\n"
            "버튼으로 직접 체크·해제할 수 있습니다.\n\n"
            "공대 클리어 처리 시 자동으로 체크됩니다.\n"
            "매주 **수요일 06:00**에 자동 초기화됩니다."
        ),
        "image": "guide_06_checklist.png",
    },
]


def _load_file(filename: str) -> discord.File | None:
    path = os.path.join(_GUIDE_DIR, filename)
    return discord.File(path, filename=filename) if os.path.isfile(path) else None


async def send_guide(send_fn, *, header: str | None = None, ephemeral: bool = True) -> None:
    """모든 단계를 embed 배열로 묶어 메시지 1개로 전송.

    이미지가 있는 경우 files 배열에 함께 첨부.
    send_fn: interaction.followup.send 또는 channel.send
    """
    embeds: list[discord.Embed] = []
    files:  list[discord.File]  = []

    for step in _STEPS:
        embed = discord.Embed(
            title=step["title"],
            description=step["text"],
            color=step["color"],
        )
        if step.get("image"):
            f = _load_file(step["image"])
            if f:
                embed.set_image(url=f"attachment://{step['image']}")
                files.append(f)
        embeds.append(embed)

    kwargs: dict = {"embeds": embeds, "ephemeral": ephemeral}
    if header:
        kwargs["content"] = header
    if files:
        kwargs["files"] = files

    await send_fn(**kwargs)


class Guide(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="가이드", description="봇 사용법을 단계별로 안내합니다.")
    async def guide(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        await send_guide(
            interaction.followup.send,
            header="📖 **봇 사용 가이드** — 아래 순서대로 따라오시면 됩니다!",
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Guide(bot))
