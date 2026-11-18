"""화면 표기 통일 — 아이템 레벨·전투력 숫자 형식과 공대 상태 글자가 화면마다 달라지지 않게."""
from webapp.format import party_view, status_view
from webapp.templating import templates
from webapp.utils import combat_power, ilvl


def test_ilvl_two_decimals_like_in_game():
    assert ilvl(1735) == "1735.00"
    assert ilvl(1722.5) == "1722.50"
    assert ilvl("1,735.00") == "1735.00"
    assert ilvl(None) == "—"
    assert ilvl("") == "—"
    assert ilvl("미확인") == "—"


def test_combat_power_thousands_and_two_decimals():
    assert combat_power(2812.45) == "2,812.45"
    assert combat_power("2,398") == "2,398.00"
    assert combat_power(None) == "—"


def test_filters_registered_in_jinja():
    env = templates.env
    assert env.from_string("{{ v | ilvl }}").render(v=1700) == "1700.00"
    assert env.from_string("{{ v | cp }}").render(v=1234.5) == "1,234.50"


def test_status_labels_are_the_same_everywhere():
    assert status_view({"status": "recruiting"}) == ("모집중", "accent")
    assert status_view({"status": "full"}) == ("파티완성", "warn")
    assert status_view({"status": "closed"}) == ("마감", "")
    assert status_view({"status": "expired"}) == ("기한 만료", "past")
    assert status_view({"status": "cancelled"}) == ("취소", "danger")
    # 클리어로 끝난 공대 / 관리자가 종료한 공대 / cleared_at 칸이 없는 이력 응답
    assert status_view({"status": "disbanded", "cleared_at": "2026-11-18 12:00:00"}) == ("클리어", "ok")
    assert status_view({"status": "disbanded", "cleared_at": None}) == ("종료", "")
    assert status_view({"status": "disbanded"}) == ("클리어", "ok")


def test_party_view_knows_expired_and_admin_ended():
    assert party_view({"status": "expired", "slots": [], "total_slots": 8})["status_label"] == "기한 만료"
    assert party_view({"status": "disbanded", "cleared_at": None, "slots": [], "total_slots": 8})["status_label"] == "종료"
