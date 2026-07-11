"""캐릭터 상세 정보(/characters/{character_name}, /party-member-card) 웹 라우트 검증
— 봇 서버는 respx로 모킹."""
from urllib.parse import parse_qs, urlparse

import httpx
import respx

from webapp.tests.conftest import log_in

ARMORY_URL = "http://bot-server.internal/api/internal/armory-detail"

DETAIL = {
    "character_name": "발키리",
    "character_class": "홀리나이트",
    "item_level": "1720.00",
    "combat_power": "123456789",
    "character_image": "https://cdn-lostark.game.onstove.com/portrait.png",
    "character_level": 70,
    "expedition_level": 293,
    "guild_name": "동물롱장",
    "guild_member_grade": "일반 길드원",
    "honor_point": 220,
    "town_level": 70,
    "town_name": "졸타뉴 마을",
    "server_name": "루페온",
    "skills": [
        {
            "name": "심판의 빛",
            "icon": "https://cdn-lostark.game.onstove.com/skill.png",
            "level": 10,
            "tripods": [
                {"tier": 0, "name": "선택된 트라이포드", "icon": "https://cdn-lostark.game.onstove.com/tripod.png"}
            ],
            "rune": {"name": "속행", "grade": "영웅", "effect": "재사용 대기시간 12% 감소"},
        }
    ],
    "ark_passive": {
        "title": "해방자",
        "points": [
            {"name": "진화", "value": 140, "description": "6랭크 27레벨"},
            {"name": "깨달음", "value": 101, "description": "6랭크 28레벨"},
            {"name": "도약", "value": 70, "description": "6랭크 21레벨"},
        ],
        "effects_by_category": {"깨달음": ["깨달음 1티어 해방자 Lv.1"]},
    },
    "accessories": [
        {
            "type": "목걸이",
            "name": "도래한 결전의 목걸이",
            "grade": "고대",
            "quality": 96,
            "quality_tier": "상",
            "honing_effects": ["낙인력 +8.00%", "최대 마나 +6"],
            "ark_passive_bonus": "깨달음 +13",
        }
    ],
    "gems": [{"slot": 0, "name": "8레벨 광휘의 보석", "level": 8, "grade": "유물", "icon": None, "effect": "추가 피해 +8.00%"}],
    "ark_grid": {
        "cores": [
            {
                "name": "질서의 해 코어 : 빛이 생명을 새긴다",
                "flavor": "빛이 생명을 새긴다",
                "icon": "https://cdn-lostark.game.onstove.com/core.png",
                "grade": "유물",
                "point": 18,
                "system": "질서",
                "core_name": "해",
                "willpower": "15 포인트",
                "option_lines": ["[10P] 아군 공격력 강화 효과 +1.3%"],
            }
        ],
        "effects": [{"name": "공격력", "level": 29, "text": "공격력 +1.06%"}],
    },
}


def test_requires_login(client):
    resp = client.get("/characters/발키리")
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_renders_character_detail(client):
    with respx.mock:
        log_in(client)
        respx.get(ARMORY_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        resp = client.get("/characters/발키리")

    assert resp.status_code == 200
    assert "발키리" in resp.text
    assert "홀리나이트" in resp.text
    assert "심판의 빛" in resp.text
    assert "선택된 트라이포드" in resp.text
    assert "속행" in resp.text
    assert "6랭크 27레벨" in resp.text
    assert "깨달음 1티어 해방자 Lv.1" in resp.text
    assert "도래한 결전의 목걸이" in resp.text
    assert "품질 96" in resp.text
    assert "낙인력 +8.00%" in resp.text
    assert "8레벨 광휘의 보석" in resp.text
    assert "추가 피해 +8.00%" in resp.text
    assert 'src="https://cdn-lostark.game.onstove.com/skill.png"' in resp.text
    assert 'src="https://cdn-lostark.game.onstove.com/tripod.png"' in resp.text
    assert "빛이 생명을 새긴다" in resp.text
    assert "[10P] 아군 공격력 강화 효과 +1.3%" in resp.text
    assert "공격력 +1.06%" in resp.text
    # 등급은 텍스트로 적지 않고 아이콘 테두리/이름 글자색(CSS 클래스)으로만 표현
    assert 'class="char-arkgrid-core-icon char-grade-유물"' in resp.text
    assert 'char-grade-text-유물' in resp.text
    # 좌측 프로필 사이드바 (칭호/수집형 포인트/아이템레벨-전투력 순위는 제외)
    assert "동물롱장" in resp.text
    assert "일반 길드원" in resp.text
    assert "졸타뉴 마을" in resp.text
    assert 'src="https://cdn-lostark.game.onstove.com/portrait.png"' in resp.text
    # 장비/스킬/아크그리드/보석 4개 탭
    assert 'data-armory-tab="equip"' in resp.text
    assert 'data-armory-tab="skill"' in resp.text
    assert 'data-armory-tab="arkgrid"' in resp.text
    assert 'data-armory-tab="gem"' in resp.text
    # 코어에 장착된 젬의 세부 정보는 너무 장황해서 보여주지 않기로 했다
    assert "char-arkgrid-gem" not in resp.text


def test_renders_error_when_not_found(client):
    with respx.mock:
        log_in(client)
        respx.get(ARMORY_URL).mock(
            return_value=httpx.Response(200, json={"error": "먼저 /api등록으로 API 키를 등록해주세요."})
        )
        resp = client.get("/characters/없는캐릭")

    assert resp.status_code == 200
    assert "정보를 불러올 수 없습니다" in resp.text
    assert "/api등록" in resp.text


def test_uses_own_discord_id_by_default(client):
    """discord_id 쿼리파라미터 없이 들어오면(원정대 관리에서 진입) 로그인한 본인 기준으로 조회."""
    with respx.mock:
        log_in(client, discord_id="111")
        route = respx.get(ARMORY_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        client.get("/characters/발키리")

    sent_params = parse_qs(urlparse(str(route.calls.last.request.url)).query)
    assert sent_params["discord_id"] == ["111"]


def test_uses_explicit_discord_id_when_provided(client):
    """공대 모집 '자세히 보기'처럼 다른 사람 캐릭터를 볼 땐 그 사람의 discord_id로 조회해야 한다."""
    with respx.mock:
        log_in(client, discord_id="111")  # 로그인은 111이지만
        route = respx.get(ARMORY_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        client.get("/characters/발키리", params={"discord_id": "222"})  # 조회 대상은 222

    sent_params = parse_qs(urlparse(str(route.calls.last.request.url)).query)
    assert sent_params["discord_id"] == ["222"]


PARTY_MEMBER_CARD_URL = "http://bot-server.internal/api/internal/armory-detail"


def test_party_member_card_requires_login(client):
    resp = client.get("/party-member-card", params={"discord_id": "222", "character_name": "발키리"})
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/login"


def test_party_member_card_renders_compact_summary(client):
    with respx.mock:
        log_in(client)
        respx.get(PARTY_MEMBER_CARD_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        resp = client.get("/party-member-card", params={"discord_id": "222", "character_name": "발키리"})

    assert resp.status_code == 200
    assert "발키리" in resp.text
    assert "홀리나이트" in resp.text
    assert "123456789" in resp.text or "123,456,789" in resp.text
    assert "품질 96" not in resp.text  # 컴팩트 카드는 장신구 품질 배지를 아예 보여주지 않음
    assert "char-quality-badge" not in resp.text
    assert "member-card-stat-value" in resp.text  # 아이템레벨/전투력이 큰 글씨로 강조되어야 함
    assert "자세히 보기" in resp.text
    assert "discord_id=222" in resp.text  # 링크가 대상자의 discord_id를 유지해야 함


def test_party_member_card_shows_error_message(client):
    with respx.mock:
        log_in(client)
        respx.get(PARTY_MEMBER_CARD_URL).mock(
            return_value=httpx.Response(200, json={"error": "API 키가 만료되었습니다."})
        )
        resp = client.get("/party-member-card", params={"discord_id": "222", "character_name": "발키리"})

    assert resp.status_code == 200
    assert "API 키가 만료되었습니다." in resp.text
