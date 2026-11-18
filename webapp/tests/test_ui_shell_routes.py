"""셸(왼쪽 메뉴 4개 + 관리, 더보기, 묶음 탭)과 확인 대화상자 마크업 검증."""
import re
from pathlib import Path

import httpx
import respx

from webapp import config
from webapp.tests.conftest import log_in

B = "http://bot-server.internal/api/internal"
TEMPLATES = Path(__file__).resolve().parents[1] / "templates"


def _sidebar(body: str) -> str:
    return body.split('id="sidebar"')[1].split("</nav>")[0]


def test_more_page_lists_tools_and_admin_for_admin(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/more")
    body = resp.text
    assert resp.status_code == 200
    for href in ('href="/settings"', 'href="/tools/auction-calculator"', 'href="/guide"', 'href="/admin/raids"'):
        assert href in body.split("<main")[1]
    # 모바일에서 닿을 곳이 없던 로그아웃·관리자 모드도 여기
    assert 'action="/logout"' in body and 'action="/admin/toggle-mode"' in body
    # 더보기 화면에서는 더보기 메뉴가 선택 상태
    assert 'href="/more" class="side-link on"' in body


def test_more_page_hides_admin_for_member(client):
    with respx.mock:
        log_in(client, discord_id="222")
        resp = client.get("/more")
    main = resp.text.split("<main")[1]
    assert 'href="/admin/raids"' not in main
    assert 'action="/admin/toggle-mode"' not in resp.text
    assert 'href="/admin/raids"' not in _sidebar(resp.text)


def test_sidebar_has_four_items_plus_admin_and_profile_menu(client, monkeypatch):
    monkeypatch.setattr(config, "ADMIN_DISCORD_IDS", {"111"})
    with respx.mock:
        log_in(client, discord_id="111")
        resp = client.get("/more")
    side = _sidebar(resp.text)
    assert re.findall(r'class="side-link[^"]*" data-tip="([^"]+)"', side)[:5] == ["홈", "공대", "원정대", "더보기", "관리"]
    # 관리 세부 링크 7개와 관리자 모드 스위치는 사이드바에서 빠졌다(관리 화면 탭·프로필 메뉴로)
    assert 'href="/admin/classes"' not in side and 'role="switch"' not in side
    assert 'id="profile-menu"' in side and 'data-nav-fold' in side
    assert "본문으로 건너뛰기" in resp.text


def test_ranking_shows_expedition_subtabs_with_current(client):
    with respx.mock:
        log_in(client)
        respx.get(f"{B}/ranking").mock(return_value=httpx.Response(200, json={"metric": "combat_power", "entries": []}))
        resp = client.get("/ranking")
    tabs = resp.text.split('class="utabs subtabs"')[1].split("</nav>")[0]
    assert 'href="/expedition"' in tabs
    assert '<a href="/ranking" class="on" aria-current="page">' in tabs
    # 원정대 묶음 → 왼쪽 메뉴의 원정대가 선택
    assert 'href="/expedition" class="side-link on"' in resp.text


def test_no_native_confirm_left_in_templates():
    """브라우저 기본 confirm()은 디스코드 앱 내 브라우저에서 막히고, {{ x | tojson }}을 큰따옴표 속성에
    넣던 곳은 이름에 따옴표가 있으면 깨졌다 — 전부 data-confirm / uiConfirm으로."""
    offenders = []
    for path in TEMPLATES.glob("*.html"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"(?<![\w.])confirm\(|window\.confirm\(", line):
                offenders.append(f"{path.name}:{i}")
    assert offenders == []


def test_confirm_text_is_attribute_escaped():
    """확인 문구는 속성값 자동 이스케이프만 거친다 — 이름의 따옴표·꺾쇠가 스크립트가 될 수 없다
    (예전 admin_raids는 {{ name | tojson }}을 onsubmit 큰따옴표 안에 넣어 이름에 따옴표가 있으면 깨졌다)."""
    from webapp.templating import templates

    source = (TEMPLATES / "admin_raids.html").read_text(encoding="utf-8")
    assert "tojson" not in source and "onsubmit=" not in source
    tricky = "A'B\"<x>"
    rendered = templates.env.from_string(
        '<form data-confirm-title="{{ n }} 레이드를 삭제할까요?" data-confirm-original="{{ n }}"></form>'
    ).render(n=tricky)
    assert "&#39;" in rendered and "&#34;" in rendered and "&lt;x&gt;" in rendered
