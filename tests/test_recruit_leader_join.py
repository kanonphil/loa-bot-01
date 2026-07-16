"""bot/ui/views._offer_leader_join 검증 — 디스코드 /공대모집으로 개설한 직후
리더에게 참여할 캐릭터를 물어보는 흐름(웹의 "참여할 캐릭터" 선택과 동등한 기능)."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.ui import views

LEADER_ID = "222"


def _setup_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(LEADER_ID, "dummy-key"))
    asyncio.run(
        db.create_party(
            message_id="700", channel_id="600", guild_id="1", leader_id=LEADER_ID,
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )


def test_offer_leader_join_sends_character_select_when_qualifying(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)
    asyncio.run(db.add_character(LEADER_ID, "발키리"))
    asyncio.run(db.update_character_cache(LEADER_ID, "발키리", item_level=1710.0, character_class="홀리나이트"))

    interaction = MagicMock()
    interaction.followup.send = AsyncMock(return_value=MagicMock())
    party = asyncio.run(db.get_party("700"))

    asyncio.run(views._offer_leader_join(interaction, party))

    assert interaction.followup.send.called
    sent_kwargs = interaction.followup.send.call_args
    assert "참여할 캐릭터를 선택" in sent_kwargs.args[0] or "참여할 캐릭터를 선택" in sent_kwargs.kwargs.get("content", "")
    assert isinstance(sent_kwargs.kwargs["view"], views.CharSelectView)


def test_offer_leader_join_skips_silently_when_no_qualifying_character(tmp_path, monkeypatch):
    """참여 가능한 캐릭터가 없으면(레벨 미달/미등록 등) 조용히 넘어가야 한다 —
    개설 자체는 이미 끝났으니 여기서 에러 메시지를 새로 띄우면 안 된다."""
    _setup_db(tmp_path, monkeypatch)
    asyncio.run(db.add_character(LEADER_ID, "저레벨캐릭"))
    asyncio.run(db.update_character_cache(LEADER_ID, "저레벨캐릭", item_level=1000.0, character_class="워로드"))

    interaction = MagicMock()
    interaction.followup.send = AsyncMock()
    party = asyncio.run(db.get_party("700"))

    asyncio.run(views._offer_leader_join(interaction, party))

    assert not interaction.followup.send.called


def test_offer_leader_join_skips_when_no_registered_characters(tmp_path, monkeypatch):
    _setup_db(tmp_path, monkeypatch)  # 캐릭터를 아예 등록하지 않음

    interaction = MagicMock()
    interaction.followup.send = AsyncMock()
    party = asyncio.run(db.get_party("700"))

    asyncio.run(views._offer_leader_join(interaction, party))

    assert not interaction.followup.send.called
