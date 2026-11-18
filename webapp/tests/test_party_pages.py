"""공대 화면 재구성 검증 — 개설 안내 API, 다시 열기 칩, 목록의 참여 칸, 상세의 상단 줄·멤버 메뉴·끝난 공대, 달력·이력의 기한 만료."""
from datetime import datetime, timedelta

import httpx
import respx

from webapp.format import KST
from webapp.tests.conftest import log_in

B = "http://bot-server.internal/api/internal"
NOW = datetime.now(KST)

RAIDS = {
    "종막": {
        "short_name": "종막", "icon": "x", "category": "카제로스", "is_extreme": False, "is_active": True,
        "available_from": None, "available_until": None, "sort_order": 0,
        "difficulties": {"노말": {"min_level": 1710, "total_slots": 8, "party_split": 4, "gates": 2}},
    },
    "카멘 익스트림": {
        "short_name": "익스", "icon": "x", "category": "익스트림", "is_extreme": True, "is_active": True,
        "available_from": None, "available_until": (NOW + timedelta(days=10)).isoformat(), "sort_order": 1,
        "difficulties": {"노말": {"min_level": 1700, "total_slots": 8, "party_split": 4, "gates": 1}},
    },
}


def summary(chars, extreme_cleared=False):
    return {
        "week_key": "w", "raids": RAIDS, "categories": [], "support_classes": ["바드"],
        "extreme": [{"raid_name": "카멘 익스트림", "cleared": extreme_cleared}],
        "characters": [
            {"character_name": n, "character_class": c, "item_level": lv, "is_support": sup, "completions": list(done),
             "selection": {"customized": False, "selected_raids": []}, "applicable_raids": [], "visible_raid_names": [],
             "done_count": 0, "total_slots": 0}
            for n, c, lv, sup, done in chars
        ],
    }


def party(mid="p1", raid="종막", when=None, slots=(), status="recruiting", **extra):
    when = when or NOW + timedelta(days=1)
    return {
        "message_id": mid, "channel_id": "c", "guild_id": "g", "leader_id": "222", "raid_name": raid, "difficulty": "노말",
        "proficiency": "숙련", "scheduled_time": when.strftime("%m/%d %H:%M"), "scheduled_datetime": when.isoformat(),
        "total_slots": 8, "min_level": 1710, "status": status, "memo": None, "slots": list(slots), "created_at": NOW.isoformat(), **extra,
    }


def slot(n, did, name, role="dps", cls="워로드", guest=False):
    return {"slot_number": n, "discord_id": did, "character_name": name, "character_class": cls, "role": role, "is_guest": guest}


# ── 개설 안내 API ─────────────────────────────────────────

def _check(client, **params):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=params.pop("parties", [])))
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(200, json=params.pop("summ", summary([("발키리", "바드", 1740.0, True, [])]))))
        return client.get("/parties/create/check", params=params)


def test_create_check_warns_when_time_is_after_next_reset(client):
    from webapp.format import next_reset

    after = (next_reset() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    before = (next_reset() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M")
    assert _check(client, raid_name="종막", difficulty="노말", scheduled_datetime=after).json()["reset"]["next_week"] is True
    assert _check(client, raid_name="종막", difficulty="노말", scheduled_datetime=before).json()["reset"]["next_week"] is False


def test_create_check_reports_duplicate_within_an_hour(client):
    when = NOW + timedelta(days=1)
    near = party("dup", when=when + timedelta(minutes=30), slots=[slot(1, "222", "파티장캐릭")])
    data = _check(client, raid_name="종막", difficulty="노말", scheduled_datetime=when.strftime("%Y-%m-%dT%H:%M"), parties=[near]).json()
    assert [d["message_id"] for d in data["duplicates"]] == ["dup"]
    assert data["duplicates"][0]["leader"] == "파티장캐릭" and data["duplicates"][0]["filled"] == 1
    far = party("far", when=when + timedelta(hours=3))
    data = _check(client, raid_name="종막", difficulty="노말", scheduled_datetime=when.strftime("%Y-%m-%dT%H:%M"), parties=[far]).json()
    assert data["duplicates"] == []


def test_create_check_recommends_and_explains(client):
    when = (NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    summ = summary([("완료", "워로드", 1745.0, False, ["종막_노말"]), ("낮음", "워로드", 1700.0, False, []), ("서포터", "바드", 1720.0, True, [])])
    data = _check(client, raid_name="종막", difficulty="노말", scheduled_datetime=when, summ=summ).json()
    by_name = {o["name"]: o for o in data["options"]}
    assert data["options"][0]["name"] == "서포터" and data["options"][0]["recommended"]
    assert by_name["완료"]["reason"] == "이번 주 완료"
    assert by_name["낮음"]["reason"] == "레벨 1710 필요"


def test_create_check_degrades_without_summary(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(500))
        data = client.get("/parties/create/check", params={"raid_name": "종막", "difficulty": "노말", "scheduled_datetime": ""}).json()
    assert data["has_summary"] is False and data["options"] == []


def _check_subs(client, subs_response, **params):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(200, json=summary([])))
        route = respx.get(f"{B}/raid-subscribers-count").mock(return_value=subs_response)
        data = client.get("/parties/create/check", params=params).json()
    return data, route


def test_create_check_reports_subscriber_count(client):
    when = (NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    data, route = _check_subs(client, httpx.Response(200, json={"count": 3}),
                              raid_name="종막", difficulty="노말", scheduled_datetime=when)
    assert data["subscribers"] == 3
    q = route.calls[0].request.url.params
    assert q["raid_name"] == "종막" and q["difficulty"] == "노말" and q["discord_id"] == "111" and q["scheduled_datetime"] == when


def test_create_check_subscribers_null_on_bot_error_or_no_raid(client):
    data, _ = _check_subs(client, httpx.Response(500), raid_name="종막", difficulty="노말", scheduled_datetime="")
    assert data["subscribers"] is None
    when = (NOW + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
    data, route = _check_subs(client, httpx.Response(200, json={"count": 3}), raid_name="", difficulty="", scheduled_datetime=when)
    assert data["subscribers"] is None and not route.called


def test_create_form_has_subscriber_preview_line(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/parties/proficiency-options").mock(return_value=httpx.Response(200, json=[{"value": "숙련", "label": "숙련", "description": ""}]))
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(200, json=summary([])))
        respx.get(f"{B}/user-party-history").mock(return_value=httpx.Response(200, json={"entries": [], "has_more": False, "total_count": 0}))
        body = client.get("/parties/create").text
    assert 'id="prev-subs" data-default="열면 이 레이드 구독자에게 DM이 갑니다"' in body


# ── 다시 열기 ─────────────────────────────────────────────

def test_create_form_offers_recent_openings_as_reopen_chips(client):
    entries = [
        {"message_id": "h1", "raid_name": "종막", "difficulty": "노말", "proficiency": "반숙", "scheduled_time": "11/14 22:00",
         "status": "disbanded", "leader_id": "111", "memo": "음성 필수"},
        {"message_id": "h2", "raid_name": "종막", "difficulty": "노말", "proficiency": "숙련", "scheduled_time": "11/07 21:00",
         "status": "disbanded", "leader_id": "111"},  # 같은 레이드·난이도 → 한 번만
        {"message_id": "h3", "raid_name": "종막", "difficulty": "노말", "proficiency": "숙련", "scheduled_time": "11/08 21:00",
         "status": "disbanded", "leader_id": "999"},  # 남이 연 공대는 제외
        {"message_id": "h4", "raid_name": "사라진레이드", "difficulty": "노말", "proficiency": "숙련", "scheduled_time": "11/09 21:00",
         "status": "disbanded", "leader_id": "111"},
    ]
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/parties/proficiency-options").mock(return_value=httpx.Response(200, json=[{"value": "숙련", "label": "숙련", "description": ""}, {"value": "반숙", "label": "반숙", "description": ""}]))
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(200, json=summary([("발키리", "바드", 1740.0, True, [])])))
        respx.get(f"{B}/user-party-history").mock(return_value=httpx.Response(200, json={"entries": entries, "has_more": False, "total_count": 4}))
        resp = client.get("/parties/create")
    assert resp.text.count("data-reopen") == 1
    assert 'data-prof="반숙"' in resp.text and 'data-memo="음성 필수"' in resp.text
    assert "종막 노말 · 토 22:00 · 반숙" in resp.text  # 11/14는 토요일 — 요일·시각만 따라간다


def test_create_form_still_renders_when_history_and_summary_fail(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/parties/proficiency-options").mock(return_value=httpx.Response(200, json=[{"value": "숙련", "label": "숙련", "description": ""}]))
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(500))
        respx.get(f"{B}/user-party-history").mock(return_value=httpx.Response(500))
        respx.get(f"{B}/user-characters-grouped").mock(return_value=httpx.Response(200, json=[
            {"character_name": "발키리", "character_class": "바드", "item_level": 1740.0, "account_label": "본"}]))
        respx.get(f"{B}/support-classes").mock(return_value=httpx.Response(200, json=["바드"]))
        resp = client.get("/parties/create")
    assert resp.status_code == 200 and "발키리" in resp.text and "data-reopen" not in resp.text


# ── 목록 ──────────────────────────────────────────────────

def _list(client, parties, chars, extreme_cleared=False, query=""):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(f"{B}/parties").mock(return_value=httpx.Response(200, json=parties))
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/raid-check-summary").mock(return_value=httpx.Response(200, json=summary(chars, extreme_cleared)))
        return client.get("/parties" + query)


def test_list_shows_composition_with_missing_support_highlighted(client):
    p = party("a", slots=[slot(1, "222", "파티장"), slot(2, "333", "딜2")])
    resp = _list(client, [p], [("발키리", "바드", 1740.0, True, [])])
    assert "딜 <span class=\"num\">2/6</span>" in resp.text
    assert 'class="pt-warn">폿 <span class="num">0/2</span>' in resp.text


def test_list_join_cell_posts_role_and_group_for_split_party(client):
    p = party("a", slots=[slot(1, "222", "파티장", "dps"), slot(2, "333", "서폿", "support", "바드"), slot(6, "444", "서폿2", "support", "바드")])
    resp = _list(client, [p], [("딜러캐", "워로드", 1745.0, False, []), ("서폿캐", "바드", 1720.0, True, [])])
    assert 'action="/parties/a/join"' in resp.text
    assert 'type="hidden" name="role" value="dps"' in resp.text  # 서포터가 이미 둘이라 딜러 캐릭터(높은 레벨)가 추천
    assert 'data-group="1"' in resp.text  # 서포터가 있는 1파티의 남는 자리부터
    lacking = party("b", slots=[slot(1, "222", "파티장", "dps")])
    resp = _list(client, [lacking], [("딜러캐", "워로드", 1745.0, False, []), ("서폿캐", "바드", 1720.0, True, [])])
    assert 'type="hidden" name="role" value="support"' in resp.text  # 서포터가 부족하면 서포터 캐릭터가 먼저
    assert 'data-group="1"' in resp.text


def test_list_shows_reason_and_waitlist_link_when_nobody_can_join(client):
    p = party("a", slots=[slot(1, "222", "파티장")])
    resp = _list(client, [p], [("발키리", "바드", 1740.0, True, ["종막_노말"])], query="?filter=all")
    assert "모든 캐릭터가 이번 주 완료" in resp.text
    assert "/parties/a#join" in resp.text and "빈자리 알림" in resp.text
    assert 'action="/parties/a/join"' not in resp.text


def test_list_shows_extreme_rule_reason(client):
    p = party("x", raid="카멘 익스트림", slots=[slot(1, "222", "파티장")])
    resp = _list(client, [p], [("발키리", "바드", 1740.0, True, [])], extreme_cleared=True, query="?filter=all")
    assert "원정대 주 1회 · 이미 감" in resp.text
    resp = _list(client, [p], [("발키리", "바드", 1740.0, True, [])], extreme_cleared=False, query="?filter=all")
    assert 'action="/parties/x/join"' in resp.text and "원정대 주 1회" in resp.text


def test_list_marks_full_closed_and_overdue_parties(client):
    full = party("f", slots=[slot(i, str(500 + i), f"c{i}") for i in range(1, 9)], status="full")
    closed = party("c", status="closed")
    late = party("l", when=NOW - timedelta(hours=3), slots=[slot(1, "222", "파티장")])
    resp = _list(client, [full, closed, late], [("발키리", "바드", 1740.0, True, [])], query="?filter=all")
    assert "파티완성" in resp.text and "모집 마감" in resp.text and "일정 지남" in resp.text
    default = _list(client, [full, closed, late], [("발키리", "바드", 1740.0, True, [])])
    assert 'action="/parties/c/join"' not in default.text and 'data-state="closed"' not in default.text  # 기본 필터는 들어갈 수 있는 공대만


def test_list_expired_party_label(client):
    p = party("e", when=NOW - timedelta(days=2), status="expired")
    resp = _list(client, [p], [("발키리", "바드", 1740.0, True, [])], query="?filter=all")
    assert "기한 만료" in resp.text and 'action="/parties/e/join"' not in resp.text


def test_list_page_top_has_subtabs_and_open_button(client):
    resp = _list(client, [], [])
    assert 'class="btn pri pt-open"' in resp.text and "/calendar" in resp.text and "/parties/history" in resp.text


# ── 상세 ──────────────────────────────────────────────────

def _detail(client, p, discord_id="111", invitable=None, eligibility=None, admin=False):
    from webapp import config

    with respx.mock:
        if admin:
            config.ADMIN_DISCORD_IDS = {discord_id}
        log_in(client, discord_id=discord_id)
        if admin:
            client.post("/admin/toggle-mode")
        mid = p["message_id"]
        respx.get(f"{B}/parties/{mid}").mock(return_value=httpx.Response(200, json=p))
        respx.get(f"{B}/parties/{mid}/comments").mock(return_value=httpx.Response(200, json=[]))
        respx.get(f"{B}/raids").mock(return_value=httpx.Response(200, json=RAIDS))
        respx.get(f"{B}/support-classes").mock(return_value=httpx.Response(200, json=["바드"]))
        respx.get(f"{B}/parties/proficiency-options").mock(return_value=httpx.Response(200, json=[{"value": "숙련", "label": "숙련", "description": ""}]))
        respx.get(f"{B}/parties/{mid}/invitable-users").mock(return_value=httpx.Response(200, json=invitable or {"success": True, "users": [], "available_slots": []}))
        respx.get(f"{B}/parties/{mid}/eligibility").mock(return_value=httpx.Response(200, json=eligibility or {"can_join": False, "reason": "사유"}))
        respx.get(f"{B}/parties/{mid}/waitlist-status").mock(return_value=httpx.Response(200, json={"on_waitlist": False}))
        try:
            return client.get(f"/parties/{mid}")
        finally:
            config.ADMIN_DISCORD_IDS = set()


def test_leader_actions_row_member_menus_and_empty_slot_invites(client):
    p = party("p1", leader_id="111", slots=[slot(1, "111", "내캐릭", "support", "바드"), slot(2, "333", "멤버둘")])
    p["leader_id"] = "111"
    resp = _detail(client, p, invitable={"success": True, "users": [{"discord_id": "9", "representative": "후보"}], "available_slots": [3, 5]})
    body = resp.text
    assert "모집 마감" in body and "클리어" in body and 'aria-controls="reschedule-pop"' in body
    assert 'aria-controls="mm-2"' in body and 'aria-controls="mm-1"' not in body  # 본인 줄에는 ⋯ 메뉴가 없다
    assert 'data-confirm-title="멤버둘 님을 내보낼까요?"' in body and 'data-confirm-ok="강제 퇴장"' in body
    assert 'data-confirm-title="멤버둘 님에게 파티장을 넘길까요?"' in body
    assert 'data-invite-slot="3"' in body and 'data-invite-slot="5"' in body and 'data-invite-slot="4"' not in body
    assert "서포터 없음" in body  # 2파티에 서포터가 없다
    assert 'id="party-settings"' in body and "<details" in body


def test_member_sees_seat_summary_and_no_leader_controls(client):
    p = party("p1", slots=[slot(1, "222", "파티장"), slot(2, "111", "나", "dps", "워로드")])
    body = _detail(client, p).text
    assert "내 자리" in body and "1파티 2번" in body and "나가기" in body and "캐릭터·역할 변경" in body
    assert "모집 마감" not in body and "공대 설정" not in body and "data-menu-trigger aria-haspopup=\"menu\" aria-expanded=\"false\" aria-controls=\"mm-" not in body


def test_outsider_gets_join_row_and_empty_slots_preselect_group(client):
    p = party("p1", slots=[slot(1, "222", "파티장")])
    elig = {"can_join": True, "qualifying": [{"name": "발키리", "level": 1740.0, "class": "바드"}], "party_split": 4, "total_slots": 8,
            "gold_done": [], "in_other_party": [], "level_too_low": [], "no_cache": [], "min_level": 1710}
    body = _detail(client, p, eligibility=elig).text
    assert 'id="join-form"' in body and 'name="party_group"' in body and "빈자리 알림 받기" in body
    assert 'data-pick-group="2"' in body  # 빈 자리를 누르면 그 파티로 참여 칸이 채워진다
    assert "초대" not in body.split('id="slot-groups"')[1].split("</details>")[0].replace("게스트 초대", "")


def test_join_row_lists_reasons_when_no_character_qualifies(client):
    p = party("p1", slots=[slot(1, "222", "파티장")])
    elig = {"can_join": True, "qualifying": [], "party_split": 4, "total_slots": 8, "gold_done": ["완료캐"], "in_other_party": ["다른공대캐"],
            "level_too_low": [{"name": "낮은캐", "level": 1600.0}], "no_cache": [], "min_level": 1710}
    body = _detail(client, p, eligibility=elig).text
    assert "참여할 수 있는 캐릭터가 없습니다" in body and "이번 주 완료: 완료캐" in body and "레벨 1710 필요: 낮은캐" in body


def test_expired_party_shows_status_line_and_no_controls(client):
    p = party("p1", status="expired", ended_at=NOW.isoformat(), cleared_at=None, leader_id="111", slots=[slot(1, "111", "나")])
    body = _detail(client, p).text
    assert "기한 만료" in body and "클리어로 집계되지 않습니다" in body
    for forbidden in ("모집 마감", "나가기", "참여하기", "공대 설정", "일정 변경", "빈자리 알림 받기"):
        assert forbidden not in body


def test_cleared_party_status_line_and_admin_revert_only_when_cleared(client):
    cleared = party("p1", status="disbanded", cleared_at=NOW.isoformat(), slots=[slot(1, "222", "파티장")])
    body = _detail(client, cleared).text
    assert "클리어 처리됐고" in body and "클리어 되돌리기" not in body  # 일반 멤버에게는 되돌리기 없음
    assert "클리어 되돌리기" in _detail(client, cleared, discord_id="999", admin=True).text
    disbanded = party("p2", status="disbanded", cleared_at=None, slots=[slot(1, "222", "파티장")])
    admin_body = _detail(client, disbanded, discord_id="999", admin=True).text
    assert "관리자가 종료한 공대" in admin_body and "클리어 되돌리기" not in admin_body
    assert "스레드 잠금 해제" in admin_body


def test_admin_mode_extras_live_in_admin_subsection(client):
    p = party("p1", slots=[slot(1, "222", "파티장")])
    body = _detail(client, p, discord_id="999", admin=True).text
    assert "관리자 권한으로 보는 중" in body and "스레드 잠금 해제" in body and "파티 종료" in body
    assert "pt-set-sec\">관리자" in body and "취소 사유" not in body  # 관리자는 공대 취소 불가(위험 구역 없음)


# ── 달력 · 이력 ───────────────────────────────────────────

def test_calendar_labels_expired_and_admin_disband(client):
    parties = [
        {**party("e", status="expired"), "slot_count": 1},
        {**party("d", status="disbanded", cleared_at=None), "slot_count": 1},
        {**party("c", status="disbanded", cleared_at=NOW.isoformat()), "slot_count": 1},
    ]
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/parties/calendar").mock(return_value=httpx.Response(200, json=parties))
        resp = client.get("/calendar?view=week&week_start=" + NOW.strftime("%Y-%m-%d"))
    assert "기한 만료" in resp.text and "종료" in resp.text and "클리어" in resp.text
    assert 'href="/parties/e"' not in resp.text  # 끝난 공대는 모집글 링크를 만들지 않는다


def test_history_labels_expired_distinct_from_clear(client):
    entries = [{"message_id": "h1", "raid_name": "종막", "difficulty": "노말", "proficiency": "숙련", "scheduled_time": "11/10 21:00",
                "status": "expired", "character_name": "발키리", "role": "dps", "total_slots": 8, "memo": None, "leader_id": "222", "members": []}]
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/user-party-history").mock(return_value=httpx.Response(200, json={"entries": entries, "has_more": False, "total_count": 1}))
        resp = client.get("/parties/history")
    assert "기한 만료" in resp.text and "클리어" not in resp.text.split("pt-title-row")[1].split("</div>")[0] + resp.text.split("ui-card")[1]
