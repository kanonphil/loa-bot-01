"""bot/api/routes/internal.py의 공대 모집(참여/나가기) 엔드포인트 검증."""
import os

os.environ.setdefault("DISCORD_TOKEN", "test-token")
os.environ.setdefault("ADMIN_API_KEY", "test-admin-key")
os.environ.setdefault("WEBAPP_API_KEY", "test-webapp-key")

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

import bot.data.raids as raids_module
import bot.database.manager as db
from bot.api import bot_ref

HEADERS = {"X-Webapp-Key": "test-webapp-key"}


@pytest.fixture()
def party_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    asyncio.run(db.init_db())
    asyncio.run(raids_module.reload())

    asyncio.run(db.set_user_api_key("111", "dummy-key"))
    asyncio.run(db.add_character("111", "발키리"))
    asyncio.run(
        db.update_character_cache("111", "발키리", item_level=1710.0, character_class="홀리나이트")
    )
    asyncio.run(db.set_user_api_key("222", "dummy-key-2"))
    asyncio.run(db.add_character("222", "워로드캐릭"))
    asyncio.run(
        db.update_character_cache("222", "워로드캐릭", item_level=1710.0, character_class="워로드")
    )

    asyncio.run(
        db.create_party(
            message_id="999", channel_id="555", guild_id="1", leader_id="222",
            raid_name="아르모체(4막)", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=8, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("999", "222", "워로드캐릭", "워로드", "dps", 8))
    return "999"


@pytest.fixture()
def client():
    from bot.api.server import app

    return TestClient(app)


@pytest.fixture()
def fake_bot(monkeypatch):
    fake_message = AsyncMock()
    fake_channel = MagicMock()
    fake_channel.fetch_message = AsyncMock(return_value=fake_message)
    fake_channel.edit = AsyncMock()
    fake_channel.send = AsyncMock()

    fake_leader_user = MagicMock()
    fake_leader_user.send = AsyncMock()

    fake_bot = MagicMock()
    fake_bot.get_channel = MagicMock(return_value=fake_channel)
    fake_bot.fetch_user = AsyncMock(return_value=fake_leader_user)

    bot_ref.set_bot(fake_bot)
    yield fake_bot, fake_channel, fake_message
    bot_ref.set_bot(None)


def test_list_parties_includes_slots(client, party_setup, fake_bot):
    resp = client.get("/api/internal/parties", params={"guild_id": "1"}, headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert len(data[0]["slots"]) == 1
    assert data[0]["slots"][0]["character_name"] == "워로드캐릭"


def test_support_classes_endpoint_includes_known_support_class(client, party_setup, fake_bot):
    """공대 개설 폼이 캐릭터별 역할 선택지를 제한하는 데 쓰는 목록 — 서포터로
    분류된 직업(예: 홀리나이트)이 포함돼야 한다."""
    resp = client.get("/api/internal/support-classes", headers=HEADERS)
    assert resp.status_code == 200
    classes = resp.json()
    assert "홀리나이트" in classes
    assert "워로드" not in classes


def test_party_detail_returns_none_for_missing(client, party_setup, fake_bot):
    resp = client.get("/api/internal/parties/no-such-id", headers=HEADERS)
    assert resp.status_code == 200
    assert resp.json() is None


def test_eligibility_endpoint_matches_shared_logic(client, party_setup, fake_bot):
    resp = client.get(
        "/api/internal/parties/999/eligibility",
        params={"discord_id": "111"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["can_join"] is True
    assert [q["name"] for q in data["qualifying"]] == ["발키리"]


def test_join_success_refreshes_discord_embed(client, party_setup, fake_bot):
    """아르모체(4막) 노말은 party_split=4(8인을 4+4로 분할)라 party_group 지정이 필요하다."""
    _, fake_channel, fake_message = fake_bot

    resp = client.post(
        "/api/internal/parties/999/join",
        json={
            "discord_id": "111",
            "character_name": "발키리",
            "role": "support",
            "party_group": 1,
        },
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["slot_number"] == 2

    fake_channel.fetch_message.assert_awaited_once()
    fake_message.edit.assert_awaited_once()
    slots = asyncio.run(db.get_party_slots(party_setup))
    assert any(s["discord_id"] == "111" and s["role"] == "support" for s in slots)


def test_join_removes_waitlist_entry(client, party_setup, fake_bot):
    """회귀 테스트: 웹 참여가 waitlist를 안 지워서, 이미 참여한 사람에게 나중에
    빈자리 알림 DM이 갈 수 있던 버그."""
    asyncio.run(db.add_waitlist(party_setup, "111"))
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "발키리", "role": "support", "party_group": 1},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    waitlist = asyncio.run(db.get_waitlist(party_setup))
    assert "111" not in waitlist


def test_join_notifies_leader_by_dm(client, party_setup, fake_bot):
    """회귀 테스트: 웹으로 참여해도 디스코드 참여하기 버튼처럼 파티장에게 DM이 가야 한다."""
    fake_bot_obj, _, _ = fake_bot
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "발키리", "role": "support", "party_group": 1},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    fake_bot_obj.fetch_user.assert_awaited_once_with(222)  # leader_id="222"
    leader_user = fake_bot_obj.fetch_user.return_value
    leader_user.send.assert_awaited_once()
    assert "발키리" in leader_user.send.call_args.args[0]


def test_join_does_not_dm_when_leader_joins_own_party(client, party_setup, fake_bot):
    """리더가 아직 파티에 슬롯을 차지하지 않은 상태(공대만 개설하고 바로 참여는
    안 한 경우)에서 스스로 참여하면, 자기 자신에게 DM을 보내지 않아야 한다.
    party_setup 픽스처가 이미 유저 222("워로드캐릭") 계정을 세팅해뒀으니 그대로 재사용한다."""
    asyncio.run(
        db.create_party(
            message_id="997", channel_id="557", guild_id="1", leader_id="222",
            raid_name="세르카", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=4, min_level=1700,
        )
    )
    fake_bot_obj, _, _ = fake_bot
    resp = client.post(
        "/api/internal/parties/997/join",
        json={"discord_id": "222", "character_name": "워로드캐릭", "role": "dps"},
        headers=HEADERS,
    )
    assert resp.json()["success"] is True
    fake_bot_obj.fetch_user.assert_not_called()


def test_join_announces_when_party_becomes_full(client, party_setup, fake_bot):
    """회귀 테스트: 웹 참여로 파티가 만석이 돼도 채널에 "파티가 완성되었습니다" 공지가
    나가야 한다 — 디스코드 참여하기 버튼과 동일한 동작. party_split이 없는 4인 레이드로
    party_group 파라미터 없이 간단히 검증한다."""
    _, fake_channel, _ = fake_bot
    # party_setup 픽스처가 이미 유저 222("워로드캐릭") 계정을 세팅해뒀으니 그대로 재사용한다.
    asyncio.run(
        db.create_party(
            message_id="998", channel_id="556", guild_id="1", leader_id="222",
            raid_name="세르카", difficulty="노말", proficiency="숙련",
            scheduled_time="05/20 20:00", scheduled_datetime="2026-05-20T20:00:00+09:00",
            total_slots=4, min_level=1700,
        )
    )
    asyncio.run(db.auto_assign_slot("998", "222", "워로드캐릭", "워로드", "dps", 4))

    for i, name in enumerate(["딜러A", "딜러B", "딜러C"], start=1):
        discord_id = f"90{i}"
        asyncio.run(db.set_user_api_key(discord_id, f"dummy-{i}"))
        asyncio.run(db.add_character(discord_id, name))
        asyncio.run(db.update_character_cache(discord_id, name, item_level=1710.0, character_class="워로드"))
        resp = client.post(
            "/api/internal/parties/998/join",
            json={"discord_id": discord_id, "character_name": name, "role": "dps"},
            headers=HEADERS,
        )
        assert resp.json()["success"] is True, resp.json()

    fake_channel.send.assert_awaited()
    sent_texts = [c.args[0] for c in fake_channel.send.await_args_list]
    assert any("파티가 완성되었습니다" in t for t in sent_texts)


def test_join_requires_party_group_when_raid_is_split(client, party_setup, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "발키리", "role": "support"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert "파티" in body["reason"]


def test_join_rejects_ineligible_character_tampering(client, party_setup, fake_bot):
    """participant가 낮은 레벨 캐릭터로 조작해서 보내도 서버가 다시 검증해서 막아야 한다."""
    asyncio.run(
        db.update_character_cache("111", "발키리", item_level=1000.0, character_class="홀리나이트")
    )
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "발키리", "role": "support"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_join_rejects_support_role_for_non_support_class(client, party_setup, fake_bot):
    asyncio.run(db.add_character("111", "워로드둘째"))
    asyncio.run(
        db.update_character_cache("111", "워로드둘째", item_level=1710.0, character_class="워로드")
    )
    resp = client.post(
        "/api/internal/parties/999/join",
        json={"discord_id": "111", "character_name": "워로드둘째", "role": "support"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
    assert "서포터" in resp.json()["reason"]


def test_leave_removes_slot_and_refreshes_embed(client, party_setup, fake_bot):
    _, fake_channel, fake_message = fake_bot
    asyncio.run(db.auto_assign_slot("999", "111", "발키리", "서포터", "support", 8))

    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "111"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is True

    slots = asyncio.run(db.get_party_slots("999"))
    assert not any(s["discord_id"] == "111" for s in slots)
    fake_message.edit.assert_awaited()


def test_leave_transfers_leadership_when_leader_leaves(client, party_setup, fake_bot):
    asyncio.run(db.auto_assign_slot("999", "111", "발키리", "서포터", "support", 8))

    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "222"},  # 원래 파티장
        headers=HEADERS,
    )
    assert resp.status_code == 200

    party = asyncio.run(db.get_party("999"))
    assert party["leader_id"] == "111"


def test_leave_transfer_notifies_new_leader_by_dm_and_channel(client, party_setup, fake_bot):
    """회귀 테스트: 웹으로 파티장이 나가면(리더십 위임) 새 파티장에게 채널 공지 +
    DM이 가야 한다 — 이전에는 embed만 갱신되고 이 알림들이 전혀 발생하지 않았다."""
    fake_bot_obj, fake_channel, _ = fake_bot
    asyncio.run(db.auto_assign_slot("999", "111", "발키리", "서포터", "support", 8))

    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "222"},  # 원래 파티장
        headers=HEADERS,
    )
    assert resp.json()["success"] is True

    sent_texts = [c.args[0] for c in fake_channel.send.await_args_list]
    assert any("파티장 변경" in t for t in sent_texts)
    fake_bot_obj.fetch_user.assert_awaited_once_with(111)
    leader_user = fake_bot_obj.fetch_user.return_value
    leader_user.send.assert_awaited_once()
    assert "파티장이 되었습니다" in leader_user.send.call_args.args[0]


def test_leave_last_member_announces_and_archives_thread(client, party_setup, fake_bot):
    """회귀 테스트: 마지막 파티원이 웹으로 나가서 공대가 해체될 때 채널 공지 +
    스레드 아카이브/잠금이 함께 처리돼야 한다."""
    _, fake_channel, fake_message = fake_bot

    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "222"},  # 유일한 멤버이자 파티장
        headers=HEADERS,
    )
    assert resp.json()["success"] is True

    party = asyncio.run(db.get_party("999"))
    assert party["status"] == "disbanded"
    fake_message.edit.assert_awaited_once()
    sent_texts = [c.args[0] for c in fake_channel.send.await_args_list]
    assert any("파티원이 모두 나가" in t for t in sent_texts)
    fake_channel.edit.assert_awaited_once_with(archived=True, locked=True)


def test_leave_non_leader_from_full_party_notifies_waitlist(client, party_setup, fake_bot):
    """회귀 테스트: 만석이었던 파티에서 리더가 아닌 멤버가 나가 다시 recruiting 상태로
    바뀌면 "빈 자리가 생겼습니다" 채널 공지 + 대기열 등록자에게 DM이 가야 한다 —
    이전에는 웹으로 나가면 embed만 갱신되고 이 알림들이 전혀 발생하지 않았다."""
    fake_bot_obj, fake_channel, _ = fake_bot
    # party_setup: 999번 파티, total_slots=8, 리더 "222"만 슬롯 1개 차지 중.
    # 나머지 7슬롯을 다른 인원으로 채워 만석으로 만든 뒤, 리더가 아닌 한 명을 내보낸다.
    for i in range(7):
        discord_id = f"80{i}"
        name = f"딜러{i}"
        asyncio.run(db.set_user_api_key(discord_id, f"dummy-{i}"))
        asyncio.run(db.add_character(discord_id, name))
        asyncio.run(db.update_character_cache(discord_id, name, item_level=1710.0, character_class="워로드"))
        asyncio.run(db.auto_assign_slot("999", discord_id, name, "워로드", "dps", 8))
    assert asyncio.run(db.get_party("999"))["status"] == "full"
    asyncio.run(db.add_waitlist("999", "333"))

    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "800"},  # 리더(222) 아닌 멤버가 나감
        headers=HEADERS,
    )
    assert resp.json()["success"] is True

    party_after = asyncio.run(db.get_party("999"))
    assert party_after["status"] == "recruiting"
    sent_texts = [c.args[0] for c in fake_channel.send.await_args_list]
    assert any("빈 자리가 생겼습니다" in t for t in sent_texts)
    fake_bot_obj.fetch_user.assert_awaited_once_with(333)
    waitlist_user = fake_bot_obj.fetch_user.return_value
    waitlist_user.send.assert_awaited_once()
    assert "빈 자리가 생겼습니다" in waitlist_user.send.call_args.args[0]
    waitlist = asyncio.run(db.get_waitlist("999"))
    assert waitlist == []


def test_leave_disbands_party_when_last_member_leaves(client, party_setup, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "222"},  # 유일한 멤버이자 파티장
        headers=HEADERS,
    )
    assert resp.status_code == 200

    party = asyncio.run(db.get_party("999"))
    assert party["status"] == "disbanded"


def test_leave_rejects_user_not_in_party(client, party_setup, fake_bot):
    resp = client.post(
        "/api/internal/parties/999/leave",
        json={"discord_id": "999999"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    assert resp.json()["success"] is False
