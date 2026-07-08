"""bot/api/armory_parser.py 검증 — 실제 로스트아크 API 응답 샘플 구조를 기반으로 한 픽스처 사용."""
import json

from bot.api import armory_parser as parser


def test_strip_html_converts_br_to_newline_and_removes_tags():
    raw = "<font color='#fff'>힘 +100</font><br>민첩 +50<BR>지능 +30"
    assert parser.strip_html(raw) == "힘 +100\n민첩 +50\n지능 +30"


def test_strip_html_handles_none_and_empty():
    assert parser.strip_html(None) == ""
    assert parser.strip_html("") == ""


def test_parse_tooltip_json_handles_invalid_json():
    assert parser.parse_tooltip_json("not json") == {}
    assert parser.parse_tooltip_json(None) == {}


def test_parse_tooltip_json_parses_valid_payload():
    raw = json.dumps({"Element_000": {"type": "NameTagBox", "value": "테스트"}})
    assert parser.parse_tooltip_json(raw) == {"Element_000": {"type": "NameTagBox", "value": "테스트"}}


ACCESSORY_TOOLTIP = json.dumps(
    {
        "Element_000": {"type": "NameTagBox", "value": "도래한 결전의 목걸이"},
        "Element_001": {
            "type": "ItemTitle",
            "value": {"qualityValue": 96, "leftStr2": "아이템 티어 4"},
        },
        "Element_004": {
            "type": "ItemPartBox",
            "value": {"Element_000": "<FONT COLOR='#A9D0F5'>기본 효과</FONT>", "Element_001": "힘 +17697"},
        },
        "Element_006": {
            "type": "ItemPartBox",
            "value": {
                "Element_000": "<FONT COLOR='#A9D0F5'>연마 효과</FONT>",
                "Element_001": (
                    "<img src='x'></img>낙인력 <FONT COLOR='FE9600'>+8.00%</FONT><br>"
                    "<img src='x'></img>최대 마나 <FONT COLOR='00B5FF'>+6</FONT>"
                ),
            },
        },
        "Element_007": {
            "type": "ItemPartBox",
            "value": {
                "Element_000": "<FONT COLOR='#A9D0F5'>아크 패시브 포인트 효과</FONT>",
                "Element_001": "깨달음 +13",
            },
        },
    }
)


def test_find_quality_extracts_from_item_title():
    tooltip = parser.parse_tooltip_json(ACCESSORY_TOOLTIP)
    assert parser.find_quality(tooltip) == 96


def test_find_quality_returns_none_for_non_quality_items():
    tooltip = {"Element_001": {"type": "ItemTitle", "value": {"qualityValue": -1}}}
    assert parser.find_quality(tooltip) is None


def test_find_item_part_matches_by_header_substring():
    tooltip = parser.parse_tooltip_json(ACCESSORY_TOOLTIP)
    honing = parser.find_item_part(tooltip, "연마 효과")
    assert "낙인력 +8.00%" in honing
    assert "최대 마나 +6" in honing


def test_find_item_part_returns_none_when_not_found():
    tooltip = parser.parse_tooltip_json(ACCESSORY_TOOLTIP)
    assert parser.find_item_part(tooltip, "존재하지 않는 섹션") is None


def test_quality_tier_thresholds():
    assert parser.quality_tier(96) == "상"
    assert parser.quality_tier(90) == "상"
    assert parser.quality_tier(89) == "중"
    assert parser.quality_tier(70) == "중"
    assert parser.quality_tier(69) == "하"
    assert parser.quality_tier(0) == "하"


def test_parse_accessories_extracts_quality_honing_and_ark_passive_bonus():
    equipment = [
        {"Type": "목걸이", "Name": "도래한 결전의 목걸이", "Grade": "고대", "Tooltip": ACCESSORY_TOOLTIP},
        {"Type": "무기", "Name": "어떤 무기", "Grade": "유물", "Tooltip": "{}"},
    ]
    result = parser.parse_accessories(equipment)
    assert len(result) == 1  # 무기는 장신구가 아니므로 제외
    acc = result[0]
    assert acc["type"] == "목걸이"
    assert acc["grade"] == "고대"
    assert acc["quality"] == 96
    assert acc["quality_tier"] == "상"
    assert acc["honing_effects"] == ["낙인력 +8.00%", "최대 마나 +6"]
    assert acc["ark_passive_bonus"] == "깨달음 +13"


RUNE_TOOLTIP = json.dumps(
    {
        "Element_003": {
            "type": "ItemPartBox",
            "value": {
                "Element_000": "<FONT COLOR='#A9D0F5'>스킬 룬 효과</FONT>",
                "Element_001": "스킬 사용 시 일정 확률로 전체 재사용 대기 시간이 12% 감소",
            },
        }
    }
)

SKILLS = [
    {
        "Name": "간파 베기",
        "Level": 1,
        "Tripods": [
            {"Tier": 0, "Slot": 1, "Name": "강화 베기", "IsSelected": False},
            {"Tier": 0, "Slot": 2, "Name": "약육강식", "IsSelected": False},
        ],
        "Rune": None,
    },
    {
        "Name": "계시의 검",
        "Level": 10,
        "Tripods": [
            {"Tier": 0, "Slot": 2, "Name": "부위파괴 강화", "IsSelected": True},
            {"Tier": 1, "Slot": 3, "Name": "신앙심", "IsSelected": True},
            {"Tier": 2, "Slot": 2, "Name": "더블 크로스", "IsSelected": True},
            {"Tier": 2, "Slot": 1, "Name": "선택 안 한 것", "IsSelected": False},
        ],
        "Rune": {"Name": "속행", "Grade": "영웅", "Tooltip": RUNE_TOOLTIP},
    },
]


def test_parse_skills_excludes_skills_without_selected_tripods():
    result = parser.parse_skills(SKILLS)
    assert len(result) == 1
    assert result[0]["name"] == "계시의 검"


def test_parse_skills_returns_tripods_sorted_by_tier():
    result = parser.parse_skills(SKILLS)
    tiers = [t["tier"] for t in result[0]["tripods"]]
    assert tiers == [0, 1, 2]
    assert result[0]["tripods"][0]["name"] == "부위파괴 강화"


def test_parse_skills_includes_rune_effect_when_present():
    result = parser.parse_skills(SKILLS)
    rune = result[0]["rune"]
    assert rune["name"] == "속행"
    assert rune["grade"] == "영웅"
    assert "12% 감소" in rune["effect"]


def test_parse_skills_rune_none_when_not_equipped():
    only_unselected = [SKILLS[0]]
    result = parser.parse_skills(only_unselected)
    assert result == []  # 트라이포드 미선택이라 애초에 걸러짐


ARK_PASSIVE = {
    "Title": "해방자",
    "IsArkPassive": True,
    "Points": [
        {"Name": "진화", "Value": 140, "Description": "6랭크 27레벨"},
        {"Name": "깨달음", "Value": 101, "Description": "6랭크 28레벨"},
        {"Name": "도약", "Value": 70, "Description": "6랭크 21레벨"},
    ],
    "Effects": [
        {"Name": "깨달음", "Description": "<FONT color='#83E9FF'>깨달음</FONT> 1티어 해방자 Lv.1"},
        {"Name": "깨달음", "Description": "깨달음 2티어 활력 Lv.3"},
        {"Name": "진화", "Description": "진화 1티어 예리한 둔기 Lv.2"},
    ],
}


def test_parse_ark_passive_points_use_api_description_directly():
    result = parser.parse_ark_passive(ARK_PASSIVE)
    names = {p["name"]: p["description"] for p in result["points"]}
    assert names["진화"] == "6랭크 27레벨"
    assert names["깨달음"] == "6랭크 28레벨"
    assert names["도약"] == "6랭크 21레벨"


def test_parse_ark_passive_groups_effects_by_category():
    result = parser.parse_ark_passive(ARK_PASSIVE)
    assert len(result["effects_by_category"]["깨달음"]) == 2
    assert len(result["effects_by_category"]["진화"]) == 1
    assert "해방자 Lv.1" in result["effects_by_category"]["깨달음"][0]


def test_parse_ark_passive_handles_none():
    result = parser.parse_ark_passive(None)
    assert result["points"] == []
    assert result["effects_by_category"] == {}


GEM_TOOLTIP = json.dumps(
    {
        "Element_006": {
            "type": "ItemPartBox",
            "value": {"Element_000": "<FONT COLOR='#A9D0F5'>효과</FONT>", "Element_001": "추가 피해 +8.00%"},
        }
    }
)


def test_parse_gems_extracts_effect():
    gem_data = {
        "Gems": [
            {
                "Slot": 0,
                "Name": "8레벨 광휘의 보석",
                "Level": 8,
                "Grade": "유물",
                "Icon": "https://example.com/gem.png",
                "Tooltip": GEM_TOOLTIP,
            }
        ]
    }
    result = parser.parse_gems(gem_data)
    assert len(result) == 1
    assert result[0]["level"] == 8
    assert result[0]["grade"] == "유물"
    assert result[0]["effect"] == "추가 피해 +8.00%"


def test_parse_gems_strips_redundant_level_prefix_from_name():
    """이름에 이미 "8레벨"이 붙어있는데(API 원본 특성) level을 따로 보여주므로 중복 제거."""
    gem_data = {"Gems": [{"Slot": 0, "Name": "8레벨 광휘의 보석", "Level": 8, "Grade": "유물", "Tooltip": "{}"}]}
    result = parser.parse_gems(gem_data)
    assert result[0]["name"] == "광휘의 보석"


def test_parse_gems_handles_none():
    assert parser.parse_gems(None) == []


def test_format_combat_power_adds_thousands_separators():
    assert parser._format_combat_power("123456789") == "123,456,789"


def test_format_combat_power_handles_none_and_non_numeric():
    assert parser._format_combat_power(None) is None
    assert parser._format_combat_power("모름") == "모름"


def test_parse_armory_detail_combines_all_sections():
    raw = {
        "ArmoryProfile": {
            "CharacterName": "테스트캐릭",
            "CharacterClassName": "홀리나이트",
            "ItemAvgLevel": "1680.00",
            "CombatPower": "123456789",
        },
        "ArmorySkills": SKILLS,
        "ArkPassive": ARK_PASSIVE,
        "ArmoryEquipment": [
            {"Type": "목걸이", "Name": "도래한 결전의 목걸이", "Grade": "고대", "Tooltip": ACCESSORY_TOOLTIP}
        ],
        "ArmoryGem": {
            "Gems": [
                {"Slot": 0, "Name": "8레벨 광휘의 보석", "Level": 8, "Grade": "유물", "Tooltip": GEM_TOOLTIP}
            ]
        },
    }
    result = parser.parse_armory_detail(raw)
    assert result["character_name"] == "테스트캐릭"
    assert result["character_class"] == "홀리나이트"
    assert result["combat_power"] == "123,456,789"
    assert len(result["skills"]) == 1
    assert len(result["ark_passive"]["points"]) == 3
    assert len(result["accessories"]) == 1
    assert len(result["gems"]) == 1
