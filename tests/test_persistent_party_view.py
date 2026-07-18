"""회귀 테스트: PartyView는 discord.py의 persistent view 요건(모든 컴포넌트에 고정
custom_id + timeout=None)을 만족해야 한다. bot.bot.LoABot.setup_hook이 재시작 시
self.add_view(PartyView(...))로 이를 전역 등록해서, _restore_party_views의 메시지
edit이 실패한 파티라도 버튼 클릭은 계속 받아낼 수 있게 한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import discord

from bot.ui.views import PartyView


def test_party_view_is_persistent():
    view = PartyView(total_slots=8)
    assert view.is_persistent()
    assert view.timeout is None
    custom_ids = {item.custom_id for item in view.children}
    assert custom_ids == {
        "party:join", "party:leave", "party:waitlist", "party:manage", "party:switch",
    }


def test_add_view_registers_without_error():
    client = discord.Client(intents=discord.Intents.default())
    client.add_view(PartyView(total_slots=8))
    # 등록 후에도 새 PartyView 인스턴스를 정상적으로 만들 수 있어야 한다
    # (persistent_views 스토어와 무관하게 매 embed 갱신마다 새 View를 만들기 때문).
    assert PartyView(total_slots=4, closed=True).is_persistent()
