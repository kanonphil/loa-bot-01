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
        {
            "Type": "목걸이", "Name": "도래한 결전의 목걸이", "Icon": "https://example.com/necklace.png",
            "Grade": "고대", "Tooltip": ACCESSORY_TOOLTIP,
        },
        {"Type": "무기", "Name": "어떤 무기", "Grade": "유물", "Tooltip": "{}"},
    ]
    result = parser.parse_accessories(equipment)
    assert len(result) == 1  # 무기는 장신구가 아니므로 제외
    acc = result[0]
    assert acc["type"] == "목걸이"
    assert acc["icon"] == "https://example.com/necklace.png"
    assert acc["grade"] == "고대"
    assert acc["quality"] == 96
    assert acc["quality_tier"] == "상"
    assert acc["honing_effects"] == ["낙인력 +8.00%", "최대 마나 +6"]
    assert acc["ark_passive_bonus"] == "깨달음 +13"
    assert acc["detail_text"] == "낙인력 +8.00%\n최대 마나 +6\n깨달음 +13"


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
        "Icon": "https://example.com/skill-ganpa.png",
        "Level": 1,
        "Tripods": [
            {"Tier": 0, "Slot": 1, "Name": "강화 베기", "Icon": "https://example.com/t1.png", "IsSelected": False},
            {"Tier": 0, "Slot": 2, "Name": "약육강식", "Icon": "https://example.com/t2.png", "IsSelected": False},
        ],
        "Rune": None,
    },
    {
        "Name": "계시의 검",
        "Icon": "https://example.com/skill-gyesi.png",
        "Level": 10,
        "Tripods": [
            {"Tier": 0, "Slot": 2, "Name": "부위파괴 강화", "Icon": "https://example.com/t3.png", "IsSelected": True},
            {"Tier": 1, "Slot": 3, "Name": "신앙심", "Icon": "https://example.com/t4.png", "IsSelected": True},
            {"Tier": 2, "Slot": 2, "Name": "더블 크로스", "Icon": "https://example.com/t5.png", "IsSelected": True},
            {"Tier": 2, "Slot": 1, "Name": "선택 안 한 것", "Icon": "https://example.com/t6.png", "IsSelected": False},
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


def test_parse_skills_includes_skill_and_tripod_icons():
    result = parser.parse_skills(SKILLS)
    assert result[0]["icon"] == "https://example.com/skill-gyesi.png"
    assert result[0]["tripods"][0]["icon"] == "https://example.com/t3.png"


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


def test_parse_ark_passive_orders_categories_evolution_realization_leap():
    """API가 내려주는 Effects 순서(이 픽스처는 깨달음이 먼저 나옴)와 무관하게
    항상 진화 → 깨달음 → 도약 순으로 정렬돼야 한다 (가로 배치 UI가 이 순서를 그대로 씀)."""
    result = parser.parse_ark_passive(ARK_PASSIVE)
    assert list(result["effects_by_category"].keys()) == ["진화", "깨달음"]


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


CORE_TOOLTIP = json.dumps(
    {
        "Element_004": {
            "type": "ItemPartBox",
            "value": {"Element_000": "<FONT COLOR='#A9D0F5'>코어 타입</FONT>", "Element_001": "질서 - 해"},
        },
        "Element_005": {
            "type": "ItemPartBox",
            "value": {
                "Element_000": "<FONT COLOR='#A9D0F5'>코어 공급 의지력</FONT>",
                "Element_001": "<FONT COLOR='#B7FB00'>15</FONT> 포인트",
            },
        },
        "Element_006": {
            "type": "ItemPartBox",
            "value": {
                "Element_000": "<FONT COLOR='#A9D0F5'>코어 옵션</FONT>",
                "Element_001": "[10P] 아군 공격력 강화 효과 +1.3%<br>[18P] 아군 공격력 강화 효과 +0.15%",
            },
        },
    }
)

ARK_GRID = {
    "Slots": [
        {
            "Index": 0,
            "Icon": "https://example.com/core-sun.png",
            "Name": "질서의 해 코어 : 빛이 생명을 새긴다",
            "Point": 18,
            "Grade": "유물",
            "Tooltip": CORE_TOOLTIP,
            # 코어에 장착된 젬 원본 데이터(Gems)는 파서가 더 이상 읽지 않는다 —
            # 개별 젬 세부 정보는 너무 장황해서 종합 스탯(Effects)만 보여주기로 했다.
            "Gems": [{"Index": 0, "Icon": "https://example.com/gem-order.png", "IsActive": True, "Grade": "전설"}],
        }
    ],
    "Effects": [
        {"Name": "공격력", "Level": 29, "Tooltip": "공격력 <font color='#ffd200'>+1.06%</font>"},
        {"Name": "낙인력", "Level": 44, "Tooltip": "낙인력 <font color='#ffd200'>+7.33%</font>"},
    ],
}


def test_parse_ark_grid_extracts_core_type_point_and_options():
    result = parser.parse_ark_grid(ARK_GRID)
    core = result["cores"][0]
    assert core["system"] == "질서"
    assert core["core_name"] == "해"
    assert core["point"] == 18
    assert core["grade"] == "유물"
    assert core["willpower"] == "15 포인트"
    assert core["flavor"] == "빛이 생명을 새긴다"
    assert core["option_lines"] == [
        "[10P] 아군 공격력 강화 효과 +1.3%",
        "[18P] 아군 공격력 강화 효과 +0.15%",
    ]


def test_parse_ark_grid_does_not_include_per_core_gem_details():
    """코어에 장착된 젬의 세부 정보(아이콘/효과 텍스트)는 너무 장황해서 보여주지 않기로 했다."""
    result = parser.parse_ark_grid(ARK_GRID)
    assert "gems" not in result["cores"][0]


def test_parse_ark_grid_extracts_aggregate_stat_effects():
    result = parser.parse_ark_grid(ARK_GRID)
    assert result["effects"] == [
        {"name": "공격력", "level": 29, "text": "공격력 +1.06%"},
        {"name": "낙인력", "level": 44, "text": "낙인력 +7.33%"},
    ]


def test_parse_ark_grid_handles_none():
    result = parser.parse_ark_grid(None)
    assert result == {"cores": [], "effects": []}


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
            "CharacterImage": "https://example.com/char.png",
            "CharacterLevel": 70,
            "ExpeditionLevel": 293,
            "GuildName": "동물롱장",
            "GuildMemberGrade": "일반 길드원",
            "HonorPoint": 220,
            "TownLevel": 70,
            "TownName": "졸타뉴 마을",
            "ServerName": "루페온",
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
        "ArkGrid": ARK_GRID,
    }
    result = parser.parse_armory_detail(raw)
    assert result["character_name"] == "테스트캐릭"
    assert result["character_class"] == "홀리나이트"
    assert result["combat_power"] == "123,456,789"
    assert result["guild_name"] == "동물롱장"
    assert result["guild_member_grade"] == "일반 길드원"
    assert result["character_level"] == 70
    assert result["expedition_level"] == 293
    assert result["honor_point"] == 220
    assert result["town_level"] == 70
    assert result["town_name"] == "졸타뉴 마을"
    assert result["server_name"] == "루페온"
    assert len(result["skills"]) == 1
    assert len(result["ark_passive"]["points"]) == 3
    assert len(result["accessories"]) == 1
    assert len(result["gems"]) == 1
    assert len(result["ark_grid"]["cores"]) == 1
    assert len(result["ark_grid"]["effects"]) == 2


# ── 무기/방어구 (실제 API 응답 샘플 기반) ──────────────────────

WEAPON_TOOLTIP = json.dumps(
    {
        "Element_000": {"type": "NameTagBox", "value": "<P ALIGN='CENTER'><FONT COLOR='#E3C7A1'>+18 운명의 전율 한손검</FONT></P>"},
        "Element_001": {
            "type": "ItemTitle",
            "value": {"leftStr0": "고대 한손검", "qualityValue": 100, "rightStr0": "장착중"},
        },
        "Element_005": {
            "type": "ItemPartBox",
            "value": {"Element_000": "<FONT COLOR='#A9D0F5'>기본 효과</FONT>", "Element_001": "무기 공격력 +203054"},
        },
        "Element_007": {
            "type": "ItemPartBox",
            "value": {"Element_000": "<FONT COLOR='#A9D0F5'>추가 효과</FONT>", "Element_001": "추가 피해 +30.00%"},
        },
    }
)

ARMOR_TOOLTIP = json.dumps(
    {
        "Element_000": {"type": "NameTagBox", "value": "<P ALIGN='CENTER'><FONT COLOR='#E3C7A1'>+17 운명의 전율 투구</FONT></P>"},
        "Element_001": {
            "type": "ItemTitle",
            "value": {"leftStr0": "고대 머리 방어구", "qualityValue": 99, "rightStr0": "장착중"},
        },
        "Element_005": {
            "type": "ItemPartBox",
            "value": {
                "Element_000": "<FONT COLOR='#A9D0F5'>기본 효과</FONT>",
                "Element_001": "물리 방어력 +9497<BR>마법 방어력 +10552<BR>힘 +114358<BR>체력 +11117",
            },
        },
        "Element_007": {
            "type": "ItemPartBox",
            "value": {"Element_000": "<FONT COLOR='#A9D0F5'>추가 효과</FONT>", "Element_001": "생명 활성력 +1373"},
        },
        "Element_009": {
            "type": "ItemPartBox",
            "value": {"Element_000": "<FONT COLOR='#A9D0F5'>아크 패시브 포인트 효과</FONT>", "Element_001": "진화 +24"},
        },
    }
)

WEAPON_ARMOR_EQUIPMENT = [
    {
        "Type": "무기",
        "Name": "+18 운명의 전율 한손검",
        "Icon": "https://example.com/weapon.png",
        "Grade": "고대",
        "Tooltip": WEAPON_TOOLTIP,
    },
    {
        "Type": "투구",
        "Name": "+17 운명의 전율 투구",
        "Icon": "https://example.com/helmet.png",
        "Grade": "고대",
        "Tooltip": ARMOR_TOOLTIP,
    },
    {"Type": "목걸이", "Name": "장신구는 여기 안 나옴", "Grade": "고대", "Tooltip": "{}"},
]


def test_parse_weapon_armor_extracts_honing_level_and_strips_from_name():
    result = parser.parse_weapon_armor(WEAPON_ARMOR_EQUIPMENT)
    weapon = next(i for i in result if i["type"] == "무기")
    assert weapon["honing_level"] == "18"
    assert weapon["name"] == "운명의 전율 한손검"


def test_parse_weapon_armor_excludes_accessories():
    result = parser.parse_weapon_armor(WEAPON_ARMOR_EQUIPMENT)
    assert len(result) == 2
    assert all(i["type"] != "목걸이" for i in result)


def test_parse_weapon_armor_extracts_quality_and_effects():
    result = parser.parse_weapon_armor(WEAPON_ARMOR_EQUIPMENT)
    weapon = next(i for i in result if i["type"] == "무기")
    assert weapon["quality"] == 100
    assert weapon["quality_tier"] == "상"
    assert weapon["base_stat_lines"] == ["무기 공격력 +203054"]
    assert weapon["bonus_effect"] == "추가 피해 +30.00%"
    assert weapon["ark_passive_bonus"] is None  # 무기는 아크 패시브 포인트 효과가 없음

    armor = next(i for i in result if i["type"] == "투구")
    assert armor["quality"] == 99
    assert armor["base_stat_lines"] == [
        "물리 방어력 +9497",
        "마법 방어력 +10552",
        "힘 +114358",
        "체력 +11117",
    ]
    assert armor["bonus_effect"] == "생명 활성력 +1373"
    assert armor["ark_passive_bonus"] == "진화 +24"


def test_parse_weapon_armor_builds_detail_text_for_hover_tooltip():
    """목록은 아이콘/이름/품질만 컴팩트하게 보여주고, 세부 스탯은 title 툴팁으로 몰아넣는다."""
    result = parser.parse_weapon_armor(WEAPON_ARMOR_EQUIPMENT)
    armor = next(i for i in result if i["type"] == "투구")
    assert armor["detail_text"] == (
        "물리 방어력 +9497\n마법 방어력 +10552\n힘 +114358\n체력 +11117\n생명 활성력 +1373\n진화 +24"
    )


# ── 전투특성 효과 (실제 API 응답 샘플 기반) ────────────────────

STATS_SAMPLE = [
    {
        "Type": "신속",
        "Value": "1804",
        "Tooltip": [
            "<textformat indent='-21' leftMargin='10'><font> </font> 공격 속도가 <font color='#99ff99'>30.99%</font> 증가합니다.</textformat>",
            "<textformat indent='-21' leftMargin='10'><font> </font> 이동 속도가 <font color='#99ff99'>30.99%</font> 증가합니다.</textformat>",
            "<textformat indent='-21' leftMargin='10'><font> </font> 스킬 재사용 대기시간이 <font color='#99ff99'>38.73%</font> 감소합니다.</textformat>",
            "<textformat indent='-21' leftMargin='10'><font> </font> 물약 및 원정대 레벨 보상 효과로 <font color='#99ff99'>32</font>만큼 영구적으로 증가되었습니다.</textformat>",
            "<textformat indent='-21' leftMargin='10'><font> </font> 카드 도감 누적 효과가 반영된 값으로 전투정보실에서는 별도 수치를 표기하지 않습니다.</textformat>",
        ],
    }
]


def test_parse_stat_effects_extracts_percent_lines_only():
    result = parser.parse_stat_effects(STATS_SAMPLE)
    texts = [r["text"] for r in result]
    assert texts == ["공격 속도 +30.99%", "이동 속도 +30.99%", "스킬 재사용 대기시간 -38.73%"]
    assert all(r["stat"] == "신속" for r in result)


def test_parse_stat_effects_ignores_boilerplate_lines_without_percent():
    """"32만큼 영구적으로 증가" 같은 보상 안내 문구는 %가 없어서 자동으로 제외돼야 한다."""
    result = parser.parse_stat_effects(STATS_SAMPLE)
    assert not any("32" in r["text"] for r in result)
    assert not any("카드 도감" in r["text"] for r in result)


def test_parse_stat_effects_handles_none():
    assert parser.parse_stat_effects(None) == []


# ── 각인 (실제 API 응답 샘플 기반 — 구 Engravings는 null, ArkPassiveEffects에 들어있음) ──

ENGRAVING_SAMPLE = {
    "Engravings": None,
    "Effects": None,
    "ArkPassiveEffects": [
        {
            "AbilityStoneLevel": 3,
            "Grade": "유물",
            "Level": 4,
            "Name": "각성",
            "Description": "각성기의 재사용 대기시간이 <FONT COLOR='#99ff99'>60.50%</FONT> 감소하고, 사용 제한 횟수가 <FONT COLOR='#99ff99'>5</FONT>회 증가한다.",
        },
        {
            "AbilityStoneLevel": None,
            "Grade": "유물",
            "Level": 4,
            "Name": "급소 타격",
            "Description": "무력화 공격 시 주는 무력화 수치가 <FONT COLOR='#99ff99'>37.00%</FONT> 증가한다.",
        },
    ],
}


def test_parse_engravings_extracts_name_grade_level_description():
    result = parser.parse_engravings(ENGRAVING_SAMPLE)
    assert len(result) == 2
    assert result[0]["name"] == "각성"
    assert result[0]["grade"] == "유물"
    assert result[0]["level"] == 4
    assert "60.50%" in result[0]["description"]
    assert "<FONT" not in result[0]["description"]  # HTML 태그 제거 확인


def test_parse_engravings_handles_none():
    assert parser.parse_engravings(None) == []


# ── 카드 ────────────────────────────────────────────────

CARD_SAMPLE = {
    "Cards": [
        {"Slot": 0, "Name": "아만", "Icon": "https://example.com/card.png", "AwakeCount": 5, "AwakeTotal": 5, "Grade": "전설"},
    ],
    "Effects": [
        {"Name": "남겨진 바람의 절벽", "Description": "암속성 피해 감소 <FONT COLOR='#99ff99'>+25.00%</FONT>"},
    ],
}


def test_parse_cards_extracts_card_list_and_set_effects():
    result = parser.parse_cards(CARD_SAMPLE)
    assert result["cards"][0]["name"] == "아만"
    assert result["cards"][0]["awake_count"] == 5
    assert result["effects"][0]["name"] == "남겨진 바람의 절벽"
    assert result["effects"][0]["text"] == "암속성 피해 감소 +25.00%"


def test_parse_cards_handles_none():
    assert parser.parse_cards(None) == {"cards": [], "effects": []}


# ── 종합 효과(효과 양수지) — 전투특성/각인/장비/장신구에서 % 효과를 모아 이름별로 합산 ──

def test_parse_aggregate_effects_sums_same_named_stat_across_sources():
    stats = [{"Type": "신속", "Tooltip": ["공격 속도가 <font>30.99%</font> 증가합니다."]}]
    engravings = [{"description": "무력화 공격 시 주는 무력화 수치가 37.00% 증가한다."}]
    equipment = [{"bonus_effect": "추가 피해 +30.00%"}]
    accessories = [{"honing_effects": ["낙인력 +8.00%", "낙인력 +2.00%"]}]

    result = parser.parse_aggregate_effects(stats, engravings, equipment, accessories)
    by_name = {r["name"]: r["text"] for r in result}
    assert by_name["공격 속도"] == "공격 속도 +30.99%"
    assert by_name["추가 피해"] == "추가 피해 +30.00%"
    assert by_name["낙인력"] == "낙인력 +10.00%"  # 8.00 + 2.00 합산


def test_parse_aggregate_effects_handles_all_none():
    assert parser.parse_aggregate_effects(None, None, None, None) == []
