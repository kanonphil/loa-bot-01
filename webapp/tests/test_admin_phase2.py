"""관리 화면 개편(2단계) — 레이드 마스터-디테일/클리어 골드, 공대 표·행 동작, 유저 내보내기 영향 범위, 작업 기록,
전체 공지 진행률, 시세 아이템. 봇 서버는 respx로 모킹하고, 새 엔드포인트가 404여도 화면이 그려지는지를 본다."""
import asyncio
import json

import httpx
import respx

from webapp import config, notification_store
from webapp.tests.conftest import log_in, toast_of, without_toast

B = "http://bot-server.internal/api/internal"
A = f"{B}/admin"
RAIDS_URL = f"{B}/raids"
CATEGORIES_URL = f"{B}/raid-categories"

CATEGORIES = [{"name": "카제로스", "sort_order": 0, "is_extreme": 0}, {"name": "익스트림", "sort_order": 1, "is_extreme": 1}]
RAIDS = {
    "종막": {
        "short_name": "종막", "icon": "⚔️", "category": "카제로스", "is_extreme": False, "is_active": True,
        "is_pinned": True, "sort_order": 0, "available_from": None, "available_until": None,
        "difficulties": {
            "노말": {"min_level": 1710, "total_slots": 8, "party_split": 4, "gates": 2},
            "하드": {"min_level": 1730, "total_slots": 8, "party_split": 4, "gates": 2, "clear_gold": 2300},
        },
        "difficulty_gold": {"노말": 1500, "하드": 2300},
    },
    "세르카": {
        "short_name": "세르카", "icon": "🌊", "category": "카제로스", "is_extreme": False, "is_active": True,
        "is_pinned": False, "sort_order": 1, "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 4, "party_split": None, "gates": 2}},
    },
}
REFS = {"parties_live": 0, "parties_all": 2, "party_history": 12, "raid_completions": 88, "raid_subscriptions": 3,
        "character_raid_selection": 5, "notification_logs": 4}
STATUS = {"is_online": True, "uptime_str": "3일 4시간", "user_count": 22, "active_party_count": 3, "subscription_count": 10, "latency_ms": 41.2}


def _admin(client, monkeypatch, discord_id="111"):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {discord_id})
    log_in(client, discord_id=discord_id)


def _mock_raids(refs=REFS):
    respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
    respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
    respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
    if refs is None:
        respx.get(f"{A}/raids/references").mock(return_value=httpx.Response(404, json={"detail": "x"}))
    else:
        respx.get(f"{A}/raids/references").mock(return_value=httpx.Response(200, json=refs))


def _payload(route, i=0):
    return json.loads(route.calls[i].request.content)


# ── 공통 틀 ────────────────────────────────────────────────

def test_admin_pages_share_title_row_status_chip_and_actions_tab(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids()
        resp = client.get("/admin/raids")
    assert resp.status_code == 200
    assert "봇 온라인" in resp.text and "업타임 3일 4시간" in resp.text
    assert 'href="/admin/actions"' in resp.text  # 묶음 탭에 작업 기록
    assert "/static/pages/admin.css" in resp.text and "/static/pages/admin.js" in resp.text


def test_page_renders_when_bot_status_is_unavailable(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(CATEGORIES_URL).mock(return_value=httpx.Response(200, json=CATEGORIES))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(500))
        respx.get(f"{A}/raids/references").mock(return_value=httpx.Response(200, json=REFS))
        resp = client.get("/admin/raids")
    assert resp.status_code == 200
    assert "봇 상태를 확인하지 못했습니다" in resp.text


def test_new_routes_reject_non_admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"999"})
    with respx.mock:
        log_in(client, discord_id="111")
        assert client.get("/admin/actions").status_code == 403
        assert client.get("/admin/users/222/impact").status_code == 403
        assert client.get("/admin/notifications/broadcast-status").status_code == 403
        assert client.post("/admin/actions/1/undo", data={}).status_code == 403
        assert client.post("/admin/raids/save", data={"old_name": "종막", "name": "x", "short_name": "x", "category": "카제로스"}).status_code == 403


# ── 레이드: 마스터-디테일 ──────────────────────────────────

def test_raids_page_lists_by_category_and_selects_first(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids()
        resp = client.get("/admin/raids")
    body = resp.text
    assert 'data-key="종막"' in body and 'data-key="세르카"' in body
    assert 'id="raid-editor" data-raid="종막"' in body  # 선택 없으면 첫 레이드
    assert "고정" in body  # 고정 칩
    assert 'value="종막"' in body  # 기본 정보 폼


def test_raids_page_selects_raid_from_query_and_ignores_unknown(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids()
        picked = client.get("/admin/raids?raid=세르카")
        unknown = client.get("/admin/raids?raid=없는레이드")
    assert 'id="raid-editor" data-raid="세르카"' in picked.text
    assert 'id="raid-editor" data-raid="종막"' in unknown.text


def test_difficulty_table_has_clear_gold_column_with_unset_state(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids()
        resp = client.get("/admin/raids?raid=종막")
    body = resp.text
    assert "클리어 골드" in body
    assert "1,500" in body  # difficulty_gold 맵에서
    assert "2,300" in body  # 난이도 객체의 clear_gold에서
    assert 'data-clear-gold="1500"' in body and 'data-clear-gold="2300"' in body
    assert "4인 × 2파티" in body


def test_difficulty_without_gold_shows_unset(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids()
        resp = client.get("/admin/raids?raid=세르카")
    assert "미입력" in resp.text and "분할 없음" in resp.text


def test_delete_is_disabled_with_reason_when_live_parties_exist(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids({**REFS, "parties_live": 2})
        resp = client.get("/admin/raids?raid=종막")
    assert "진행 중인 공대가 2개 있어 삭제할 수 없습니다" in resp.text
    assert 'class="btn sm danger" disabled' in resp.text


def test_delete_is_enabled_without_live_parties(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids()
        resp = client.get("/admin/raids?raid=종막")
    assert "진행 중인 공대가 0개" not in resp.text
    assert 'action="/admin/raids/delete"' in resp.text and 'class="btn sm danger" disabled' not in resp.text


def test_rename_confirm_message_carries_cascade_counts(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids()
        resp = client.get("/admin/raids?raid=종막")
    assert "공대 2개, 이력 12건, 클리어 기록 88건, DM 구독 3건이 새 이름으로 바뀝니다" in resp.text
    assert 'data-confirm-skip-same="name"' in resp.text


def test_raids_page_renders_when_references_endpoint_fails(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_raids(refs=None)
        resp = client.get("/admin/raids?raid=종막")
    assert resp.status_code == 200
    assert "관련 기록이 모두 새 이름으로 바뀝니다" in resp.text  # 건수 없이도 확인 문구


def test_save_raid_renames_updates_and_moves_in_order(client, monkeypatch, notification_db):
    asyncio.run(notification_store.add_raid_filter("111", "종막", "노말"))
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        rename = respx.post(f"{A}/raids/rename").mock(return_value=httpx.Response(200, json={"success": True}))
        update = respx.post(f"{A}/raids/update").mock(return_value=httpx.Response(200, json={"success": True}))
        move = respx.post(f"{A}/raids/move-category").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/save", data={
            "old_name": "종막", "name": " 종막 개정 ", "short_name": "개정", "icon": "🔥", "category": "익스트림",
        })
    assert resp.status_code == 303
    assert without_toast(resp.headers["location"]) == "/admin/raids?raid=%EC%A2%85%EB%A7%89%20%EA%B0%9C%EC%A0%95"
    assert _payload(rename) == {"discord_id": "111", "old_name": "종막", "new_name": "종막 개정"}
    assert _payload(update) == {"discord_id": "111", "name": "종막 개정", "short_name": "개정", "icon": "🔥"}  # 새 이름으로
    assert _payload(move) == {"discord_id": "111", "name": "종막 개정", "category": "익스트림"}
    assert asyncio.run(notification_store.get_preferences("111"))["raid_filters"][0]["raid_name"] == "종막 개정"


def test_save_raid_sends_only_changed_parts(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        rename = respx.post(f"{A}/raids/rename").mock(return_value=httpx.Response(200, json={"success": True}))
        update = respx.post(f"{A}/raids/update").mock(return_value=httpx.Response(200, json={"success": True}))
        move = respx.post(f"{A}/raids/move-category").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/save", data={
            "old_name": "종막", "name": "종막", "short_name": "종막2", "icon": "⚔️", "category": "카제로스",
        })
    assert resp.status_code == 303
    assert rename.call_count == 0 and move.call_count == 0 and update.call_count == 1
    assert toast_of(resp.headers["location"]) == ("저장했습니다.", "success")


def test_save_raid_stops_and_reports_when_rename_is_rejected(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(RAIDS_URL).mock(return_value=httpx.Response(200, json=RAIDS))
        respx.post(f"{A}/raids/rename").mock(return_value=httpx.Response(200, json={"success": False, "reason": "이미 있는 이름입니다."}))
        update = respx.post(f"{A}/raids/update").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/save", data={
            "old_name": "종막", "name": "세르카", "short_name": "x", "icon": "⚔️", "category": "카제로스",
        })
    assert toast_of(resp.headers["location"]) == ("이미 있는 이름입니다.", "error")
    assert update.call_count == 0


def test_save_difficulty_renames_then_updates_with_clear_gold(client, monkeypatch, notification_db):
    asyncio.run(notification_store.add_raid_filter("111", "종막", "노말"))
    with respx.mock:
        _admin(client, monkeypatch)
        rename = respx.post(f"{A}/difficulties/rename").mock(return_value=httpx.Response(200, json={"success": True}))
        update = respx.post(f"{A}/difficulties/update").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/difficulties/save", data={
            "raid_name": "종막", "old_difficulty": "노말", "difficulty": "일반", "min_level": "1710", "total_slots": "8",
            "party_split": "4", "gates": "2", "clear_gold": "1,500",
        })
    assert without_toast(resp.headers["location"]) == "/admin/raids?raid=%EC%A2%85%EB%A7%89"
    assert _payload(rename)["new_difficulty"] == "일반"
    assert _payload(update) == {
        "discord_id": "111", "raid_name": "종막", "difficulty": "일반", "min_level": 1710, "total_slots": 8,
        "party_split": 4, "gates": 2, "clear_gold": 1500,
    }
    assert asyncio.run(notification_store.get_preferences("111"))["raid_filters"][0]["difficulty"] == "일반"


def test_save_difficulty_blank_gold_sends_null_and_bad_gold_is_rejected(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        update = respx.post(f"{A}/difficulties/update").mock(return_value=httpx.Response(200, json={"success": True}))
        ok = client.post("/admin/raids/difficulties/save", data={
            "raid_name": "종막", "old_difficulty": "노말", "difficulty": "노말", "min_level": "1710", "total_slots": "8",
            "party_split": "", "gates": "2", "clear_gold": "",
        })
        bad = client.post("/admin/raids/difficulties/save", data={
            "raid_name": "종막", "old_difficulty": "노말", "difficulty": "노말", "min_level": "1710", "total_slots": "8",
            "party_split": "", "gates": "2", "clear_gold": "많이",
        })
    assert ok.status_code == 303 and update.call_count == 1
    assert _payload(update)["clear_gold"] is None and _payload(update)["party_split"] is None
    assert toast_of(bad.headers["location"])[1] == "error" and "골드" in toast_of(bad.headers["location"])[0]


def test_add_difficulty_forwards_clear_gold(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/difficulties/add").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/difficulties/add", data={
            "raid_name": "종막", "difficulty": "하드", "min_level": "1730", "total_slots": "8", "party_split": "4", "gates": "2", "clear_gold": "2300",
        })
    assert resp.status_code == 303
    assert _payload(route)["clear_gold"] == 2300


def test_order_all_posts_each_changed_category(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/raids/order").mock(return_value=httpx.Response(200, json={"success": True, "count": 2}))
        resp = client.post("/admin/raids/order-all", data={
            "orders": json.dumps({"카제로스": ["세르카", "종막"], "익스트림": ["카멘 익스트림"]}), "return_raid": "종막",
        })
    assert route.call_count == 2
    assert {_payload(route, i)["category"] for i in range(2)} == {"카제로스", "익스트림"}
    assert _payload(route, 0)["order"] == ["세르카", "종막"]
    assert without_toast(resp.headers["location"]) == "/admin/raids?raid=%EC%A2%85%EB%A7%89"
    assert toast_of(resp.headers["location"])[1] == "success"


def test_order_all_with_nothing_changed_makes_no_bot_call(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/raids/order").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/raids/order-all", data={"orders": "{}"})
    assert route.call_count == 0 and toast_of(resp.headers["location"])[1] == "info"


# ── 공대 ──────────────────────────────────────────────────

PARTY = {
    "message_id": "p1", "channel_id": "5", "guild_id": "g", "leader_id": "111", "raid_name": "종막", "difficulty": "노말",
    "proficiency": "숙련", "scheduled_time": "05/20 20:00", "scheduled_datetime": "2099-05-20T20:00:00+09:00",
    "total_slots": 8, "min_level": 1710, "status": "recruiting", "memo": None,
    "slots": [{"slot_number": 1, "discord_id": "111", "character_name": "리더캐릭", "character_class": "워로드", "role": "dps"}],
}
FORUM = {"forum_channel_id": "700", "forum_channel_name": "공대모집", "channels": [{"id": "700", "name": "공대모집"}]}


def _mock_parties(open_=(PARTY,), closed=()):
    respx.get(f"{A}/parties").mock(return_value=httpx.Response(200, json={"open": list(open_), "closed": list(closed)}))
    respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
    respx.get(f"{A}/forum-channel").mock(return_value=httpx.Response(200, json=FORUM))


def test_parties_table_rows_show_leader_slots_and_row_actions(client, monkeypatch):
    closed_party = {**PARTY, "message_id": "p2", "status": "closed"}
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_parties([PARTY, closed_party])
        resp = client.get("/admin/parties")
    body = resp.text
    assert "리더캐릭" in body and "1/8" in body
    assert 'action="/admin/parties/p1/close"' in body and 'action="/admin/parties/p2/reopen"' in body  # 마감 ↔ 재개
    assert 'action="/admin/parties/p1/reopen"' not in body
    assert body.count('aria-controls="pm-') == 2
    assert 'data-key="problem"' in body and "일정 지남" in body
    assert "#공대모집" in body


def test_closed_tab_offers_revert_only_when_can_revert(client, monkeypatch):
    base = {**PARTY, "status": "disbanded", "is_live": True, "created_at": "2026-05-20T10:00:00"}
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_parties([], [{**base, "message_id": "c1", "can_revert": True}, {**base, "message_id": "c2", "can_revert": False},
                           {**base, "message_id": "c3", "is_live": False, "can_revert": False, "slots": []}])
        resp = client.get("/admin/parties?tab=closed")
    body = resp.text
    assert 'action="/admin/parties/c1/revert-clear"' in body
    assert "/admin/parties/c2/revert-clear" not in body and "/admin/parties/c3/revert-clear" not in body
    assert "/admin/parties/c3/unlock" not in body  # 기록만 남은 공대에는 메뉴 자체가 없다
    assert "기록만 남음" in body


def test_expired_party_gets_its_own_label(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        _mock_parties([], [{**PARTY, "status": "expired", "is_live": True, "can_revert": False, "created_at": "2026-05-20T10:00:00"}])
        resp = client.get("/admin/parties?tab=closed")
    assert "기한 만료" in resp.text


def test_parties_page_renders_when_forum_lookup_fails(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/parties").mock(return_value=httpx.Response(200, json={"open": [PARTY], "closed": []}))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        respx.get(f"{A}/forum-channel").mock(return_value=httpx.Response(500))
        resp = client.get("/admin/parties")
    assert resp.status_code == 200 and "미설정" in resp.text


def test_force_close_and_reopen_from_list_return_to_list(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        close = respx.post(f"{B}/parties/p1/close").mock(return_value=httpx.Response(200, json={"success": True}))
        reopen = respx.post(f"{B}/parties/p1/reopen").mock(return_value=httpx.Response(200, json={"success": False, "reason": "이미 모집중입니다."}))
        a = client.post("/admin/parties/p1/close")
        b = client.post("/admin/parties/p1/reopen")
    assert _payload(close)["discord_id"] == "111"
    assert without_toast(a.headers["location"]) == "/admin/parties" and toast_of(a.headers["location"])[1] == "success"
    assert toast_of(b.headers["location"]) == ("이미 모집중입니다.", "error") and reopen.call_count == 1


def test_revert_clear_and_unlock_from_list_return_to_closed_tab(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        revert = respx.post(f"{A}/parties/p1/revert-clear").mock(return_value=httpx.Response(200, json={"success": True}))
        unlock = respx.post(f"{A}/parties/p1/unlock").mock(return_value=httpx.Response(200, json={"success": True}))
        a = client.post("/admin/parties/p1/revert-clear")
        b = client.post("/admin/parties/p1/unlock")
    assert without_toast(a.headers["location"]) == "/admin/parties?tab=closed" and revert.call_count == 1
    assert without_toast(b.headers["location"]) == "/admin/parties?tab=closed" and unlock.call_count == 1


# ── 유저 ──────────────────────────────────────────────────

USERS = [
    {"discord_id": "222", "registered_at": "2026-05-01T00:00:00", "representative": "리퍼짱", "discord_nick": "ripper",
     "last_sync": "2026-05-02 04:00:00", "character_count": 6},
    {"discord_id": "333", "registered_at": "2026-05-02T00:00:00", "representative": None, "last_sync": None, "character_count": 0},
]


def test_users_table_columns_character_count_and_party_participation(client, monkeypatch):
    party = {**PARTY, "leader_id": "222", "slots": [{"slot_number": 1, "discord_id": "222", "character_name": "리퍼짱", "character_class": "리퍼", "role": "dps"}]}
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/users").mock(return_value=httpx.Response(200, json=USERS))
        respx.get(f"{A}/parties").mock(return_value=httpx.Response(200, json={"open": [party], "closed": []}))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        resp = client.get("/admin/users")
    body = resp.text
    for head in ("유저", "캐릭터", "마지막 활동", "참여 중 공대"):
        assert f"<th>{head}</th>" in body
    assert "@ripper" in body and "(파티장)" in body
    assert 'data-user-kick="222"' in body and 'data-user-kick="333"' in body


def test_users_page_falls_back_to_per_user_character_lookup_when_count_missing(client, monkeypatch):
    users = [{"discord_id": "222", "registered_at": "2026-05-01T00:00:00", "representative": "리퍼짱", "last_sync": "2026-05-02 04:00:00"}]
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/users").mock(return_value=httpx.Response(200, json=users))
        chars = respx.get(f"{A}/users/222/characters").mock(return_value=httpx.Response(200, json=[{"character_name": "a"}, {"character_name": "b"}]))
        respx.get(f"{A}/parties").mock(return_value=httpx.Response(200, json={"open": [], "closed": []}))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        resp = client.get("/admin/users")
    assert chars.call_count == 1
    assert '<td class="num" data-label="캐릭터">2</td>' in resp.text


IMPACT = {
    "characters": 3, "api_keys": 1, "completions_this_week": 4,
    "active_parties": [
        {"message_id": "p1", "raid_name": "종막", "difficulty": "노말", "is_leader": True, "handover_to": {"discord_id": "444", "name": "바드님"}},
        {"message_id": "p2", "raid_name": "세르카", "difficulty": "하드", "is_leader": True, "handover_to": None},
        {"message_id": "p3", "raid_name": "아르모체(4막)", "difficulty": "하드", "is_leader": False, "handover_to": None},
    ],
}


def test_user_impact_fragment_shows_deletions_handover_and_kept_records(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.get(f"{A}/users/333/impact").mock(return_value=httpx.Response(200, json=IMPACT))
        resp = client.get("/admin/users/333/impact")
    body = resp.text
    assert route.calls[0].request.url.params["discord_id"] == "111"
    assert "캐릭터 3개" in body and "API 키 1개" in body
    assert "참여 중 공대에서 자동으로 나감" in body and "3개" in body
    assert "종막 노말" in body and "새 파티장" in body and "바드님" in body
    assert "세르카 하드" in body and "넘길 파티원 없음" in body
    assert "아르모체(4막) 하드" in body  # 파티장이 아닌 공대는 '나가는 공대'
    assert "통계용으로 남김" in body and "4건" in body


def test_user_impact_fragment_degrades_when_endpoint_missing(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/users/333/impact").mock(return_value=httpx.Response(404, json={"detail": "x"}))
        resp = client.get("/admin/users/333/impact")
    assert resp.status_code == 200
    assert "봇 서버가 아직 지원하지 않아" in resp.text and "삭제됩니다" in resp.text


def test_kick_posts_to_existing_delete_route_and_toasts(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/users/333/delete").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/users/333/delete")
    assert _payload(route) == {"discord_id": "111"}
    assert without_toast(resp.headers["location"]) == "/admin/users" and toast_of(resp.headers["location"])[1] == "success"


# ── 작업 기록 ─────────────────────────────────────────────

ACTIONS = {"items": [
    {"id": 5, "at": "2099-01-01T00:00:00+09:00", "actor_name": "발키리", "source": "web", "action": "party.force_close",
     "summary": "종막 노말 공대 강제 마감", "undoable": True, "undone_at": None},
    {"id": 4, "at": "2020-11-17T22:10:00+09:00", "actor_name": "리퍼짱", "source": "discord", "action": "party.revert_clear",
     "summary": "세르카 하드 클리어 되돌리기", "undoable": False, "undone_at": None},
    {"id": 3, "at": "2020-11-16T22:10:00+09:00", "actor_name": "발키리", "source": "web", "action": "raid.disable",
     "summary": "레이드 \"종막\" 비활성화", "undoable": True, "undone_at": "2020-11-16T23:00:00+09:00"},
]}


def test_actions_page_lists_rows_and_gates_undo(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.get(f"{A}/actions").mock(return_value=httpx.Response(200, json=ACTIONS))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        resp = client.get("/admin/actions?kind=raid")
    body = resp.text
    assert route.calls[0].request.url.params["kind"] == "raid" and route.calls[0].request.url.params["limit"] == "100"
    for head in ("언제", "누가", "무엇을", "어디서"):
        assert f"<th>{head}</th>" in body
    assert "종막 노말 공대 강제 마감" in body and "디스코드" in body and "웹" in body
    assert body.count('action="/admin/actions/') == 1 and 'action="/admin/actions/5/undo"' in body  # 되돌릴 수 있고 아직 안 되돌린 줄만
    assert "되돌릴 수 없음" in body and "되돌림" in body
    assert "kind=party" in body  # 종류 칩


def test_actions_page_unknown_kind_falls_back_to_all(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.get(f"{A}/actions").mock(return_value=httpx.Response(200, json={"items": []}))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        resp = client.get("/admin/actions?kind=hack")
    assert route.calls[0].request.url.params["kind"] == "all"
    assert "아직 기록이 없습니다" in resp.text


def test_actions_page_shows_muted_notice_when_bot_has_no_endpoint(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/actions").mock(return_value=httpx.Response(404, json={"detail": "Not Found"}))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        resp = client.get("/admin/actions")
    assert resp.status_code == 200
    assert "작업 기록을 불러오지 못했습니다" in resp.text and "아직 지원하지 않거나" in resp.text


def test_undo_posts_and_returns_to_same_filter(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/actions/5/undo").mock(return_value=httpx.Response(200, json={"success": True, "reason": None}))
        resp = client.post("/admin/actions/5/undo", data={"kind": "party"})
    assert _payload(route) == {"discord_id": "111"}
    assert without_toast(resp.headers["location"]) == "/admin/actions?kind=party"
    assert toast_of(resp.headers["location"]) == ("되돌렸습니다.", "success")


def test_undo_failure_shows_reason_and_missing_endpoint_is_explained(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.post(f"{A}/actions/5/undo").mock(return_value=httpx.Response(200, json={"success": False, "reason": "이미 다른 상태로 바뀌었습니다."}))
        respx.post(f"{A}/actions/6/undo").mock(return_value=httpx.Response(404, json={"detail": "x"}))
        failed = client.post("/admin/actions/5/undo", data={"kind": "all"})
        missing = client.post("/admin/actions/6/undo", data={"kind": "all"})
    assert toast_of(failed.headers["location"]) == ("이미 다른 상태로 바뀌었습니다.", "error")
    assert toast_of(missing.headers["location"]) == ("봇 서버가 아직 이 기능을 지원하지 않습니다.", "error")


# ── 알림·구독 ─────────────────────────────────────────────

def test_broadcast_tab_shows_recipients_preview_and_hidden_progress(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        respx.get(f"{A}/notify-all/status").mock(return_value=httpx.Response(200, json={}))
        resp = client.get("/admin/notifications?tab=broadcast")
    body = resp.text
    assert 'data-recipients="22"' in body and "수신 대상" in body
    assert 'id="bc-preview"' in body and "미리보기" in body
    assert 'id="bc-progress" aria-live="polite" hidden' in body


def test_broadcast_tab_resumes_progress_when_a_broadcast_is_running(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        respx.get(f"{A}/notify-all/status").mock(return_value=httpx.Response(200, json={"sent": 8, "total": 22, "done": False}))
        resp = client.get("/admin/notifications?tab=broadcast")
    import re
    tag = re.search(r'<div class="ad-progress"[^>]*>', resp.text).group(0)
    assert 'data-running="1"' in tag and "hidden" not in tag
    assert "36%" in resp.text  # 8/22


def test_broadcast_json_reports_queued_and_rejection_reason(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/notify-all").mock(side_effect=[
            httpx.Response(200, json={"success": True, "queued": True, "total": 22, "sent": 0}),
            httpx.Response(200, json={"success": False, "reason": "같은 내용의 공지를 10분 안에 이미 보냈습니다."}),
        ])
        queued = client.post("/admin/notifications/broadcast", data={"content": " 점검 "}, headers={"Accept": "application/json"})
        dup = client.post("/admin/notifications/broadcast", data={"content": " 점검 "}, headers={"Accept": "application/json"})
    assert _payload(route)["content"] == "점검"
    assert queued.json() == {"success": True, "reason": None, "queued": True, "sent": 0, "total": 22}
    assert dup.json()["success"] is False and "10분 안에" in dup.json()["reason"]


def test_broadcast_form_post_queued_redirects_with_in_progress_toast(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.post(f"{A}/notify-all").mock(return_value=httpx.Response(200, json={"success": True, "queued": True, "total": 22}))
        resp = client.post("/admin/notifications/broadcast", data={"content": "x"})
    assert "tab=broadcast" in resp.headers["location"]
    assert "22명에게 보내는 중" in toast_of(resp.headers["location"])[0]


def test_broadcast_duplicate_rejection_is_an_error_toast_for_form_posts(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.post(f"{A}/notify-all").mock(return_value=httpx.Response(200, json={"success": False, "reason": "같은 내용의 공지를 10분 안에 이미 보냈습니다."}))
        resp = client.post("/admin/notifications/broadcast", data={"content": "x"})
    assert toast_of(resp.headers["location"]) == ("같은 내용의 공지를 10분 안에 이미 보냈습니다.", "error")


def test_broadcast_status_proxy_returns_progress_json(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/notify-all/status").mock(return_value=httpx.Response(200, json={"sent": 22, "total": 22, "done": True}))
        done = client.get("/admin/notifications/broadcast-status")
        respx.get(f"{A}/notify-all/status").mock(return_value=httpx.Response(200, json={}))
        none = client.get("/admin/notifications/broadcast-status")
    assert done.json() == {"sent": 22, "total": 22, "done": True, "active": True}
    assert none.json()["active"] is False


def test_tracked_items_tab_lists_names_and_unresolved(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        respx.get(f"{A}/loa/tracked-items").mock(return_value=httpx.Response(200, json={"names": ["운명의 파괴석 결정", "없는 아이템"]}))
        resp = client.get("/admin/notifications?tab=items&unresolved=" + "없는 아이템")
    body = resp.text
    assert 'value="운명의 파괴석 결정"' in body and 'value="없는 아이템"' in body
    assert "시세에서 못 찾음" in body and "최대 8개" in body


def test_tracked_items_tab_shows_notice_when_endpoint_missing(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        respx.get(f"{A}/loa/tracked-items").mock(return_value=httpx.Response(404, json={"detail": "x"}))
        resp = client.get("/admin/notifications?tab=items")
    assert resp.status_code == 200 and "아직 시세 아이템 설정을 지원하지 않아" in resp.text
    assert 'id="tracked-form"' not in resp.text


def test_set_tracked_items_dedupes_posts_and_reports_unresolved(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/loa/tracked-items").mock(return_value=httpx.Response(
            200, json={"success": True, "names": ["a", "b"], "unresolved": ["b"]}))
        resp = client.post("/admin/notifications/items", data={"names": [" a ", "b", "a", ""]})
    assert _payload(route) == {"discord_id": "111", "names": ["a", "b"]}
    loc = resp.headers["location"]
    assert "tab=items" in loc and "unresolved=b" in loc
    assert toast_of(loc)[1] == "info" and "1개" in toast_of(loc)[0]


def test_set_tracked_items_rejects_more_than_eight_without_calling_bot(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        route = respx.post(f"{A}/loa/tracked-items").mock(return_value=httpx.Response(200, json={"success": True}))
        resp = client.post("/admin/notifications/items", data={"names": [f"item{i}" for i in range(9)]})
    assert route.call_count == 0
    assert toast_of(resp.headers["location"]) == ("시세로 볼 아이템은 최대 8개입니다.", "error")


# ── 직업 / 통계 / 클리어: 새 틀에서도 그려진다 ──────────────

def test_classes_page_has_role_chips_table_and_add_dialog(client, monkeypatch):
    with respx.mock:
        _admin(client, monkeypatch)
        respx.get(f"{B}/job-classes").mock(return_value=httpx.Response(200, json=[{"name": "바드", "is_support": 1}, {"name": "리퍼", "is_support": 0}]))
        respx.get(f"{A}/status").mock(return_value=httpx.Response(200, json=STATUS))
        resp = client.get("/admin/classes")
    body = resp.text
    assert 'data-ad-role="support"' in body and 'data-role="support"' in body and 'data-role="dps"' in body
    assert 'id="class-table"' in body and 'id="dlg-class-add"' in body and 'action="/admin/classes/add"' in body
