"""/캐릭터삭제 자동완성(bot/cogs/expedition.py의 _my_character_autocomplete) 검증.
다른 사람 캐릭터명이 후보로 새면 안 되므로 본인 것만 나오는지 확인한다."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import MagicMock

import pytest

import bot.database.manager as db
from bot.cogs.expedition import _my_character_autocomplete

ME = "111"
OTHER = "222"


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(db.add_character(ME, "발키리"))
    asyncio.run(db.add_character(ME, "워로드부캐"))
    asyncio.run(db.add_character(OTHER, "남의캐릭"))


def _interaction(discord_id: str):
    interaction = MagicMock()
    interaction.user.id = int(discord_id)
    return interaction


def test_autocomplete_only_returns_own_characters(seeded):
    choices = asyncio.run(_my_character_autocomplete(_interaction(ME), ""))
    values = {c.value for c in choices}
    assert values == {"발키리", "워로드부캐"}
    assert "남의캐릭" not in values


def test_autocomplete_filters_by_current_input(seeded):
    choices = asyncio.run(_my_character_autocomplete(_interaction(ME), "워로드"))
    values = {c.value for c in choices}
    assert values == {"워로드부캐"}
