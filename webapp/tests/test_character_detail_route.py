"""캐릭터 상세 정보(/characters/{character_name}) 웹 라우트 검증 — 봇 서버는 respx로 모킹."""
import httpx
import respx

from webapp.tests.conftest import log_in

ARMORY_URL = "http://bot-server.internal/api/internal/armory-detail"

DETAIL = {
    "character_name": "발키리",
    "character_class": "홀리나이트",
    "item_level": "1720.00",
    "combat_power": "123456789",
    "skills": [
        {
            "name": "심판의 빛",
            "level": 10,
            "tripods": [{"tier": 0, "name": "선택된 트라이포드"}],
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
