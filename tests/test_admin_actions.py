"""관리자 활동 기록(admin_actions) — 공용 코어에서 기록, 목록/필터, 되돌리기, 유저 삭제 영향."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
import config
from bot.api import bot_ref
from bot.data.raids import KST
from bot.services import admin_log, loa_content
from bot.ui import views

WEB = {"X-Webapp-Key": "test-webapp-key"}
API = {"X-API-Key": "test-admin-key"}
ADMIN = "100"
LEADER = "200"
MEMBER = "300"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {ADMIN})
    monkeypatch.setattr(config, "GUEST_LOOKUP_DISCORD_ID", "")  # 로스트아크 호출 없음
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())
    for uid, char, cls in ((LEADER, "리더캐", "바드"), (MEMBER, "멤버캐", "워로드")):
        asyncio.run(db.set_user_api_key(uid, "dummy"))
        asyncio.run(db.add_character(uid, char))
        asyncio.run(db.update_character_cache(uid, char, 1740, cls))
    loa_content._reset_state_for_tests()
    bot_ref.set_bot(None)
    from bot.api.server import app

    yield TestClient(app)
    bot_ref.set_bot(None)
    loa_content._reset_state_for_tests()
    asyncio.run(raids_module.reload())


def _party(mid="701", leader=LEADER):
    asyncio.run(db.create_party(
        message_id=mid, channel_id=f"9{mid}", guild_id="1", leader_id=leader, raid_name="종막",
        difficulty="하드", proficiency="숙련", scheduled_time="일정",
        scheduled_datetime=(datetime.now(KST) + timedelta(days=2)).isoformat(),
        total_slots=8, min_level=1700,
    ))


def _join(mid, uid, char, cls="바드"):
    asyncio.run(db.auto_assign_slot(mid, uid, char, cls, "dps", 8))


def _actions(client, kind="all"):
    resp = client.get("/api/internal/admin/actions", params={"discord_id": ADMIN, "kind": kind}, headers=WEB)
    assert resp.status_code == 200
    return resp.json()["items"]


def test_force_close_logged_and_undo_reopens(client):
    _party()
    resp = client.post("/api/internal/parties/701/close", json={"discord_id": ADMIN}, headers=WEB)
    assert resp.json()["success"] is True
    items = _actions(client)
    assert len(items) == 1
    item = items[0]
    assert set(item) == {"id", "at", "actor_name", "source", "action", "summary", "undoable", "undone_at"}
    assert item["action"] == "party.close" and item["source"] == "web"
    assert item["summary"] == "종막 하드 공대 강제 마감"
    assert item["undoable"] is True and item["undone_at"] is None
    assert item["at"].endswith("+09:00")

    resp = client.post(f"/api/internal/admin/actions/{item['id']}/undo", json={"discord_id": ADMIN}, headers=WEB)
    assert resp.json() == {"success": True, "reason": None}
    assert asyncio.run(db.get_party("701"))["status"] == "recruiting"

    items = _actions(client)
    assert [i["action"] for i in items] == ["party.close.undo", "party.close"]  # 되돌리기도 기록, 재개 자체는 따로 안 남김
    assert items[0]["summary"] == "되돌리기: 종막 하드 공대 강제 마감" and items[0]["undoable"] is False
    assert items[1]["undoable"] is False and items[1]["undone_at"]

    again = client.post(f"/api/internal/admin/actions/{item['id']}/undo", json={"discord_id": ADMIN}, headers=WEB).json()
    assert again == {"success": False, "reason": "이미 되돌린 기록입니다."}


def test_reopen_logged_and_undo_closes(client):
    _party()
    asyncio.run(db.close_party("701"))
    client.post("/api/internal/parties/701/reopen", json={"discord_id": ADMIN}, headers=WEB)
    item = _actions(client)[0]
    assert item["action"] == "party.reopen" and item["undoable"]
    client.post(f"/api/internal/admin/actions/{item['id']}/undo", json={"discord_id": ADMIN}, headers=WEB)
    assert asyncio.run(db.get_party("701"))["status"] == "closed"


def test_undo_failure_keeps_action_undoable(client):
    _party()
    client.post("/api/internal/parties/701/close", json={"discord_id": ADMIN}, headers=WEB)
    item = _actions(client)[0]
    asyncio.run(db.reopen_party("701"))  # 그 사이 누가 이미 재개함
    resp = client.post(f"/api/internal/admin/actions/{item['id']}/undo", json={"discord_id": ADMIN}, headers=WEB).json()
    assert resp["success"] is False and resp["reason"]
    assert _actions(client)[0]["undoable"] is True


def test_leader_own_actions_not_logged(client):
    _party()
    client.post("/api/internal/parties/701/close", json={"discord_id": LEADER}, headers=WEB)
    client.post("/api/internal/parties/701/reopen", json={"discord_id": LEADER}, headers=WEB)
    assert _actions(client) == []


def test_sources_discord_and_api(client):
    _party("701")
    _party("702")
    asyncio.run(views._close_party_core(None, "701", ADMIN, source="discord"))
    resp = client.patch("/api/parties/702/close", headers=API)
    assert resp.json()["success"] is True
    rows = _actions(client)
    assert {r["source"] for r in rows} == {"discord", "api"}
    api_row = next(r for r in rows if r["source"] == "api")
    assert api_row["actor_name"] == "관리자 API"


def test_kick_transfer_reschedule_difficulty_revert_disband_logged(client):
    _party()
    _join("701", LEADER, "리더캐")
    _join("701", MEMBER, "멤버캐", "워로드")
    client.post("/api/internal/parties/701/transfer-leader",
                json={"discord_id": ADMIN, "new_leader_discord_id": MEMBER}, headers=WEB)
    new_time = (datetime.now(KST) + timedelta(days=3)).strftime("%Y-%m-%dT%H:%M")
    client.post("/api/internal/parties/701/reschedule", json={"discord_id": ADMIN, "scheduled_datetime": new_time}, headers=WEB)
    client.post("/api/internal/parties/701/edit-difficulty",
                json={"discord_id": ADMIN, "difficulty": "하드", "proficiency": "트라이"}, headers=WEB)
    client.post("/api/internal/parties/701/kick", json={"discord_id": ADMIN, "target_discord_id": LEADER}, headers=WEB)
    asyncio.run(views._clear_party_core(None, "701", MEMBER))  # 파티장 본인 클리어 — 기록 안 함
    client.post("/api/internal/admin/parties/701/revert-clear", json={"discord_id": ADMIN}, headers=WEB)
    client.post("/api/internal/admin/parties/701/disband", json={"discord_id": ADMIN}, headers=WEB)

    actions = [i["action"] for i in reversed(_actions(client, "party"))]
    assert actions == ["party.transfer", "party.reschedule", "party.difficulty", "party.kick",
                       "party.revert_clear", "party.disband"]
    summaries = [i["summary"] for i in reversed(_actions(client, "party"))]
    assert summaries[0] == "종막 하드 공대 파티장 위임 → 멤버캐"
    assert summaries[2] == "종막 하드 공대 난이도 변경 (하드 숙련 → 하드 트라이)"
    assert summaries[3] == "종막 하드 공대 리더캐 강퇴"


def test_raid_rename_and_active_undo(client):
    asyncio.run(db.add_category("테스트", 50))
    asyncio.run(db.add_raid("카멘(익스)", "카멘", "x", "테스트"))
    asyncio.run(db.add_difficulty("카멘(익스)", "노말", 1600, 8, 4, 1, 0))
    asyncio.run(raids_module.reload())
    _party("801")
    asyncio.run(db.add_completion(LEADER, "리더캐", "카멘(익스)", "노말", db.get_week_key()))
    asyncio.run(db.create_party(
        message_id="802", channel_id="9802", guild_id="1", leader_id=LEADER, raid_name="카멘(익스)",
        difficulty="노말", proficiency="숙련", scheduled_time="일정",
        scheduled_datetime=(datetime.now(KST) + timedelta(days=2)).isoformat(), total_slots=8, min_level=1600,
    ))

    resp = client.post("/api/internal/admin/raids/rename",
                       json={"discord_id": ADMIN, "old_name": "카멘(익스)", "new_name": "카멘 익스트림"}, headers=WEB)
    assert resp.json() == {"success": True}
    item = _actions(client, "raid")[0]
    assert item["summary"] == '레이드 이름 "카멘(익스)" → "카멘 익스트림" · 공대 1, 기록 1건 함께 변경'
    client.post(f"/api/internal/admin/actions/{item['id']}/undo", json={"discord_id": ADMIN}, headers=WEB)
    assert asyncio.run(db.raid_exists("카멘(익스)")) and not asyncio.run(db.raid_exists("카멘 익스트림"))
    assert asyncio.run(db.get_party("802"))["raid_name"] == "카멘(익스)"

    client.post("/api/internal/admin/raids/active", json={"discord_id": ADMIN, "name": "카멘(익스)", "is_active": False}, headers=WEB)
    item = _actions(client, "raid")[0]
    assert item["action"] == "raid.disable" and item["summary"] == '레이드 "카멘(익스)" 비활성화'
    client.post(f"/api/internal/admin/actions/{item['id']}/undo", json={"discord_id": ADMIN}, headers=WEB)
    assert raids_module.RAIDS["카멘(익스)"]["is_active"] is True


def test_raid_crud_and_difficulty_gold_edit_logged(client):
    post = lambda path, body: client.post(f"/api/internal/admin/{path}", json={"discord_id": ADMIN, **body}, headers=WEB)
    post("categories/add", {"name": "신규", "sort_order": 9})
    post("raids/add", {"name": "새레이드", "short_name": "새", "category": "신규"})
    post("difficulties/add", {"raid_name": "새레이드", "difficulty": "노말", "min_level": 1600, "total_slots": 4})
    post("difficulties/update", {"raid_name": "새레이드", "difficulty": "노말", "min_level": 1600, "total_slots": 4, "clear_gold": 30000})
    post("raids/delete", {"name": "새레이드"})
    post("categories/delete", {"name": "신규"})
    items = list(reversed(_actions(client, "raid")))
    assert [i["action"] for i in items] == [
        "category.create", "raid.create", "difficulty.add", "difficulty.update", "raid.delete", "category.delete",
    ]
    assert items[3]["summary"] == "새레이드 노말 난이도 수정 · 골드 미입력 → 30,000"
    assert all(i["undoable"] is False for i in items)
    resp = client.post(f"/api/internal/admin/actions/{items[0]['id']}/undo", json={"discord_id": ADMIN}, headers=WEB).json()
    assert resp == {"success": False, "reason": "되돌릴 수 없는 기록입니다."}


def test_legacy_api_raid_changes_logged(client):
    client.post("/api/raids/categories", json={"name": "API카테", "sort_order": 3}, headers=API)
    rows = _actions(client, "raid")
    assert rows[0]["action"] == "category.create" and rows[0]["source"] == "api"


def test_tracked_items_change_undo(client):
    asyncio.run(loa_content.set_tracked_items(["A"]))
    resp = client.post("/api/internal/admin/loa/tracked-items", json={"discord_id": ADMIN, "names": ["B", "C"]}, headers=WEB)
    assert resp.json()["names"] == ["B", "C"]
    items = _actions(client)
    assert items[0]["action"] == "loa.tracked_items" and items[0]["undoable"]
    assert _actions(client, "party") == [] and _actions(client, "raid") == []
    client.post(f"/api/internal/admin/actions/{items[0]['id']}/undo", json={"discord_id": ADMIN}, headers=WEB)
    assert asyncio.run(loa_content.get_tracked_items()) == ["A"]


def test_completion_and_notify_and_user_delete_in_user_kind(client, monkeypatch):
    client.post("/api/internal/admin/completions/set", json={
        "discord_id": ADMIN, "target_discord_id": MEMBER, "character_name": "멤버캐", "raid_name": "종막",
        "difficulty": "하드", "week_key": db.get_week_key(), "done": True,
    }, headers=WEB)
    client.post(f"/api/internal/admin/users/{MEMBER}/delete", json={"discord_id": ADMIN}, headers=WEB)
    items = _actions(client, "user")
    assert [i["action"] for i in items] == ["user.delete", "completion.set"]
    assert items[0]["summary"].startswith("유저 멤버캐 삭제")
    assert _actions(client, "party") == []


def test_actor_name_prefers_discord_display_name(client):
    class Member:
        display_name = "관리자닉"

    class Guild:
        def get_member(self, uid):
            return Member() if uid == int(ADMIN) else None

    class FakeBot:
        guilds = [Guild()]

        def get_user(self, uid):
            return None

    bot_ref.set_bot(FakeBot())
    assert asyncio.run(admin_log.actor_name(ADMIN)) == "관리자닉"
    assert asyncio.run(admin_log.actor_name(LEADER)) == "리더캐"  # 캐시에 없으면 대표 캐릭터
    assert asyncio.run(admin_log.actor_name("12345")) == "12345"
    assert asyncio.run(admin_log.actor_name("")) == "관리자 API"


def test_admin_actions_requires_admin(client):
    assert client.get("/api/internal/admin/actions", params={"discord_id": LEADER}, headers=WEB).status_code == 403
    resp = client.post("/api/internal/admin/actions/1/undo", json={"discord_id": LEADER}, headers=WEB).json()
    assert resp == {"success": False, "reason": "관리자 권한이 없습니다."}
    resp = client.post("/api/internal/admin/actions/999/undo", json={"discord_id": ADMIN}, headers=WEB).json()
    assert resp == {"success": False, "reason": "기록을 찾을 수 없습니다."}


def test_record_failure_does_not_break_action(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "insert_admin_action", boom)
    _party()
    assert client.post("/api/internal/parties/701/close", json={"discord_id": ADMIN}, headers=WEB).json()["success"] is True


# ── §5 유저 삭제 영향 ──────────────────────────────────────

def test_user_delete_impact(client):
    _party("701", leader=LEADER)
    _join("701", LEADER, "리더캐")
    _join("701", MEMBER, "멤버캐", "워로드")
    _party("702", leader=LEADER)  # 슬롯 없이 파티장만
    _party("703", leader=MEMBER)
    _join("703", LEADER, "리더캐")
    asyncio.run(db.add_user_api_key(LEADER, "본계정", "k1"))
    asyncio.run(db.add_completion(LEADER, "리더캐", "종막", "노말", db.get_week_key()))
    asyncio.run(db.add_completion(LEADER, "리더캐", "종막", "하드", "2000-01-05"))  # 지난 주차

    resp = client.get(f"/api/internal/admin/users/{LEADER}/impact", params={"discord_id": ADMIN}, headers=WEB)
    assert resp.status_code == 200
    body = resp.json()
    assert body["characters"] == 1 and body["api_keys"] == 1 and body["completions_this_week"] == 1
    by_id = {p["message_id"]: p for p in body["active_parties"]}
    assert set(by_id) == {"701", "702", "703"}
    assert by_id["701"] == {"message_id": "701", "raid_name": "종막", "difficulty": "하드", "is_leader": True,
                            "handover_to": {"discord_id": MEMBER, "name": "멤버캐"}}
    assert by_id["702"]["is_leader"] is True and by_id["702"]["handover_to"] is None
    assert by_id["703"]["is_leader"] is False and by_id["703"]["handover_to"] is None

    assert client.get(f"/api/internal/admin/users/{LEADER}/impact", params={"discord_id": MEMBER}, headers=WEB).status_code == 403

    # 실제 삭제 결과가 영향 예고와 같다
    client.post(f"/api/internal/admin/users/{LEADER}/delete", json={"discord_id": ADMIN}, headers=WEB)
    assert asyncio.run(db.get_party("701"))["leader_id"] == MEMBER
    assert asyncio.run(db.get_party("702"))["status"] == "disbanded"
    detail = asyncio.run(db.list_admin_actions(("user.",)))[0]
    assert json.loads(detail["detail_json"])["characters"] == 1
    # 위임/종료는 유저 삭제 한 줄로만 남는다
    assert [i["action"] for i in _actions(client)] == ["user.delete"]


def test_discord_admin_command_logged(client):
    from unittest.mock import AsyncMock, MagicMock

    from bot.cogs.admin import Admin

    asyncio.run(db.add_category("디코카테", 7))
    interaction = MagicMock()
    interaction.client.is_owner = AsyncMock(return_value=True)
    interaction.user.id = int(ADMIN)
    interaction.response.send_message = AsyncMock()
    cog = Admin(MagicMock())
    asyncio.run(Admin.del_category.callback(cog, interaction, "디코카테"))
    row = _actions(client, "raid")[0]
    assert row["action"] == "category.delete" and row["source"] == "discord"
    assert row["summary"] == '카테고리 "디코카테" 삭제'


def test_legacy_schedule_change_logged(client):
    _party()
    resp = client.patch("/api/parties/701/schedule", json={"scheduled_time": "새일정", "scheduled_datetime": "2026-12-01T20:00:00+09:00"}, headers=API)
    assert resp.json() == {"success": True}
    row = _actions(client, "party")[0]
    assert row["action"] == "party.reschedule" and row["source"] == "api"
    assert row["summary"] == "종막 하드 공대 일정 변경 (일정 → 새일정)"
