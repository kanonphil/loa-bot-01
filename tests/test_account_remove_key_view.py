"""회귀 테스트: /api삭제에서 계정(부계정)이 2개 이상일 때 RemoveApiKeySelectView를
생성하면 discord.ui.Select를 사용하는데, bot/cogs/account.py의 import에 Select가
빠져 있어 NameError로 크래시하던 버그."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

from bot.cogs.account import RemoveApiKeySelectView


def test_remove_api_key_select_view_constructs_without_nameerror():
    accounts = [
        {"id": 1, "label": "본캐", "added_at": "2026-01-01"},
        {"id": 2, "label": "부캐", "added_at": "2026-01-02"},
    ]
    view = RemoveApiKeySelectView("111", accounts)
    assert len(view.children) == 1
