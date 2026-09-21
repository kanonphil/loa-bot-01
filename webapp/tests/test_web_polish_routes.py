"""웹 기능 보강 묶음 — 이용 가이드, 지난 주차 클리어 기록, 공대 이력 멤버, 익스트림 운영 종료 D-day,
초대 만료 카운트다운, 원정대 마지막 동기화, 검색창, 댓글 htmx 부분 갱신, 레이드 체크 토글 토스트."""
from datetime import datetime, timedelta, timezone

import httpx
import respx

from webapp.format import KST, invite_expiry_view, period_view
from webapp.tests.conftest import log_in

B = "http://bot-server.internal/api/internal"

RAIDS = {
    "아르모체(4막)": {
        "short_name": "4막", "icon": "🗡️", "category": "카제로스", "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    "익스트림": {
        "short_name": "익스", "icon": "🔥", "category": "익스트림", "is_extreme": True, "is_active": True,
        "available_from": "2026-01-01T00:00:00+09:00",
        "available_until": (datetime.now(KST) + timedelta(days=2)).isoformat(),  # 날짜 차이가 항상 2일
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
}
PARTY = {
    "message_id": "p1", "channel_id": "555", "guild_id": "test-guild-id", "leader_id": "222",
    "raid_name": "익스트림", "difficulty": "노말", "proficiency": "숙련",
    "scheduled_time": "05/20 20:00", "scheduled_datetime": "2099-05-20T20:00:00+09:00",
    "total_slots": 8, "min_level": 1700, "status": "recruiting", "memo": None,
    "slots": [{"slot_number": 1, "discord_id": "222", "character_name": "워로드캐릭", "character_class": "워로드", "role": "dps"}],
}


# ── format 헬퍼 ────────────────────────────────────────────

def test_period_view_counts_days_and_warns_near_end():
    now = datetime(2026, 5, 20, 12, tzinfo=KST)
    assert period_view("2026-05-23T06:00:00+09:00", now) == {"label": "운영 종료 D-3", "tone": "warn", "days": 3, "is_past": False}
    assert period_view("2026-05-30T06:00:00+09:00", now)["tone"] == ""
    assert period_view("2026-05-20T23:00:00+09:00", now)["label"] == "오늘 운영 종료"
    assert period_view("2026-05-19T06:00:00+09:00", now)["is_past"] is True
    assert period_view(None, now) is None


def test_invite_expiry_view_counts_down_from_naive_utc():
    now = datetime(2026, 5, 20, 10, 30, tzinfo=timezone.utc)
    assert invite_expiry_view("2026-05-20T10:00:00", now=now) == {"label": "만료까지 30분", "tone": "", "minutes": 30}
    assert invite_expiry_view("2026-05-20T09:40:00", now=now)["tone"] == "warn"  # 10분 남음
    assert invite_expiry_view("2026-05-20T08:00:00", now=now)["label"] == "곧 만료"
    assert invite_expiry_view(None) is None


# ── 이용 가이드 ────────────────────────────────────────────

def test_guide_is_public_and_links_login(client):
    resp = client.get("/guide")
    assert resp.status_code == 200
    assert "API 키 발급" in resp.text
    assert 'href="/login"' in resp.text


def test_guide_for_logged_in_user_hides_login_button(client):
    with respx.mock:
        log_in(client)
        resp = client.get("/guide")
    assert resp.status_code == 200
    assert "이용 가이드" in resp.text
    assert "주차별 클리어 기록" in resp.text


def test_landing_page_links_guide(client):
    resp = client.get("/")
    assert 'href="/guide"' in resp.text


# ── 지난 주차 클리어 기록 ─────────────────────────────────────

def test_raid_check_history_lists_weeks_and_characters(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/completions/weeks").mock(return_value=httpx.Response(200, json={"current_week": "2026-05-13", "weeks": ["2026-05-13", "2026-05-06"]}))
        week_route = respx.get(f"{B}/completions/week").mock(return_value=httpx.Response(200, json={
            "week_key": "2026-05-06",
            "characters": [{"character_name": "발키리", "character_class": "홀리나이트",
                            "completions": [{"raid_name": "아르모체(4막)", "difficulty": "노말"}, {"raid_name": "종막", "difficulty": "하드"}]}],
        }))
        resp = client.get("/raid-check/history?week=2026-05-06")

    assert resp.status_code == 200
    body = resp.text
    assert week_route.calls[0].request.url.params["week_key"] == "2026-05-06"
    assert "5/6(수) ~ 5/12(화)" in body
    assert "(이번 주)" in body
    assert "발키리" in body and "2개 클리어" in body
    assert "종막 하드" in body


def test_raid_check_history_falls_back_to_current_week_for_unknown_key(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/completions/weeks").mock(return_value=httpx.Response(200, json={"current_week": "2026-05-13", "weeks": ["2026-05-13"]}))
        week_route = respx.get(f"{B}/completions/week").mock(return_value=httpx.Response(200, json={"week_key": "2026-05-13", "characters": []}))
        resp = client.get("/raid-check/history?week=1999-01-01")

    assert week_route.calls[0].request.url.params["week_key"] == "2026-05-13"
    assert "이번 주 기록이 아직 없습니다" in resp.text


def test_raid_check_page_links_history_and_shows_saved_toast(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/raid-check?saved=1")
    assert 'href="/raid-check/history"' in resp.text
    assert "레이드 선택을 저장했습니다" in resp.text


def test_raid_check_toggle_sends_toast_header(client):
    characters = [{"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0}]
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/raid-categories").mock(return_value=httpx.Response(200, json=[{"name": "카제로스", "sort_order": 0, "is_extreme": 0}, {"name": "익스트림", "sort_order": 1, "is_extreme": 1}]))
        respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=characters))
        respx.get(f"{B}/raid-selection").mock(return_value=httpx.Response(200, json={"customized": False, "selected_raids": []}))
        respx.get(f"{B}/completions").mock(return_value=httpx.Response(200, json={"week_key": "w", "completions": ["아르모체(4막)_노말"]}))
        respx.post(f"{B}/completions/toggle").mock(return_value=httpx.Response(200, json={"completed": True}))
        resp = client.post("/raid-check/toggle", data={"raid_name": "아르모체(4막)", "difficulty": "노말", "character_name": "발키리", "card_index": "0"})

    assert resp.status_code == 200
    from urllib.parse import unquote
    assert unquote(resp.headers["X-Toast"]) == "발키리 · 4막 노말 완료 체크"
    assert resp.headers["X-Toast-Type"] == "success"


# ── 공대 이력: 함께한 멤버 ────────────────────────────────────

def test_history_shows_members_and_memo(client):
    entries = [{
        "message_id": "p1", "raid_name": "카멘", "difficulty": "노말", "proficiency": "숙련",
        "scheduled_time": "05/20 20:00", "status": "disbanded", "character_name": "워로드캐릭", "role": "dps",
        "created_at": "2026-05-20T10:00:00", "total_slots": 8, "memo": "음성 필수", "leader_id": "222",
        "members": [
            {"discord_id": "222", "character_name": "워로드캐릭", "character_class": "워로드", "role": "dps"},
            {"discord_id": "333", "character_name": "바드캐릭", "character_class": "바드", "role": "support"},
        ],
    }]
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(f"{B}/user-party-history").mock(return_value=httpx.Response(200, json={"entries": entries, "has_more": False, "total_count": 1}))
        resp = client.get("/parties/history")

    body = resp.text
    assert "함께한 멤버 2/8" in body
    assert "바드캐릭" in body and "음성 필수" in body
    assert "파티장" in body


# ── 익스트림 운영 종료 D-day ──────────────────────────────────

def test_party_list_and_detail_show_period_chip(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=[PARTY]))
        respx.get(f"{B}/user-characters").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        list_resp = client.get("/parties")

        respx.get(f"{B}/parties/p1").mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(f"{B}/parties/p1/comments").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{B}/parties/p1/eligibility").mock(return_value=httpx.Response(200, json={"can_join": False, "reason": "x"}))
        respx.get(f"{B}/parties/p1/waitlist-status").mock(return_value=httpx.Response(200, json={"on_waitlist": False, "count": 0}))
        detail_resp = client.get("/parties/p1")

    assert "운영 종료 D-2" in list_resp.text
    assert "운영 종료 D-2" in detail_resp.text


# ── 초대 만료 카운트다운 + 검색 ─────────────────────────────────

def test_invites_page_shows_expiry_and_search(client):
    sent = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S")
    invite = {
        "message_id": "700", "slot_number": 3, "invited_at": sent,
        "raid_name": "아르모체(4막)", "difficulty": "노말", "proficiency": "숙련",
        "scheduled_time": "05/20 20:00", "scheduled_datetime": "2099-05-20T20:00:00+09:00",
        "leader_id": "111", "min_level": 1700, "status": "recruiting",
    }
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/my-invites").mock(return_value=httpx.Response(200, json=[invite]))
        respx.get(f"{B}/parties/700/eligibility").mock(return_value=httpx.Response(200, json={"can_join": False, "reason": "x"}))
        resp = client.get("/invites")

    body = resp.text
    assert "만료까지 " in body
    assert 'data-filter-target="#invite-list"' in body


# ── 원정대: 마지막 동기화 / 검색 ─────────────────────────────

def test_expedition_shows_last_sync_and_search_for_many_characters(client):
    cached = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
    chars = [
        {"character_name": f"캐릭{i}", "character_class": "워로드", "item_level": 1700.0, "account_label": "본계정", "cached_at": cached}
        for i in range(6)
    ]
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=chars))
        respx.get(f"{B}/accounts/list").mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/expedition")

    body = resp.text
    assert "마지막 동기화 3시간 전" in body
    assert "매일 04시" in body
    assert 'data-filter-target="#expedition-groups"' in body


def test_expedition_hides_search_for_few_characters(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=[
            {"character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "account_label": "본계정"},
        ]))
        respx.get(f"{B}/accounts/list").mock(return_value=httpx.Response(200, json=[]))
        resp = client.get("/expedition")
    assert 'data-filter-target="#expedition-groups"' not in resp.text


# ── 랭킹 검색 / 모바일 탭 ────────────────────────────────────

def test_ranking_has_search_and_bottom_tabs_include_invites(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/ranking").mock(return_value=httpx.Response(200, json={"metric": "combat_power", "entries": [
            {"discord_id": "111", "character_name": "발키리", "character_class": "홀리나이트", "item_level": 1720.0, "combat_power": 1, "value": 1},
        ]}))
        resp = client.get("/ranking")
    body = resp.text
    assert 'data-filter-target="#rank-table"' in body
    assert 'data-badge="invites"' in body.split('class="bottom-tabs"')[1]
    assert 'href="/guide"' in body


# ── 댓글 htmx 부분 갱신 ──────────────────────────────────────

def test_post_comment_via_htmx_returns_partial(client):
    comments = [{"id": 1, "discord_id": "111", "author_name": "나", "content": "새 댓글", "source": "web", "created_at": "2026-05-19T19:02:00"}]
    with respx.mock:
        log_in(client, discord_id="111", username="나")
        respx.post(f"{B}/parties/p1/comments").mock(return_value=httpx.Response(200, json={"success": True, "relayed": True}))
        respx.get(f"{B}/parties/p1").mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(f"{B}/parties/p1/comments").mock(return_value=httpx.Response(200, json=comments))
        resp = client.post("/parties/p1/comments", data={"content": "새 댓글"}, headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert 'id="party-comments"' in resp.text
    assert "새 댓글" in resp.text
    assert "<html" not in resp.text
    assert "X-Toast" not in resp.headers


def test_post_comment_via_htmx_failure_sets_toast_header(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(f"{B}/parties/p1/comments").mock(return_value=httpx.Response(200, json={"success": False, "reason": "이미 종료된 공대라 댓글을 남길 수 없습니다."}))
        respx.get(f"{B}/parties/p1").mock(return_value=httpx.Response(200, json={**PARTY, "status": "disbanded"}))
        respx.get(f"{B}/parties/p1/comments").mock(return_value=httpx.Response(200, json=[]))
        resp = client.post("/parties/p1/comments", data={"content": "x"}, headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert resp.headers["X-Toast-Type"] == "error"
    assert 'action="/parties/p1/comments"' not in resp.text  # 종료된 공대엔 입력 폼 없음


def test_delete_comment_via_htmx_returns_partial(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.post(f"{B}/parties/p1/comments/1/delete").mock(return_value=httpx.Response(200, json={"success": True}))
        respx.get(f"{B}/parties/p1").mock(return_value=httpx.Response(200, json=PARTY))
        respx.get(f"{B}/parties/p1/comments").mock(return_value=httpx.Response(200, json=[]))
        resp = client.post("/parties/p1/comments/1/delete", headers={"HX-Request": "true"})

    assert resp.status_code == 200
    assert "아직 댓글이 없습니다" in resp.text
