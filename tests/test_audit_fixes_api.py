"""2026-11 봇 감사 결함 회귀 테스트(HTTP/디스코드 UI 계층).

완료 토글 검증, 관리자 API가 공용 코어를 타는지, 카테고리/레이드 삭제 가드, 키 미설정 시 인증
거부, 암호화 키 판별, 전체 공지 중복 방지, 레이드 체크 요약/아머리 캐시 전용 엔드포인트,
Select 25개 한도, 체크리스트 버튼 배치, 영속 초대 뷰, 공대 생성 실패 시 스레드 정리.
"""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
import config
from bot.api import bot_ref
from bot.data.raids import KST
from bot.ui import views

WEB = {"X-Webapp-Key": "test-webapp-key"}
ADMIN = {"X-API-Key": "test-admin-key"}
ME = "111"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    asyncio.run(db.set_user_api_key(ME, "dummy"))
    asyncio.run(db.add_character(ME, "본캐"))
    asyncio.run(db.update_character_cache(ME, "본캐", 1720, "바드"))
    from bot.api.server import app

    yield TestClient(app)
    bot_ref.set_bot(None)
    asyncio.run(raids_module.reload())


def _future() -> str:
    return (datetime.now(KST) + timedelta(days=2)).isoformat()


def _party(mid="701", leader=ME, raid="종막", diff="하드"):
    asyncio.run(db.create_party(
        message_id=mid, channel_id=f"9{mid[-1]}", guild_id="1", leader_id=leader, raid_name=raid,
        difficulty=diff, proficiency="숙련", scheduled_time="일정", scheduled_datetime=_future(),
        total_slots=8, min_level=1700,
    ))


def _completions():
    con = sqlite3.connect(db.DB_PATH)
    try:
        return con.execute("SELECT discord_id, character_name, raid_name, difficulty FROM raid_completions").fetchall()
    finally:
        con.close()


# ── 5. 완료 토글 검증 ──────────────────────────────────────

@pytest.mark.parametrize("body,reason", [
    ({"character_name": "본캐", "raid_name": "없는레이드", "difficulty": "노말"}, "레이드"),
    ({"character_name": "본캐", "raid_name": "종막", "difficulty": "지옥"}, "난이도"),
    ({"character_name": "남의캐릭", "raid_name": "종막", "difficulty": "노말"}, "본인"),
])
def test_toggle_rejects_invalid_input(client, body, reason):
    resp = client.post("/api/internal/completions/toggle", json={"discord_id": ME, **body}, headers=WEB)
    data = resp.json()
    assert data["success"] is False and data["completed"] is False and reason in data["reason"]
    assert _completions() == []


def test_toggle_rejects_extreme_raid(client):
    asyncio.run(db.add_category("익스", 9))
    asyncio.run(db.update_category_extreme("익스", True))
    asyncio.run(db.add_raid("익스A", "익스A", "🔥", "익스"))
    asyncio.run(db.add_difficulty("익스A", "노말", 1600, 8, 4, 1, 0))
    asyncio.run(raids_module.reload())
    resp = client.post("/api/internal/completions/toggle", headers=WEB, json={
        "discord_id": ME, "character_name": "본캐", "raid_name": "익스A", "difficulty": "노말",
    })
    assert resp.json()["success"] is False
    assert _completions() == []


def test_toggle_valid_still_works(client):
    resp = client.post("/api/internal/completions/toggle", headers=WEB, json={
        "discord_id": ME, "character_name": "본캐", "raid_name": "종막", "difficulty": "노말",
    })
    assert resp.json() == {"success": True, "completed": True}


# ── 15. 관리자 API(X-API-Key) → 공용 코어 ──────────────────

def _fake_bot():
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=AsyncMock())
    channel.send = AsyncMock()
    channel.edit = AsyncMock()
    channel.delete = AsyncMock()
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=channel)
    bot.get_user = MagicMock(return_value=None)
    bot.fetch_user = AsyncMock(return_value=AsyncMock())
    bot_ref.set_bot(bot)
    return bot, channel


def test_legacy_clear_has_status_guard_and_records_clear(client):
    _party()
    asyncio.run(db.auto_assign_slot("701", ME, "본캐", "바드", "dps", 8))
    _fake_bot()
    first = client.patch("/api/parties/701/clear", headers=ADMIN).json()
    assert first["success"] and first["count"] == 1
    assert (asyncio.run(db.get_party("701")))["cleared_at"]
    second = client.patch("/api/parties/701/clear", headers=ADMIN).json()
    assert second["success"] is False


def test_legacy_cancel_deletes_thread_too(client):
    _party()
    _bot, channel = _fake_bot()
    assert client.delete("/api/parties/701", headers=ADMIN).json()["success"]
    channel.delete.assert_awaited()
    assert asyncio.run(db.get_party("701")) is None


def test_legacy_kick_dms_and_refreshes(client):
    _party()
    asyncio.run(db.auto_assign_slot("701", "222", "부캐", "워로드", "dps", 8))
    bot, channel = _fake_bot()
    assert client.delete("/api/parties/701/slots/222", headers=ADMIN).json()["success"]
    bot.fetch_user.assert_awaited()  # 퇴장 DM
    channel.fetch_message.assert_awaited()  # 임베드 갱신


def test_legacy_category_delete_refused_when_not_empty(client):
    resp = client.delete("/api/raids/categories/카제로스", headers=ADMIN).json()
    assert resp["success"] is False


def test_raid_delete_refused_with_live_party(client):
    _party()
    assert client.delete("/api/raids/종막", headers=ADMIN).json()["success"] is False
    assert asyncio.run(db.raid_exists("종막"))


def test_legacy_period_validated(client):
    resp = client.patch("/api/raids/종막/period", headers=ADMIN, json={"available_from": "엉망", "available_until": None})
    assert resp.json()["success"] is False


# ── 4. 키 미설정 / 8. 암호화 판별 ─────────────────────────

def test_empty_server_key_rejects_everything(client, monkeypatch):
    monkeypatch.setattr(config, "WEBAPP_API_KEY", "")
    resp = client.get("/api/internal/raids", headers={"X-Webapp-Key": ""})
    assert resp.status_code == 401
    monkeypatch.setattr(config, "ADMIN_API_KEY", "")
    assert client.get("/api/raids", headers={"X-API-Key": ""}).status_code == 401


def test_validate_required_settings(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_API_KEY", "")
    with pytest.raises(RuntimeError):
        config.validate_required_settings()


def test_ciphertext_from_another_key_is_never_reencrypted(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet

    old = Fernet(Fernet.generate_key())
    monkeypatch.setattr(config, "_fernet", Fernet(Fernet.generate_key()))  # 키 교체 후 기동
    foreign = old.encrypt(b"real-key").decode()
    assert config.is_plaintext_key(foreign) is False
    assert config.is_plaintext_key("eyJhbGciOi.plain") is True

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "k.db"))
    asyncio.run(db.init_db())
    con = sqlite3.connect(db.DB_PATH)
    con.execute("INSERT INTO user_api_keys (discord_id, label, api_key, added_at) VALUES ('1','a',?,'x')", (foreign,))
    con.commit(); con.close()
    asyncio.run(db.init_db())  # 마이그레이션 재실행
    con = sqlite3.connect(db.DB_PATH)
    stored = con.execute("SELECT api_key FROM user_api_keys").fetchone()[0]
    con.close()
    assert stored == foreign  # 그대로 — 옛 키로 여전히 복호화 가능
    assert old.decrypt(stored.encode()) == b"real-key"


def test_invalid_encryption_key_fails_startup():
    env = {**os.environ, "ENCRYPTION_KEY": "not-a-fernet-key", "DISCORD_TOKEN": "t"}
    proc = subprocess.run([sys.executable, "-c", "import config"], env=env, capture_output=True, cwd=os.getcwd())
    assert proc.returncode != 0
    assert b"ENCRYPTION_KEY" in proc.stderr


# ── 14. 전체 공지 중복 방지 ────────────────────────────────

def test_notify_all_rejects_identical_broadcast_within_window(client, monkeypatch):
    import bot.services.broadcast as broadcast

    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    monkeypatch.setattr(broadcast, "_last_broadcast", {})
    monkeypatch.setattr(broadcast, "_broadcast_task", None)
    bot, _ = _fake_bot()
    body = {"discord_id": "999", "content": "점검 공지"}
    first = client.post("/api/internal/admin/notify-all", json=body, headers=WEB).json()
    assert first["success"] and first["total"] == 1
    second = client.post("/api/internal/admin/notify-all", json=body, headers=WEB).json()
    assert second["success"] is False and "10분" in second["reason"]
    assert bot.fetch_user.await_count == 1


# ── C. 레이드 체크 요약 / B. 아머리 캐시 전용 ───────────────

def test_raid_check_summary_shape(client):
    week = db.get_week_key()
    asyncio.run(db.add_completion(ME, "본캐", "종막", "노말", week))
    asyncio.run(db.set_selected_raids(ME, "본캐", ["종막", "세르카"]))
    data = client.get("/api/internal/raid-check-summary", params={"discord_id": ME}, headers=WEB).json()
    assert data["week_key"] == week
    assert set(data) >= {"characters", "raids", "categories", "support_classes", "extreme"}
    char = data["characters"][0]
    assert char["character_name"] == "본캐" and char["is_support"] is True
    assert char["completions"] == ["종막_노말"]
    assert char["selection"] == {"customized": True, "selected_raids": ["종막", "세르카"]} or \
        char["selection"]["customized"] is True
    names = [r["raid_name"] for r in char["applicable_raids"]]
    assert "종막" in names and "account_label" in char
    assert set(char["visible_raid_names"]) <= {"종막", "세르카"}
    assert char["done_count"] == 1 and char["total_slots"] == len(char["visible_raid_names"])

    # 기존 raid-progress와 같은 숫자
    prog = client.get("/api/internal/raid-progress", params={"discord_id": ME}, headers=WEB).json()
    assert prog["characters"][0]["done_count"] == char["done_count"]
    assert prog["characters"][0]["total_slots"] == char["total_slots"]


def test_armory_cache_only_never_calls_api(client, monkeypatch):
    import bot.api.lostark as loa

    monkeypatch.setattr(loa, "get_armory", AsyncMock(side_effect=AssertionError("API 호출 금지")))
    monkeypatch.setattr(loa, "get_siblings", AsyncMock(side_effect=AssertionError("API 호출 금지")))
    params = {"discord_id": ME, "character_name": "본캐", "cache_only": "true"}
    miss = client.get("/api/internal/armory-detail", params=params, headers=WEB).json()
    assert miss["not_cached"] is True and "error" in miss
    asyncio.run(db.set_character_armory_cache(ME, "본캐", {"skills": []}))
    hit = client.get("/api/internal/armory-detail", params=params, headers=WEB).json()
    assert hit["skills"] == [] and "synced_at" in hit


# ── 6/7. 디스코드 UI 한도 ──────────────────────────────────

def test_paged_select_caps_options_and_pages():
    options = [discord.SelectOption(label=f"캐릭{i}", value=f"v{i}") for i in range(30)]
    picked = AsyncMock()
    sel = views.PagedSelect(options, picked, placeholder="x")
    assert len(sel.options) == 25 and sel.options[-1].value == views.PagedSelect.MORE_VALUE

    view = discord.ui.View()
    view.add_item(sel)
    interaction = MagicMock()
    interaction.data = {"values": [views.PagedSelect.MORE_VALUE]}
    interaction.response.edit_message = AsyncMock()
    asyncio.run(sel.callback(interaction))
    assert [o.value for o in sel.options][:6] == ["v24", "v25", "v26", "v27", "v28", "v29"]
    picked.assert_not_awaited()

    interaction.data = {"values": ["v26"]}
    asyncio.run(sel.callback(interaction))
    picked.assert_awaited_once()


def test_checklist_view_handles_many_difficulties_in_one_category(monkeypatch):
    fake = {
        f"레이드{i}": {"category": "카제로스", "short_name": f"R{i}", "is_active": True, "is_extreme": False,
                     "difficulties": {d: {"min_level": 1} for d in ("노말", "하드", "나메")}}
        for i in range(10)
    }
    monkeypatch.setattr(raids_module, "RAIDS", fake)
    monkeypatch.setattr(views, "RAIDS", fake)

    async def build():
        return views.RaidChecklistView("1", "캐릭", 1800, set())

    view = asyncio.run(build())
    assert len(view.children) == 25
    assert max(item.row for item in view.children) == 4


# ── 11. 영속 초대 뷰 ──────────────────────────────────────

def test_invite_view_is_persistent_and_restored(client):
    async def run():
        view = views.InviteResponseView("700", None, ME)
        assert view.timeout is None and view.is_persistent()
        assert {c.custom_id for c in view.children} == {"invite:accept:700", "invite:decline:700"}

        await db.create_invite("700", ME, 1)
        await db.set_invite_dm_message("700", ME, "55", "66")
        bot = MagicMock()
        count = await views.restore_invite_views(bot)
        assert count == 1
        kwargs = bot.add_view.call_args.kwargs
        assert kwargs["message_id"] == 66
    asyncio.run(run())


# ── 13. 공대 생성 ─────────────────────────────────────────

def test_create_party_deletes_thread_when_db_insert_fails(client, monkeypatch):
    thread = MagicMock(id=123)
    thread.delete = AsyncMock()
    starter = MagicMock(id=456)
    forum = MagicMock()
    forum.create_thread = AsyncMock(return_value=(thread, starter))
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=forum)
    monkeypatch.setattr(db, "create_party", AsyncMock(side_effect=RuntimeError("db down")))

    with pytest.raises(RuntimeError):
        asyncio.run(views._create_party_core(bot, "1", ME, "1", "종막", "하드", "숙련", "일정", _future()))
    thread.delete.assert_awaited_once()


def test_concurrent_create_party_makes_one_thread(client):
    created = []

    async def create_thread(**kwargs):
        await asyncio.sleep(0.05)
        n = len(created) + 1
        created.append(n)
        starter = MagicMock(id=1000 + n)
        starter.edit = AsyncMock()
        return MagicMock(id=2000 + n), starter

    forum = MagicMock()
    forum.create_thread = create_thread
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=forum)
    sdt = _future()

    async def run():
        return await asyncio.gather(*[
            views._create_party_core(bot, "1", ME, "1", "종막", "하드", "숙련", "일정", sdt) for _ in range(2)
        ])

    a, b = asyncio.run(run())
    assert len(created) == 1 and a["message_id"] == b["message_id"]


def test_admin_party_list_marks_only_cleared_as_revertable(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    _party("701")
    _party("702")
    asyncio.run(db.auto_assign_slot("701", ME, "본캐", "바드", "dps", 8))
    asyncio.run(views._clear_party_core(None, "701", ME))
    asyncio.run(db.disband_party("702"))  # 클리어 아닌 종료
    data = client.get("/api/internal/admin/parties", params={"guild_id": "1", "discord_id": "999"}, headers=WEB).json()
    flags = {p["message_id"]: p["can_revert"] for p in data["closed"]}
    assert flags == {"701": True, "702": False}


def test_refresh_embed_drops_buttons_for_ended_party(client):
    _party("701")
    asyncio.run(db.expire_party("701"))
    msg = MagicMock()
    msg.edit = AsyncMock()
    channel = MagicMock()
    channel.fetch_message = AsyncMock(return_value=msg)
    bot = MagicMock()
    bot.get_channel = MagicMock(return_value=channel)
    asyncio.run(views._refresh_party_embed_with_reserved(bot, asyncio.run(db.get_party("701"))))
    assert msg.edit.await_args.kwargs["view"] is None
