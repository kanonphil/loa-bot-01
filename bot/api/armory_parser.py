"""로스트아크 오픈API의 아머리(장비/스킬/아크패시브/보석) 원본 응답을
웹에 그대로 보여줄 수 있는 정제된 구조로 변환한다.

원본 API의 Tooltip 필드는 HTML 태그가 섞인 문자열이거나, 그 문자열이 다시
JSON으로 인코딩된 형태(Element_000, Element_001 ... 형식)라 그대로 쓸 수 없다.
이 모듈은 순수 함수만 모아뒀다 — 네트워크 호출은 bot/services/armory.py에서 한다.
"""
import json
import re

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_ACCESSORY_TYPES = {"목걸이", "귀걸이", "반지"}
_WEAPON_ARMOR_TYPES = {"무기", "투구", "상의", "하의", "장갑", "어깨"}
_GEM_LEVEL_PREFIX_RE = re.compile(r"^\d+레벨\s*")
_HONING_LEVEL_RE = re.compile(r"^\+(\d+)\s*")
_STAT_PERCENT_RE = re.compile(r"([^,.\n]+?)(?:이|가)\s*([\d.]+)%\s*(증가|감소)")
_SIMPLE_PERCENT_RE = re.compile(r"^(.+?)\s*([+-][\d.]+)%")


def strip_html(text: str | None) -> str:
    """HTML 태그를 제거하고 <br>/<BR>은 줄바꿈으로 바꾼 평문을 돌려준다."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = _HTML_TAG_RE.sub("", text)
    return text.strip()


def parse_tooltip_json(raw: str | None) -> dict:
    """Tooltip 문자열(JSON 인코딩된 Element_XXX 딕셔너리)을 파싱. 실패하면 빈 dict."""
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def find_item_part(tooltip: dict, header_contains: str) -> str | None:
    """ItemPartBox 타입 엘리먼트 중 제목(Element_000)에 header_contains가 포함된
    항목을 찾아 본문(Element_001)을 평문으로 돌려준다. 못 찾으면 None."""
    for element in tooltip.values():
        if not isinstance(element, dict) or element.get("type") != "ItemPartBox":
            continue
        value = element.get("value") or {}
        header = value.get("Element_000", "")
        if header_contains in header:
            return strip_html(value.get("Element_001", ""))
    return None


def find_quality(tooltip: dict) -> int | None:
    """ItemTitle 엘리먼트의 qualityValue. 품질 개념이 없는 아이템(보석/룬 등)은 -1이라 None 처리."""
    for element in tooltip.values():
        if not isinstance(element, dict) or element.get("type") != "ItemTitle":
            continue
        value = element.get("value") or {}
        quality = value.get("qualityValue")
        if isinstance(quality, int) and quality >= 0:
            return quality
    return None


def quality_tier(quality: int) -> str:
    """품질 구간 분류 — 상(90+)/중(70-89)/하(70 미만). 색상은 프론트에서 이 값 기준으로 입힌다."""
    if quality >= 90:
        return "상"
    if quality >= 70:
        return "중"
    return "하"


def parse_skills(skills: list[dict]) -> list[dict]:
    """실제로 트라이포드를 선택해 사용 중인 스킬만 골라 이름/레벨/트라이포드/룬을 정리한다."""
    result = []
    for skill in skills or []:
        selected_tripods = [t for t in (skill.get("Tripods") or []) if t.get("IsSelected")]
        if not selected_tripods:
            continue

        rune = None
        raw_rune = skill.get("Rune")
        if raw_rune:
            rune_tooltip = parse_tooltip_json(raw_rune.get("Tooltip"))
            rune = {
                "name": raw_rune.get("Name"),
                "grade": raw_rune.get("Grade"),
                "effect": find_item_part(rune_tooltip, "스킬 룬 효과"),
            }

        result.append(
            {
                "name": skill.get("Name"),
                "icon": skill.get("Icon"),
                "level": skill.get("Level"),
                "tripods": [
                    {"tier": t.get("Tier"), "name": t.get("Name"), "icon": t.get("Icon")}
                    for t in sorted(selected_tripods, key=lambda t: t.get("Tier", 0))
                ],
                "rune": rune,
            }
        )
    return result


_ARK_PASSIVE_CATEGORY_ORDER = ["진화", "깨달음", "도약"]


def parse_ark_passive(ark_passive: dict | None) -> dict:
    """진화/깨달음/도약 포인트 요약 + 카테고리별로 실제 선택한 노드 목록.
    카테고리는 API가 내려주는 순서(등장 순)가 아니라 항상 진화/깨달음/도약 고정 순서로 정렬한다."""
    ark_passive = ark_passive or {}
    points = [
        {"name": p.get("Name"), "value": p.get("Value"), "description": p.get("Description")}
        for p in ark_passive.get("Points") or []
    ]

    raw_by_category: dict[str, list[str]] = {}
    for effect in ark_passive.get("Effects") or []:
        category = effect.get("Name", "기타")
        raw_by_category.setdefault(category, []).append(strip_html(effect.get("Description", "")))

    effects_by_category: dict[str, list[str]] = {}
    for category in _ARK_PASSIVE_CATEGORY_ORDER:
        if category in raw_by_category:
            effects_by_category[category] = raw_by_category.pop(category)
    effects_by_category.update(raw_by_category)  # 예상 못한 카테고리가 있으면 뒤에 붙인다

    return {"title": ark_passive.get("Title"), "points": points, "effects_by_category": effects_by_category}


def parse_accessories(equipment: list[dict]) -> list[dict]:
    """목걸이/귀걸이/반지만 골라 품질/연마 효과/아크패시브 포인트 기여를 정리한다."""
    result = []
    for item in equipment or []:
        if item.get("Type") not in _ACCESSORY_TYPES:
            continue
        tooltip = parse_tooltip_json(item.get("Tooltip"))
        quality = find_quality(tooltip)
        honing = find_item_part(tooltip, "연마 효과")
        ark_passive_bonus = find_item_part(tooltip, "아크 패시브 포인트 효과")
        honing_effects = [line for line in (honing or "").split("\n") if line.strip()]

        detail_lines = list(honing_effects)
        if ark_passive_bonus:
            detail_lines.append(ark_passive_bonus)

        result.append(
            {
                "type": item.get("Type"),
                "name": strip_html(item.get("Name")),
                "icon": item.get("Icon"),
                "grade": item.get("Grade"),
                "quality": quality,
                "quality_tier": quality_tier(quality) if quality is not None else None,
                "honing_effects": honing_effects,
                "ark_passive_bonus": ark_passive_bonus,
                "detail_text": "\n".join(detail_lines),
            }
        )
    return result


def parse_weapon_armor(equipment: list[dict]) -> list[dict]:
    """무기/방어구(투구·상의·하의·장갑·어깨) 6부위 — 강화 수치, 품질, 기본/추가 효과를 정리한다.
    이름에 붙은 "+18" 같은 강화 수치 접두어는 honing_level로 따로 뽑아내고 이름에서는 제거한다."""
    result = []
    for item in equipment or []:
        if item.get("Type") not in _WEAPON_ARMOR_TYPES:
            continue
        raw_name = strip_html(item.get("Name"))
        honing_match = _HONING_LEVEL_RE.match(raw_name)
        honing_level = honing_match.group(1) if honing_match else None
        name = _HONING_LEVEL_RE.sub("", raw_name)

        tooltip = parse_tooltip_json(item.get("Tooltip"))
        quality = find_quality(tooltip)
        base_stats = find_item_part(tooltip, "기본 효과")
        bonus_effect = find_item_part(tooltip, "추가 효과")
        ark_passive_bonus = find_item_part(tooltip, "아크 패시브 포인트 효과")
        base_stat_lines = [line for line in (base_stats or "").split("\n") if line.strip()]

        # 목록 자체는 아이콘/이름/품질만 컴팩트하게 보여주고, 세부 스탯은
        # 마우스 오버 시 뜨는 네이티브 title 툴팁으로 몰아넣는다.
        detail_lines = list(base_stat_lines)
        if bonus_effect:
            detail_lines.append(bonus_effect)
        if ark_passive_bonus:
            detail_lines.append(ark_passive_bonus)

        result.append(
            {
                "type": item.get("Type"),
                "name": name,
                "honing_level": honing_level,
                "icon": item.get("Icon"),
                "grade": item.get("Grade"),
                "quality": quality,
                "quality_tier": quality_tier(quality) if quality is not None else None,
                "base_stat_lines": base_stat_lines,
                "bonus_effect": bonus_effect,
                "ark_passive_bonus": ark_passive_bonus,
                "detail_text": "\n".join(detail_lines),
            }
        )
    return result


def parse_stat_effects(stats: list[dict] | None) -> list[dict]:
    """전투특성(특화/치명/신속/제압/인내/숙련) 툴팁에서 "OOO가 N% 증가/감소합니다" 형태의
    실제 효과 문장만 뽑아 정리한다. 보상/카드도감 안내 문구는 "%" 표기가 없어 자동으로 걸러진다."""
    result = []
    for stat in stats or []:
        for raw_line in stat.get("Tooltip") or []:
            line = strip_html(raw_line)
            match = _STAT_PERCENT_RE.search(line)
            if not match:
                continue
            name, value, direction = match.groups()
            sign = "+" if direction == "증가" else "-"
            result.append({"stat": stat.get("Type"), "text": f"{name.strip()} {sign}{value}%"})
    return result


def parse_engravings(engraving: dict | None) -> list[dict]:
    """각인 — 구 각인 아이템(Engravings)은 아크패시브 도입 이후 대부분 비어있고(null),
    실제로 장착 중인 각인 5개는 ArkPassiveEffects에 등급/레벨과 함께 내려온다."""
    engraving = engraving or {}
    result = []
    for e in engraving.get("ArkPassiveEffects") or []:
        result.append(
            {
                "name": e.get("Name"),
                "grade": e.get("Grade"),
                "level": e.get("Level"),
                "description": strip_html(e.get("Description")),
            }
        )
    return result


def parse_cards(card: dict | None) -> dict:
    """카드 — 장착된 카드 목록과, 세트효과가 활성화됐다면 그 이름/효과 설명을 정리한다."""
    card = card or {}
    cards = [
        {
            "slot": c.get("Slot"),
            "name": c.get("Name"),
            "icon": c.get("Icon"),
            "grade": c.get("Grade"),
            "awake_count": c.get("AwakeCount"),
            "awake_total": c.get("AwakeTotal"),
        }
        for c in card.get("Cards") or []
    ]
    effects = []
    for e in card.get("Effects") or []:
        # ArkPassive/ArkGrid의 Effects는 Name+Description(또는 Tooltip) 형태였다 —
        # 카드 세트효과도 같은 컨벤션일 것으로 보고 두 필드 모두 방어적으로 처리한다.
        text = e.get("Description") or e.get("Tooltip") or ""
        effects.append({"name": e.get("Name"), "text": strip_html(text)})
    return {"cards": cards, "effects": effects}


def _iter_percent_effects(text: str):
    """한 텍스트(문장/여러 줄) 안에서 "OOO가 N% 증가/감소" 또는 "OOO +N.NN%" 형태를
    전부 찾아 (이름, 부호 있는 값) 쌍으로 내보낸다. 여러 절이 붙은 긴 문장(각인 설명 등)에도
    대응하기 위해 첫 매치만 보지 않고 finditer로 전부 훑는다."""
    for match in _STAT_PERCENT_RE.finditer(text):
        name, value, direction = match.groups()
        sign = 1 if direction == "증가" else -1
        yield name.strip(), sign * float(value)
    for line in text.split("\n"):
        match = _SIMPLE_PERCENT_RE.match(line.strip())
        if match:
            name, value = match.groups()
            yield name.strip(), float(value)


def parse_aggregate_effects(
    stats: list[dict] | None,
    engravings: list[dict] | None,
    equipment: list[dict] | None,
    accessories: list[dict] | None,
) -> list[dict]:
    """전투특성 + 각인 + 장비/장신구 추가 효과에서 퍼센트 효과를 모아 이름별로 합산한다.
    참고용 종합치다 — 카드 세트효과나 아크그리드 코어 옵션 등 조건부 효과까지 완벽히
    반영한 것은 아니라 레퍼런스 사이트의 "효과 양수지"와 100% 일치하지 않을 수 있다."""
    totals: dict[str, float] = {}
    order: list[str] = []

    def add(name: str, value: float) -> None:
        if name not in totals:
            totals[name] = 0.0
            order.append(name)
        totals[name] += value

    for stat in stats or []:
        for raw_line in stat.get("Tooltip") or []:
            for name, value in _iter_percent_effects(strip_html(raw_line)):
                add(name, value)

    for eng in engravings or []:
        for name, value in _iter_percent_effects(eng.get("description") or ""):
            add(name, value)

    for item in equipment or []:
        if item.get("bonus_effect"):
            for name, value in _iter_percent_effects(item["bonus_effect"]):
                add(name, value)

    for acc in accessories or []:
        for line in acc.get("honing_effects") or []:
            for name, value in _iter_percent_effects(line):
                add(name, value)

    return [
        {"name": name, "text": f"{name} {'+' if totals[name] >= 0 else ''}{totals[name]:.2f}%"}
        for name in order
    ]


def parse_gems(gem_data: dict | None) -> list[dict]:
    """보석 슬롯/이름/레벨/등급/효과를 정리한다."""
    gem_data = gem_data or {}
    result = []
    for gem in gem_data.get("Gems") or []:
        tooltip = parse_tooltip_json(gem.get("Tooltip"))
        effect = find_item_part(tooltip, "효과")
        # 이름에 이미 "N레벨"이 접두어로 붙어있어(예: "8레벨 광휘의 보석") level을 따로 보여줄 때
        # 중복되므로 제거한다.
        name = _GEM_LEVEL_PREFIX_RE.sub("", strip_html(gem.get("Name")))
        result.append(
            {
                "slot": gem.get("Slot"),
                "name": name,
                "level": gem.get("Level"),
                "grade": gem.get("Grade"),
                "icon": gem.get("Icon"),
                "effect": effect,
            }
        )
    return result


def parse_ark_grid(ark_grid: dict | None) -> dict:
    """아크그리드: 질서/혼돈 해·달·별 코어 6개와, 전체 장착 젬을 합산한
    종합 스탯 효과(Effects)를 정리한다. 코어별 개별 젬 세부 정보는 너무 장황해서
    보여주지 않기로 했다 — 종합 스탯만으로 충분하다."""
    ark_grid = ark_grid or {}

    cores = []
    for slot in ark_grid.get("Slots") or []:
        tooltip = parse_tooltip_json(slot.get("Tooltip"))
        core_type = find_item_part(tooltip, "코어 타입") or ""
        system, _, core_name = core_type.partition(" - ")
        option_text = find_item_part(tooltip, "코어 옵션") or ""
        # Name은 "질서의 해 코어 : 빛이 생명을 새긴다"처럼 시스템/코어명 뒤에
        # 콜론으로 구분된 플레이버 텍스트가 붙어있다 — 부제로 따로 보여준다.
        _, _, flavor = (slot.get("Name") or "").partition(" : ")

        cores.append(
            {
                "name": slot.get("Name"),
                "flavor": flavor or None,
                "icon": slot.get("Icon"),
                "grade": slot.get("Grade"),
                "point": slot.get("Point"),
                "system": system or None,
                "core_name": core_name or None,
                "willpower": find_item_part(tooltip, "코어 공급 의지력"),
                "option_lines": [line for line in option_text.split("\n") if line.strip()],
            }
        )

    effects = [
        {"name": e.get("Name"), "level": e.get("Level"), "text": strip_html(e.get("Tooltip"))}
        for e in ark_grid.get("Effects") or []
    ]

    return {"cores": cores, "effects": effects}


def _format_combat_power(raw) -> str | None:
    """전투력은 문자열 숫자로 내려오는데, 천단위 콤마 없이 그대로 보여주면 자릿수를
    가늠하기 어려워 콤마를 붙인다. 숫자가 아니면(예외적인 경우) 원본을 그대로 반환."""
    if raw is None:
        return None
    try:
        return f"{int(float(raw)):,}"
    except (TypeError, ValueError):
        return str(raw)


def parse_armory_detail(raw: dict) -> dict:
    """아머리 원본 응답(profiles+equipment+combat-skills+engravings+cards+arkpassive+gems+arkgrid
    필터) 전체를 정리."""
    profile = raw.get("ArmoryProfile") or {}
    stats = profile.get("Stats")
    equipment = parse_weapon_armor(raw.get("ArmoryEquipment"))
    accessories = parse_accessories(raw.get("ArmoryEquipment"))
    engravings = parse_engravings(raw.get("ArmoryEngraving"))

    return {
        "character_name": profile.get("CharacterName"),
        "character_class": profile.get("CharacterClassName"),
        "item_level": profile.get("ItemAvgLevel"),
        "combat_power": _format_combat_power(profile.get("CombatPower")),
        "character_image": profile.get("CharacterImage"),
        "character_level": profile.get("CharacterLevel"),
        "expedition_level": profile.get("ExpeditionLevel"),
        "guild_name": profile.get("GuildName"),
        "guild_member_grade": profile.get("GuildMemberGrade"),
        "honor_point": profile.get("HonorPoint"),
        "town_level": profile.get("TownLevel"),
        "town_name": profile.get("TownName"),
        "server_name": profile.get("ServerName"),
        "skills": parse_skills(raw.get("ArmorySkills")),
        "ark_passive": parse_ark_passive(raw.get("ArkPassive")),
        "equipment": equipment,
        "accessories": accessories,
        "gems": parse_gems(raw.get("ArmoryGem")),
        "ark_grid": parse_ark_grid(raw.get("ArkGrid")),
        "stat_effects": parse_stat_effects(stats),
        "engravings": engravings,
        "cards": parse_cards(raw.get("ArmoryCard")),
        "aggregate_effects": parse_aggregate_effects(stats, engravings, equipment, accessories),
    }
