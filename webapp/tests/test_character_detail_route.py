"""캐릭터 상세 정보(/characters/{character_name}, /party-member-card) 웹 라우트 검증
— 봇 서버는 respx로 모킹."""
from urllib.parse import parse_qs, urlparse

import httpx
import respx

from webapp.tests.conftest import log_in

ARMORY_URL = "http://bot-server.internal/api/internal/armory-detail"

# 보석은 detail["gems"]와 detail["gem_summary"]의 그룹 양쪽에 같은 객체가 들어간다
GEM = {
    "slot": 0,
    "name": "광휘의 보석",
    "level": 8,
    "grade": "유물",
    "icon": "https://cdn-lostark.game.onstove.com/gem.png",
    "effect": "재사용 대기시간 20.00% 감소",
    "skill_name": "심판의 빛",
    "skill_icon": "https://cdn-lostark.game.onstove.com/skill.png",
    "effect_lines": ["재사용 대기시간 20.00% 감소", "기본 공격력 0.80% 증가"],
    "kind": "쿨감",
}

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
    "using_skill_point": 480,
    "total_skill_point": 483,
    "profile_stats": {
        "attack_power": "184,894",
        "max_hp": "405,670",
        "combat": [
            {"type": "치명", "value": "76"},
            {"type": "특화", "value": "575"},
            {"type": "신속", "value": "1804"},
        ],
    },
    "stat_effects": [
        {"stat": "신속", "text": "공격 속도 +30.99%"},
        {"stat": "신속", "text": "이동 속도 +30.99%"},
    ],
    "aggregate_effects": [
        {"name": "공격 속도", "value_text": "+30.99%", "text": "공격 속도 +30.99%"},
        {"name": "추가 피해", "value_text": "+30.00%", "text": "추가 피해 +30.00%"},
        {"name": "최대 마나", "value_text": "+6", "text": "최대 마나 +6"},
    ],
    "engravings": [
        {"name": "각성", "grade": "유물", "level": 4, "ability_stone_level": 3, "description": "각성기의 재사용 대기시간이 60.50% 감소한다."},
    ],
    "cards": {
        "cards": [
            {"slot": 0, "name": "아만", "icon": "https://cdn-lostark.game.onstove.com/card.png", "grade": "전설", "awake_count": 5, "awake_total": 5},
        ],
        "effects": [
            {"name": "남겨진 바람의 절벽 6세트 (12각성)", "text": "암속성 피해 감소 +25.00%"},
        ],
        "total_awake": 30,
        "set_name": "남겨진 바람의 절벽",
    },
    "equipment": [
        {
            "type": "무기",
            "name": "운명의 전율 한손검",
            "honing_level": "18",
            "icon": "https://cdn-lostark.game.onstove.com/weapon.png",
            "grade": "고대",
            "quality": 100,
            "quality_tier": "상",
            "base_stat_lines": ["무기 공격력 +203054"],
            "bonus_effect": "추가 피해 +30.00%",
            "ark_passive_bonus": None,
            "detail_text": "무기 공격력 +203054\n추가 피해 +30.00%",
        }
    ],
    "skills": [
        {
            "name": "심판의 빛",
            "icon": "https://cdn-lostark.game.onstove.com/skill.png",
            "level": 10,
            "tripods": [
                {"tier": 0, "name": "선택된 트라이포드", "icon": "https://cdn-lostark.game.onstove.com/tripod.png"}
            ],
            "rune": {"name": "속행", "grade": "영웅", "effect": "재사용 대기시간 12% 감소"},
            "gems": [{"level": 8, "kind": "쿨감", "name": "광휘의 보석"}],
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
        "nodes_by_category": {
            "깨달음": [{"tier": 1, "name": "해방자", "level": 1, "icon": None}],
        },
    },
    "accessories": [
        {
            "type": "목걸이",
            "name": "도래한 결전의 목걸이",
            "icon": "https://cdn-lostark.game.onstove.com/necklace.png",
            "grade": "고대",
            "quality": 96,
            "quality_tier": "상",
            "base_stat_lines": ["힘 +17697", "민첩 +17697", "지능 +17697", "체력 +4006"],
            "honing_effects": ["낙인력 +8.00%", "최대 마나 +6"],
            "honing_options": [
                {"text": "낙인력 +8.00%", "tier": "상"},
                {"text": "최대 마나 +6", "tier": "하"},
            ],
            "ark_passive_bonus": "깨달음 +13",
            "detail_text": "낙인력 +8.00%\n최대 마나 +6\n깨달음 +13",
        }
    ],
    "extra_equipment": [
        {
            "type": "팔찌",
            "name": "천선의 구슬치",
            "icon": "https://cdn-lostark.game.onstove.com/bracelet.png",
            "grade": "고대",
            "quality": None,
            "quality_tier": None,
            "sections": [
                {
                    "header": "팔찌 효과",
                    "lines": ["체력 +15000", "신속 +100"],
                    "options": [
                        {"text": "체력 +15000", "tier": None},
                        {"text": "신속 +100", "tier": "상"},
                    ],
                }
            ],
        },
        {
            "type": "어빌리티 스톤",
            "name": "위대한 비상",
            "icon": "https://cdn-lostark.game.onstove.com/stone.png",
            "grade": "유물",
            "quality": None,
            "quality_tier": None,
            "sections": [{"header": "기본 효과", "lines": ["체력 +30000"], "options": [{"text": "체력 +30000", "tier": None}]}],
            "stone_engravings": [{"name": "각성", "level": 3}, {"name": "구슬동자", "level": 2}],
        },
    ],
    "gems": [GEM],
    "gem_summary": {
        "damage": [],
        "cooldown": [GEM],
        "etc": [],
        "base_attack_total": "0.80%",
        "support_total": "9.00%",
    },
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
                "options": [
                    {
                        "point": 10,
                        "text": "아군 공격력 강화 효과 +1.3%",
                        "sub_lines": ["'운명: 빛이 생명을 새긴다' : 적에게 주는 무력화 피해가 5.0% 증가한다."],
                    }
                ],
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
    # 진화/깨달음/도약 패널 머리글 — 노드가 있는 카테고리(깨달음)의 포인트 요약이 나와야 한다
    assert "6랭크 28레벨" in resp.text
    assert "101P" in resp.text
    # 아크패시브 노드는 구조화된 형태(티어 배지 + 이름 + 레벨)로 렌더링
    assert "해방자" in resp.text
    assert "1티어" in resp.text
    assert "도래한 결전의 목걸이" in resp.text
    # 품질 대신 기본 효과(힘/민첩/지능)를 보여준다
    assert "힘 +17697" in resp.text
    assert "width: 96%;" not in resp.text
    assert "낙인력 +8.00%" in resp.text  # 연마 효과는 장신구 카드에 바로 노출
    assert "grind-tier-상" in resp.text  # 연마 단계(상/중/하)별 색상 클래스
    assert "grind-tier-하" in resp.text
    assert "광휘의 보석" in resp.text
    assert "재사용 대기시간 20.00% 감소" in resp.text
    # 보석 탭: 쿨타임 그룹 + 적용 스킬 + 총합
    assert "쿨타임 감소 보석" in resp.text
    assert "기본 공격력 총합" in resp.text
    assert "0.80%" in resp.text
    assert "지원 효과 총합" in resp.text
    # 스킬 탭: SP + 보석 배지
    assert "480" in resp.text and "483" in resp.text
    assert "8레벨 쿨감" in resp.text
    # 장비 탭 하단: 전투특성/공격력/최대 생명력 + 팔찌
    assert "184,894" in resp.text
    assert "405,670" in resp.text
    assert "1804" in resp.text
    assert "천선의 구슬치" in resp.text
    assert "체력 +15000" in resp.text
    # 팔찌 전투특성도 상/중/하 밴딩 색
    assert "grind-tier-상" in resp.text
    # 어빌리티 스톤 카드에 세공 각인 + 레벨 칩
    assert "stone-engraving" in resp.text
    assert "구슬동자" in resp.text
    # hover 정보는 네이티브 title 대신 카드형 툴팁(data-tip)으로
    assert "data-tip=" in resp.text
    # 효과 영수증은 이름/수치 분리 렌더링
    assert "+30.99%" in resp.text
    assert "최대 마나" in resp.text
    assert 'src="https://cdn-lostark.game.onstove.com/skill.png"' in resp.text
    assert 'src="https://cdn-lostark.game.onstove.com/tripod.png"' in resp.text
    assert "빛이 생명을 새긴다" in resp.text
    # 코어 옵션은 "[10P] 설명" 한 덩어리가 아니라 포인트 칩 + 설명으로 분리 렌더링
    assert "core-opt-point" in resp.text
    assert "10P" in resp.text
    assert "아군 공격력 강화 효과 +1.3%" in resp.text
    # '운명: ...' 부연 설명은 상위 옵션에 종속된 들여쓰기 줄로 렌더링
    assert "core-opt-sub" in resp.text
    assert "적에게 주는 무력화 피해가 5.0% 증가한다." in resp.text
    # 장신구 기본 효과 4종(힘/민첩/지능/체력)
    assert "체력 +4006" in resp.text
    assert "공격력 +1.06%" in resp.text
    # 등급은 텍스트로 적지 않고 아이콘 테두리/이름 글자색(CSS 클래스)으로만 표현
    assert 'class="char-arkgrid-core-icon char-grade-유물"' in resp.text
    assert 'char-grade-text-유물' in resp.text
    # 장비 탭 아크 그리드 요약 — 코어 이름이 hover 툴팁이 아니라 아이콘 오른쪽에 노출
    assert "arkgrid-core-mini-name" in resp.text
    assert "질서의 해 코어 : 빛이 생명을 새긴다" in resp.text
    assert "18P" in resp.text
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
    # 무기/방어구 목록은 의도적으로 렌더링하지 않는다 — 장비 탭 상단은
    # 장신구(목걸이/귀걸이 | 반지) + 팔찌/어빌리티 스톤/보주 배치로 재구성됐다.
    # (equipment 데이터 자체는 효과 영수증 합산에는 계속 쓰인다)
    assert "운명의 전율 한손검" not in resp.text
    assert "공격 속도" in resp.text  # 효과 영수증 — 이름/수치가 분리 렌더링됨
    # 각인 + 카드
    assert "각성" in resp.text
    assert "Lv.4" in resp.text
    # 어빌리티 스톤으로 활성화된 각인은 파란 스톤 아이콘 + 레벨 표시
    assert 'class="char-engraving-stone"' in resp.text
    assert "Lv.3" in resp.text
    assert 'src="https://cdn-lostark.game.onstove.com/card.png"' in resp.text
    # 카드 아이콘 아래 "세트 이름 + 총 각성" 한 줄과 세트효과 설명
    assert "남겨진 바람의 절벽" in resp.text
    assert "30각" in resp.text
    assert "암속성 피해 감소 +25.00%" in resp.text
    assert "5각" in resp.text  # 카드마다 각성 수 배지


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


# ── 동기화 버튼 — F5로는 API를 다시 호출하지 않고, 이 버튼을 눌러야만 갱신된다 ──

SYNC_URL = "http://bot-server.internal/api/internal/armory-detail/sync"


def test_own_character_shows_sync_button_and_last_synced_time(client):
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(ARMORY_URL).mock(
            return_value=httpx.Response(200, json={**DETAIL, "synced_at": "2026-07-16T00:00:00+00:00"})
        )
        resp = client.get("/characters/발키리")

    assert resp.status_code == 200
    assert "armory-sync-btn" in resp.text
    assert "마지막 동기화" in resp.text
    assert "동기화" in resp.text
    # 아이콘 없이 텍스트만 — 이모지/아이콘 클래스가 버튼에 섞여 있지 않은지 확인
    assert '<button type="submit" class="armory-sync-btn">동기화</button>' in resp.text


def test_other_persons_character_hides_sync_button(client):
    """공대 모집 '자세히 보기'처럼 남의 캐릭터를 볼 때는 동기화 버튼을 숨긴다
    — 남을 대신해 로스트아크 API를 호출시킬 권한이 없다."""
    with respx.mock:
        log_in(client, discord_id="111")
        respx.get(ARMORY_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        resp = client.get("/characters/발키리", params={"discord_id": "222"})

    assert resp.status_code == 200
    assert "armory-sync-btn" not in resp.text


def test_sync_posts_to_bot_and_redirects_back(client):
    with respx.mock:
        log_in(client, discord_id="111")
        sync_route = respx.post(SYNC_URL).mock(return_value=httpx.Response(200, json=DETAIL))
        resp = client.post("/characters/발키리/sync")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/characters/%EB%B0%9C%ED%82%A4%EB%A6%AC"  # "발키리" URL 인코딩
    assert sync_route.called
    sent_params = parse_qs(urlparse(str(sync_route.calls.last.request.url)).query)
    assert sent_params["discord_id"] == ["111"]
    assert sent_params["character_name"] == ["발키리"]


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
