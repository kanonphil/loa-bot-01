"""공대 화면의 판단 로직(추천·불가 사유·리셋/중복 경고·상태 표기) 순수 함수 검증."""
from datetime import datetime, timedelta

from webapp import party_logic as pl
from webapp.format import KST

# 2026-11-19(목) 12:00 KST — 이번 주 리셋은 11-18(수) 06:00, 다음 리셋은 11-25(수) 06:00
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=KST)


def char(name, level, sup=False, done=(), cls="워로드"):
    return {"character_name": name, "character_class": cls, "item_level": level, "is_support": sup, "completions": list(done)}


def summary(chars, extreme=None):
    return {"characters": chars, "extreme": extreme or []}


def opts(chars, *, target=None, my_slots=(), lacks_support=False, extreme_cleared=None, raid="종막", min_level=1710):
    is_extreme = extreme_cleared is not None
    ext = [{"raid_name": raid, "cleared": extreme_cleared}] if is_extreme else []
    return pl.character_options(
        summary(chars, ext), raid_name=raid, difficulty="노말", min_level=min_level,
        target=target or NOW + timedelta(days=1), my_slots=list(my_slots),
        lacks_support=lacks_support, is_extreme=is_extreme, now=NOW,
    )


def party(mid, raid, when, slots=(), status="recruiting", total=8):
    return {"message_id": mid, "raid_name": raid, "difficulty": "노말", "status": status, "total_slots": total,
            "scheduled_datetime": when.isoformat(), "slots": list(slots), "leader_id": "222", "min_level": 1700}


def slot(n, did, name, role="dps"):
    return {"slot_number": n, "discord_id": did, "character_name": name, "character_class": "워로드", "role": role}


# ── 추천 순서와 불가 사유 ──────────────────────────────────

def test_highest_level_eligible_character_is_recommended_first():
    result = opts([char("낮음", 1715), char("높음", 1740)])
    assert [o["name"] for o in result] == ["높음", "낮음"]
    assert result[0]["recommended"] and not result[1]["recommended"]


def test_support_character_comes_first_when_party_lacks_support():
    chars = [char("딜러높음", 1740), char("서포터", 1715, sup=True, cls="바드")]
    assert opts(chars, lacks_support=True)[0]["name"] == "서포터"
    assert opts(chars, lacks_support=False)[0]["name"] == "딜러높음"


def test_level_too_low_is_disabled_with_required_level():
    result = opts([char("부족", 1700), char("충분", 1720)])
    low = next(o for o in result if o["name"] == "부족")
    assert not low["ok"] and low["reason"] == "레벨 1710 필요"
    assert result[-1]["name"] == "부족"  # 못 들어가는 캐릭터는 뒤로


def test_character_done_this_week_is_disabled_but_not_for_next_week_party():
    done = char("완료", 1740, done=["종막_하드"])  # 난이도가 달라도 같은 레이드면 이번 주 완료
    assert opts([done])[0]["reason"] == "이번 주 완료"
    after_reset = NOW + timedelta(days=7)  # 다음 주 공대는 이번 주 완료 기록과 무관
    assert opts([done], target=after_reset)[0]["ok"]


def test_time_conflict_within_two_hours_blocks_character():
    target = NOW + timedelta(days=1)
    other = party("x", "세르카", target + timedelta(hours=1), [slot(1, "111", "충돌")])
    mine = pl.my_party_slots([other], "111")
    result = opts([char("충돌", 1740), char("한가", 1720)], target=target, my_slots=mine)
    blocked = next(o for o in result if o["name"] == "충돌")
    assert blocked["reason"] == "같은 시간 다른 공대"
    assert result[0]["name"] == "한가"


def test_same_raid_other_party_same_week_blocks_even_at_different_time():
    target = NOW + timedelta(days=1)
    other = party("x", "종막", target + timedelta(hours=20), [slot(1, "111", "중복")])
    result = opts([char("중복", 1740)], target=target, my_slots=pl.my_party_slots([other], "111"))
    assert result[0]["reason"] == "이번 주 이 레이드의 다른 공대"


def test_ended_parties_do_not_count_as_my_slots():
    ended = party("x", "종막", NOW + timedelta(hours=1), [slot(1, "111", "캐릭")], status="expired")
    assert pl.my_party_slots([ended], "111") == []


def test_extreme_rule_is_per_expedition_once_a_week():
    chars = [char("아무", 1740)]
    assert opts(chars, extreme_cleared=True)[0]["reason"] == "원정대 주 1회 · 이미 감"
    fresh = opts(chars, extreme_cleared=False)[0]
    assert fresh["ok"] and fresh["note"] == "원정대 주 1회 · 아직 안 감"


def test_no_summary_means_no_options():
    assert pl.character_options(None, raid_name="종막", difficulty="노말", min_level=1710, target=NOW, my_slots=[]) == []


def test_join_summary_reports_common_reason():
    blocked = opts([char("가", 1740, done=["종막_노말"]), char("나", 1730, done=["종막_노말"])])
    result = pl.join_summary(blocked)
    assert not result["can_join"] and result["reason"] == "모든 캐릭터가 이번 주 완료"
    assert pl.join_summary(opts([char("가", 1740)]))["can_join"]


# ── 목록 참여 칸 ──────────────────────────────────────────

RAIDS = {"종막": {"is_extreme": False, "difficulties": {"노말": {"party_split": 4}}}}


def test_list_row_states():
    sm = summary([char("발키리", 1740, sup=True, cls="바드")])
    mine = party("a", "종막", NOW + timedelta(days=1), [slot(1, "111", "발키리")])
    assert pl.list_row_join(mine, sm, [mine], "111", RAIDS, NOW)["state"] == "joined"
    closed = party("b", "종막", NOW + timedelta(days=1), status="closed")
    assert pl.list_row_join(closed, sm, [closed], "111", RAIDS, NOW)["state"] == "closed"
    full = party("c", "종막", NOW + timedelta(days=1), [slot(i, str(i), f"c{i}") for i in range(1, 9)], status="full")
    assert pl.list_row_join(full, sm, [full], "111", RAIDS, NOW)["state"] == "full"
    expired = party("d", "종막", NOW - timedelta(days=2), status="expired")
    assert pl.list_row_join(expired, sm, [expired], "111", RAIDS, NOW)["state"] == "ended"
    open_party = party("e", "종막", NOW + timedelta(days=1), [slot(1, "222", "파티장")])
    row = pl.list_row_join(open_party, sm, [open_party], "111", RAIDS, NOW)
    assert row["state"] == "can" and row["options"][0]["role"] == "support" and row["options"][0]["group"] == 1
    assert pl.list_row_join(open_party, None, [open_party], "111", RAIDS, NOW)["state"] == "unknown"


def test_list_row_blocked_shows_reason():
    sm = summary([char("발키리", 1740, done=["종막_노말"])])
    p = party("e", "종막", NOW + timedelta(days=1), [slot(1, "222", "파티장")])
    row = pl.list_row_join(p, sm, [p], "111", RAIDS, NOW)
    assert row == {"state": "blocked", "reason": "모든 캐릭터가 이번 주 완료"}


# ── 파티 구성·그룹 ────────────────────────────────────────

def test_composition_highlights_missing_support():
    p = party("a", "종막", NOW, [slot(1, "1", "딜1"), slot(2, "2", "딜2")])
    comp = pl.composition(p)
    assert (comp["dps"], comp["dps_total"], comp["sup"], comp["sup_total"]) == (2, 6, 0, 2)
    assert comp["lacks_support"] and comp["lacks_dps"]
    p4 = party("b", "세르카", NOW, [slot(1, "1", "딜"), slot(2, "2", "폿", "support")], total=4)
    assert pl.composition(p4)["sup_total"] == 1 and not pl.composition(p4)["lacks_support"]


def test_pick_group_separates_supports_and_keeps_room_for_them():
    p = party("a", "종막", NOW, [slot(1, "1", "딜1"), slot(2, "2", "서포터", "support")])
    groups = pl.group_layout(p, 4)
    assert [g["group_number"] for g in groups] == [1, 2]
    assert pl.pick_group(groups, "support") == 2  # 서포터가 없는 파티로
    assert pl.pick_group(groups, "dps") == 1      # 서포터가 이미 있는 파티를 먼저 채운다


def test_pick_group_skips_full_groups():
    full1 = [slot(i, str(i), f"c{i}") for i in range(1, 5)]
    groups = pl.group_layout(party("a", "종막", NOW, full1), 4)
    assert pl.pick_group(groups, "dps") == 2
    all_full = pl.group_layout(party("a", "종막", NOW, full1 + [slot(i, str(i), f"c{i}") for i in range(5, 9)]), 4)
    assert pl.pick_group(all_full, "dps") is None


def test_group_layout_uses_absolute_numbers_for_empty_slots():
    groups = pl.group_layout(party("a", "종막", NOW, [slot(1, "1", "a")]), 4)
    assert [s["slot_number"] for s in groups[1]["slots"]] == [5, 6, 7, 8]
    assert [s["local_number"] for s in groups[1]["slots"]] == [1, 2, 3, 4]
    single = pl.group_layout(party("b", "세르카", NOW, [], total=4), None)
    assert len(single) == 1 and single[0]["total"] == 4


# ── 리셋·중복·프리셋 ──────────────────────────────────────

def test_week_start_is_previous_wednesday_six_am():
    assert pl.week_start(NOW) == datetime(2026, 11, 18, 6, 0, tzinfo=KST)
    assert pl.week_start(datetime(2026, 11, 18, 5, 59, tzinfo=KST)) == datetime(2026, 11, 11, 6, 0, tzinfo=KST)
    assert pl.week_start(datetime(2026, 11, 25, 6, 0, tzinfo=KST)) == datetime(2026, 11, 25, 6, 0, tzinfo=KST)


def test_reset_info_warns_only_after_next_wednesday_six():
    before = pl.reset_info(datetime(2026, 11, 25, 5, 59, tzinfo=KST), NOW)
    after = pl.reset_info(datetime(2026, 11, 25, 6, 0, tzinfo=KST), NOW)
    assert not before["next_week"] and after["next_week"]
    assert before["label"] == "리셋까지 5일 · 수요일 06:00"
    assert pl.reset_info(None, datetime(2026, 11, 24, 20, 0, tzinfo=KST))["label"].startswith("리셋까지 10시간")


def test_find_duplicates_same_raid_difficulty_within_an_hour():
    target = NOW + timedelta(days=1)
    near = party("a", "종막", target + timedelta(minutes=50))
    far = party("b", "종막", target + timedelta(hours=2))
    other_raid = party("c", "세르카", target)
    closed = party("d", "종막", target, status="closed")
    found = pl.find_duplicates([near, far, other_raid, closed], "종막", "노말", target)
    assert [p["message_id"] for p in found] == ["a"]
    assert pl.find_duplicates([near], "종막", "노말", None) == []


def test_time_presets_skip_past_today_slot_and_dedupe_saturday():
    morning = datetime(2026, 11, 19, 9, 0, tzinfo=KST)  # 목
    labels = [p["label"] for p in pl.time_presets(morning)]
    assert labels == ["오늘 21:00", "내일(금) 21:00", "토 21:00"]
    night = datetime(2026, 11, 19, 22, 0, tzinfo=KST)
    assert [p["label"] for p in pl.time_presets(night)][0] == "내일(금) 21:00"
    friday = datetime(2026, 11, 20, 9, 0, tzinfo=KST)  # 내일이 토요일 → 중복 칩 없음
    assert [p["label"] for p in pl.time_presets(friday)] == ["오늘 21:00", "내일(토) 21:00"]


# ── 상태 표기 ─────────────────────────────────────────────

def test_status_labels_include_expired_and_separate_clear_from_disband():
    assert pl.status_view({"status": "expired"}) == ("기한 만료", "past")
    assert pl.status_view({"status": "disbanded", "cleared_at": "2026-11-19T22:00:00+09:00"}) == ("클리어", "ok")
    assert pl.status_view({"status": "disbanded", "cleared_at": None}) == ("종료", "")
    assert pl.status_view({"status": "recruiting"}) == ("모집중", "accent")
    assert pl.is_ended({"status": "expired"}) and pl.is_ended({"status": "disbanded"}) and not pl.is_ended({"status": "closed"})
