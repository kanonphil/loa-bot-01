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
# "최대 마나 +6", "치명 +195" 같은 고정 수치 라인 (%가 붙으면 위 규칙이 먼저 잡는다)
_SIMPLE_FLAT_RE = re.compile(r"^(.+?)\s*\+([\d,]+)$")
# 문장 안의 "+1.99%" / "-6.00%" 같은 수치 토큰
_VALUE_TOKEN_RE = re.compile(r"[+-][\d.,]+%?")
# 아크그리드 코어 옵션의 "[10P] 효과 설명" 형식
_CORE_OPTION_RE = re.compile(r"^\[(\d+)P\]\s*(.*)$")


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
# "진화 1티어 예리한 둔기 Lv.2" / "1티어 신속 Lv.30" — 카테고리 접두어는 있을 수도 없을 수도 있다.
_ARK_NODE_RE = re.compile(r"(?:진화|깨달음|도약)?\s*(\d+)티어\s*(.+?)\s*Lv\.(\d+)")


def _sorted_by_category(raw_by_category: dict[str, list]) -> dict[str, list]:
    """API가 내려주는 순서(등장 순)와 무관하게 항상 진화/깨달음/도약 고정 순서로 정렬한다."""
    ordered: dict[str, list] = {}
    for category in _ARK_PASSIVE_CATEGORY_ORDER:
        if category in raw_by_category:
            ordered[category] = raw_by_category.pop(category)
    ordered.update(raw_by_category)  # 예상 못한 카테고리가 있으면 뒤에 붙인다
    return ordered


def parse_ark_passive(ark_passive: dict | None) -> dict:
    """진화/깨달음/도약 포인트 요약 + 카테고리별로 실제 선택한 노드 목록.
    노드는 "N티어 이름 Lv.X" 문장을 구조화(nodes_by_category)해서 레퍼런스처럼
    티어 배지 + 이름 + 레벨로 보여줄 수 있게 하고, 원문(effects_by_category)도 유지한다."""
    ark_passive = ark_passive or {}
    points = [
        {"name": p.get("Name"), "value": p.get("Value"), "description": p.get("Description")}
        for p in ark_passive.get("Points") or []
    ]

    raw_by_category: dict[str, list[str]] = {}
    nodes_by_category: dict[str, list[dict]] = {}
    for effect in ark_passive.get("Effects") or []:
        category = effect.get("Name", "기타")
        text = strip_html(effect.get("Description", ""))
        raw_by_category.setdefault(category, []).append(text)

        match = _ARK_NODE_RE.search(text)
        node = {"tier": None, "name": text, "level": None, "icon": effect.get("Icon")}
        if match:
            node.update(tier=int(match.group(1)), name=match.group(2), level=int(match.group(3)))
        nodes_by_category.setdefault(category, []).append(node)

    return {
        "title": ark_passive.get("Title"),
        "points": points,
        "effects_by_category": _sorted_by_category(raw_by_category),
        "nodes_by_category": _sorted_by_category(nodes_by_category),
    }


# T4 장신구 연마 효과의 옵션별 (하/중/상) 수치표 — 값이 어느 단계 롤인지로 색을 입힌다.
# 이름이 겹치는 항목("아군 공격력 강화 효과" ⊃ "공격력")이 있어 긴 이름부터 매칭한다.
_GRIND_PCT_TIERS = {
    "추가 피해": (0.70, 1.60, 2.60),
    "적에게 주는 피해": (0.55, 1.20, 2.00),
    "낙인력": (2.15, 4.80, 8.00),
    "게이지 획득량": (1.60, 3.60, 6.00),  # 세레나데, 신앙, 조화 게이지 획득량
    "치명타 적중률": (0.40, 0.95, 1.55),
    "치명타 피해": (1.10, 2.40, 4.00),
    "무기 공격력": (0.90, 1.80, 3.00),
    "공격력": (0.40, 0.95, 1.55),
    "파티원 회복 효과": (0.95, 2.10, 3.50),
    "파티원 보호막 효과": (0.95, 2.10, 3.50),
    "아군 공격력 강화 효과": (1.35, 3.00, 5.00),
    "아군 피해량 강화 효과": (2.00, 4.50, 7.50),
    "상태이상 공격 지속시간": (0.20, 0.50, 1.00),
}
_GRIND_FLAT_TIERS = {
    "무기 공격력": (195, 480, 960),
    "공격력": (80, 195, 390),
    "최대 생명력": (1300, 3250, 6500),
    "최대 마나": (6, 15, 30),
    "전투 중 생명력 회복량": (10, 25, 50),
}
_GRIND_TIER_NAMES = ("하", "중", "상")
_GRIND_VALUE_RE = re.compile(r"\+([\d.,]+)\s*(%?)")


def grind_tier(line: str) -> str | None:
    """연마 효과 한 줄("낙인력 +8.00%")이 하/중/상 어느 단계 롤인지 판별.
    수치표에 없는 옵션이거나 값이 표와 안 맞으면(밸런스 패치 등) None — 색 없이 보여준다."""
    match = _GRIND_VALUE_RE.search(line)
    if not match:
        return None
    value = float(match.group(1).replace(",", ""))
    table = _GRIND_PCT_TIERS if match.group(2) else _GRIND_FLAT_TIERS
    for name in sorted(table, key=len, reverse=True):
        if name in line:
            for tier_name, tier_value in zip(_GRIND_TIER_NAMES, table[name]):
                if abs(value - tier_value) < 0.011:
                    return tier_name
            return None
    return None


def parse_accessories(equipment: list[dict]) -> list[dict]:
    """목걸이/귀걸이/반지만 골라 기본 효과(힘/민첩/지능)/연마 효과(+단계)/아크패시브
    포인트 기여를 정리한다."""
    result = []
    for item in equipment or []:
        if item.get("Type") not in _ACCESSORY_TYPES:
            continue
        tooltip = parse_tooltip_json(item.get("Tooltip"))
        quality = find_quality(tooltip)
        base_stats = find_item_part(tooltip, "기본 효과")
        honing = find_item_part(tooltip, "연마 효과")
        ark_passive_bonus = find_item_part(tooltip, "아크 패시브 포인트 효과")
        base_stat_lines = [line for line in (base_stats or "").split("\n") if line.strip()]
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
                "base_stat_lines": base_stat_lines,
                "honing_effects": honing_effects,
                "honing_options": [{"text": line, "tier": grind_tier(line)} for line in honing_effects],
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


# 화면에 보여줄 기타 장비 화이트리스트 겸 배치 순서 — 팔찌/어빌리티 스톤은 반지 열 아래,
# 보주는 귀걸이 열 아래 (템플릿이 이 정렬 순서를 그대로 쓴다).
# 나침반/부적 등 전투와 무관한 아이템은 화면만 어지럽혀서 아예 제외한다.
_EXTRA_EQUIP_ORDER = ["팔찌", "어빌리티 스톤", "보주"]
# 장비 획득처/상인 판매 안내 같은 잡다한 섹션은 빼고, 실제 효과만 보여준다.
_EXTRA_SECTION_KEYWORDS = ("효과", "각인", "보너스")


def parse_extra_equipment(equipment: list[dict] | None) -> list[dict]:
    """무기/방어구/장신구 외 장착 아이템 중 팔찌/어빌리티 스톤/보주만 정리한다.
    아이템 종류마다 Tooltip 구조가 달라서, ItemPartBox 섹션 중 제목에 효과/각인/보너스가
    들어간 것들을 (제목, 줄 목록) 그대로 수집하는 방어적 방식을 쓴다."""
    result = []
    for item in equipment or []:
        item_type = item.get("Type")
        if item_type not in _EXTRA_EQUIP_ORDER:
            continue
        tooltip = parse_tooltip_json(item.get("Tooltip"))
        sections = []
        for element in tooltip.values():
            if not isinstance(element, dict) or element.get("type") != "ItemPartBox":
                continue
            value = element.get("value") or {}
            header = strip_html(value.get("Element_000", ""))
            body = strip_html(value.get("Element_001", ""))
            if not header or not body:
                continue
            if not any(keyword in header for keyword in _EXTRA_SECTION_KEYWORDS):
                continue
            sections.append(
                {"header": header, "lines": [line for line in body.split("\n") if line.strip()]}
            )
        quality = find_quality(tooltip)
        result.append(
            {
                "type": item_type,
                "name": strip_html(item.get("Name")),
                "icon": item.get("Icon"),
                "grade": item.get("Grade"),
                "quality": quality,
                "quality_tier": quality_tier(quality) if quality is not None else None,
                "sections": sections,
            }
        )
    order = {t: i for i, t in enumerate(_EXTRA_EQUIP_ORDER)}
    result.sort(key=lambda x: order.get(x["type"], len(order)))
    return result


_COMBAT_STAT_ORDER = ["치명", "특화", "신속", "제압", "인내", "숙련"]


def _format_int(raw) -> str | None:
    if raw is None:
        return None
    try:
        return f"{int(float(raw)):,}"
    except (TypeError, ValueError):
        return str(raw)


def parse_profile_stats(stats: list[dict] | None) -> dict:
    """프로필 Stats에서 공격력/최대 생명력과 전투특성 6종의 수치를 뽑는다.
    전투특성은 게임 내 표기 순서(치명/특화/신속/제압/인내/숙련)로 고정한다."""
    by_type = {s.get("Type"): s.get("Value") for s in stats or []}
    return {
        "attack_power": _format_int(by_type.get("공격력")),
        "max_hp": _format_int(by_type.get("최대 생명력")),
        "combat": [
            {"type": t, "value": by_type[t]} for t in _COMBAT_STAT_ORDER if by_type.get(t) is not None
        ],
    }


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
                # 어빌리티 스톤으로 활성화된 각인이면 그 스톤 세공 레벨 (아니면 None)
                "ability_stone_level": e.get("AbilityStoneLevel"),
                "description": strip_html(e.get("Description")),
            }
        )
    return result


# "남겨진 바람의 절벽 6세트 (12각성)" → 세트 이름만 남기기 위한 접미어 제거 규칙
_CARD_SET_SUFFIX_RE = re.compile(r"\s*\d+세트.*$")


def parse_cards(card: dict | None) -> dict:
    """카드 — 장착된 카드 목록, 총 각성 수, 세트 이름, 세트효과 설명을 정리한다."""
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
    total_awake = sum(c["awake_count"] or 0 for c in cards)

    # 실제 응답의 Effects는 [{"Index": 0, "Items": [{Name, Description}, ...]}]처럼
    # Items로 한 겹 감싸져 있다 (세트 이름이 "남겨진 바람의 절벽 6세트 (12각성)" 형태로
    # Items 안에 들어있음). 감싸지지 않은 평면 형태(Name/Description 직접)도 함께 처리한다.
    entries = []
    for e in card.get("Effects") or []:
        if not isinstance(e, dict):
            continue
        if isinstance(e.get("Items"), list):
            entries.extend(i for i in e["Items"] if isinstance(i, dict))
        else:
            entries.append(e)

    effects = []
    for e in entries:
        # 이름/본문이 둘 다 없는 항목은 "None —" 같은 깨진 줄이 보이지 않도록 건너뛴다.
        name = e.get("Name")
        text = strip_html(e.get("Description") or e.get("Tooltip") or "")
        if not name and not text:
            continue
        effects.append({"name": name, "text": text})

    # 세트 이름 — "남겨진 바람의 절벽 6세트 (12각성)"에서 "N세트" 이후를 잘라낸다.
    # 화면에는 "남겨진 바람의 절벽 30각"처럼 세트 이름 + 총 각성 수로 보여준다.
    set_name = None
    for eff in effects:
        candidate = _CARD_SET_SUFFIX_RE.sub("", eff["name"] or "").strip()
        if candidate:
            set_name = candidate
            break

    return {"cards": cards, "effects": effects, "total_awake": total_awake, "set_name": set_name}


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


# 효과 영수증에 넣기엔 이름이 아닌 문장 조각(팔찌 특수효과 설명 등)인 항목을 걸러내는 기준.
# 실제 스탯 이름은 "상태이상 공격 지속시간"(12자) 정도가 최장이라 20자면 충분하다.
_EFFECT_NAME_MAX_LEN = 20
_BRACKET_PREFIX_RE = re.compile(r"^\[[^\]]+\]\s*")


def _clean_effect_name(name: str) -> str:
    """팔찌 효과의 "[비수] 무기 공격력" 같은 대괄호 태그 접두어를 제거한다."""
    return _BRACKET_PREFIX_RE.sub("", name).strip()


def _iter_flat_effects(text: str):
    """"최대 마나 +6", "치명 +195" 같은 %가 없는 고정 수치 라인을 (이름, 값)으로 내보낸다."""
    for line in text.split("\n"):
        line = line.strip()
        if "%" in line:
            continue
        match = _SIMPLE_FLAT_RE.match(line)
        if match:
            name, value = match.groups()
            try:
                yield name.strip(), int(value.replace(",", ""))
            except ValueError:
                continue


def parse_aggregate_effects(
    stats: list[dict] | None,
    engravings: list[dict] | None,
    equipment: list[dict] | None,
    accessories: list[dict] | None,
    extras: list[dict] | None = None,
) -> list[dict]:
    """전투특성 + 각인 + 장비/장신구 추가 효과 + 팔찌/스톤에서 퍼센트·고정 수치 효과를
    모아 이름별로 합산한다("효과 영수증"). 참고용 종합치다 — 카드 세트효과나 아크그리드
    코어 옵션 등 조건부 효과까지 완벽히 반영한 것은 아니라 레퍼런스 사이트와 100%
    일치하지 않을 수 있다. 반환 항목: name / value_text(우측 정렬용 값) / text(전체 문장)."""
    pct_totals: dict[str, float] = {}
    flat_totals: dict[str, int] = {}
    order: list[tuple[str, str]] = []  # (이름, "pct"|"flat") — 등장 순서 유지

    def add_pct(name: str, value: float) -> None:
        name = _clean_effect_name(name)
        if not name or len(name) > _EFFECT_NAME_MAX_LEN:
            return  # 스탯 이름이 아니라 문장 조각 — 영수증만 지저분해지므로 버린다
        if name not in pct_totals:
            pct_totals[name] = 0.0
            order.append((name, "pct"))
        pct_totals[name] += value

    def add_flat(name: str, value: int) -> None:
        name = _clean_effect_name(name)
        if not name or len(name) > _EFFECT_NAME_MAX_LEN:
            return
        if name not in flat_totals:
            flat_totals[name] = 0
            order.append((name, "flat"))
        flat_totals[name] += value

    def add_all(text: str) -> None:
        for name, value in _iter_percent_effects(text):
            add_pct(name, value)
        for name, value in _iter_flat_effects(text):
            add_flat(name, value)

    for stat in stats or []:
        for raw_line in stat.get("Tooltip") or []:
            for name, value in _iter_percent_effects(strip_html(raw_line)):
                add_pct(name, value)

    for eng in engravings or []:
        for name, value in _iter_percent_effects(eng.get("description") or ""):
            add_pct(name, value)

    for item in equipment or []:
        if item.get("bonus_effect"):
            add_all(item["bonus_effect"])

    for acc in accessories or []:
        for line in acc.get("honing_effects") or []:
            add_all(line)

    for extra in extras or []:
        for section in extra.get("sections") or []:
            for line in section.get("lines") or []:
                add_all(line)

    result = []
    for name, kind in order:
        if kind == "pct":
            value_text = f"{'+' if pct_totals[name] >= 0 else ''}{pct_totals[name]:.2f}%"
        else:
            value_text = f"{'+' if flat_totals[name] >= 0 else ''}{flat_totals[name]:,}"
        result.append({"name": name, "value_text": value_text, "text": f"{name} {value_text}"})
    return result


def _parse_gem_skill_map(gem_data: dict) -> dict:
    """ArmoryGem.Effects — 보석 슬롯별로 어떤 스킬에 적용되는지 매핑.
    문서 기준 {"Description": ..., "Skills": [{GemSlot, Name, Icon, Description: [...]}]} 형태지만,
    구버전(리스트) 응답도 있어 두 형태 모두 방어적으로 처리한다."""
    effects = gem_data.get("Effects")
    skills = effects.get("Skills") if isinstance(effects, dict) else effects
    mapping: dict[int, dict] = {}
    for s in skills or []:
        if not isinstance(s, dict):
            continue
        desc = s.get("Description")
        if isinstance(desc, list):
            lines = [strip_html(d) for d in desc]
        else:
            lines = [strip_html(desc)] if desc else []
        mapping[s.get("GemSlot")] = {
            "skill_name": strip_html(s.get("Name")),
            "skill_icon": s.get("Icon"),
            "effect_lines": [line for line in lines if line],
        }
    return mapping


def _classify_gem(text: str, name: str) -> str:
    """보석을 레퍼런스처럼 "피해 증가"/"쿨타임 감소" 그룹으로 분류.
    효과 문구를 우선 보고, 문구가 없으면 보석 이름(겁화/멸화=피해, 작열/홍염=쿨감)으로 판단."""
    if "재사용 대기시간" in text and "감소" in text:
        return "쿨감"
    if "피해" in text and "증가" in text:
        return "피해"
    if "겁화" in name or "멸화" in name:
        return "피해"
    if "작열" in name or "홍염" in name:
        return "쿨감"
    return "기타"


def parse_gems(gem_data: dict | None) -> list[dict]:
    """보석 슬롯/이름/레벨/등급/효과 + 적용 스킬(이름/아이콘)과 피해/쿨감 분류를 정리한다."""
    gem_data = gem_data or {}
    skill_map = _parse_gem_skill_map(gem_data)
    result = []
    for gem in gem_data.get("Gems") or []:
        tooltip = parse_tooltip_json(gem.get("Tooltip"))
        effect = find_item_part(tooltip, "효과")
        # 이름에 이미 "N레벨"이 접두어로 붙어있어(예: "8레벨 광휘의 보석") level을 따로 보여줄 때
        # 중복되므로 제거한다.
        name = _GEM_LEVEL_PREFIX_RE.sub("", strip_html(gem.get("Name")))
        mapped = skill_map.get(gem.get("Slot")) or {}
        effect_lines = mapped.get("effect_lines") or [
            line for line in (effect or "").split("\n") if line.strip()
        ]
        result.append(
            {
                "slot": gem.get("Slot"),
                "name": name,
                "level": gem.get("Level"),
                "grade": gem.get("Grade"),
                "icon": gem.get("Icon"),
                "effect": effect,
                "skill_name": mapped.get("skill_name"),
                "skill_icon": mapped.get("skill_icon"),
                "effect_lines": effect_lines,
                "kind": _classify_gem(" ".join(effect_lines) or (effect or ""), name),
            }
        )
    return result


_GEM_BASE_ATK_RE = re.compile(r"기본 공격력\s*(?:이|가)?\s*\+?([\d.]+)\s*%")
_GEM_SUPPORT_RE = re.compile(r"지원 효과\s*(?:이|가)?\s*\+?([\d.]+)\s*%")


def summarize_gems(gems: list[dict]) -> dict:
    """보석을 피해/쿨감/기타 그룹으로 나누고, 광휘 보석의 기본 공격력·지원 효과 총합을 계산한다.
    (레퍼런스 사이트 보석 탭 상단의 "기본 공격력 총합 / 지원 효과 총합"에 대응)"""
    base_atk = 0.0
    support = 0.0
    for gem in gems:
        text = " ".join(gem.get("effect_lines") or []) or (gem.get("effect") or "")
        for m in _GEM_BASE_ATK_RE.finditer(text):
            base_atk += float(m.group(1))
        for m in _GEM_SUPPORT_RE.finditer(text):
            support += float(m.group(1))
    return {
        "damage": [g for g in gems if g["kind"] == "피해"],
        "cooldown": [g for g in gems if g["kind"] == "쿨감"],
        "etc": [g for g in gems if g["kind"] == "기타"],
        "base_attack_total": f"{base_atk:.2f}%" if base_atk else None,
        "support_total": f"{support:.2f}%" if support else None,
    }


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

        option_lines = [line for line in option_text.split("\n") if line.strip()]
        # "[10P] 효과 설명"을 (달성 포인트, 설명)으로 분리 — 달성 여부 강조 표시에 쓴다
        options = []
        for line in option_lines:
            match = _CORE_OPTION_RE.match(line)
            if match:
                options.append({"point": int(match.group(1)), "text": match.group(2).strip()})
            else:
                options.append({"point": None, "text": line})

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
                "option_lines": option_lines,
                "options": options,
            }
        )

    effects = []
    for e in ark_grid.get("Effects") or []:
        text = strip_html(e.get("Tooltip"))
        # 이름("아군 피해 강화")과 본문("아군 피해량 강화 효과 +1.99%")의 표현이 미묘하게
        # 달라 이름 제거 방식으로는 중복이 남는다 — 수치 토큰만 따로 뽑아 value_text로 준다.
        values = _VALUE_TOKEN_RE.findall(text)
        effects.append(
            {
                "name": e.get("Name"),
                "level": e.get("Level"),
                "text": text,
                "value_text": values[-1] if values else None,
            }
        )

    return {"cores": cores, "effects": effects}


def _format_combat_power(raw) -> str | None:
    """전투력은 문자열 숫자로 내려오는데, 천단위 콤마 없이 그대로 보여주면 자릿수를
    가늠하기 어려워 콤마를 붙인다. 숫자가 아니면(예외적인 경우) 원본을 그대로 반환."""
    return _format_int(raw)


def parse_armory_detail(raw: dict) -> dict:
    """아머리 원본 응답(profiles+equipment+combat-skills+engravings+cards+arkpassive+gems+arkgrid
    필터) 전체를 정리."""
    profile = raw.get("ArmoryProfile") or {}
    stats = profile.get("Stats")
    equipment = parse_weapon_armor(raw.get("ArmoryEquipment"))
    accessories = parse_accessories(raw.get("ArmoryEquipment"))
    extra_equipment = parse_extra_equipment(raw.get("ArmoryEquipment"))
    engravings = parse_engravings(raw.get("ArmoryEngraving"))
    gems = parse_gems(raw.get("ArmoryGem"))

    # 보석이 적용된 스킬에 레벨/분류 배지를 달아주기 위한 스킬명 → 보석 매핑
    skills = parse_skills(raw.get("ArmorySkills"))
    gems_by_skill: dict[str, list[dict]] = {}
    for gem in gems:
        if gem.get("skill_name"):
            gems_by_skill.setdefault(gem["skill_name"], []).append(gem)
    for skill in skills:
        skill["gems"] = [
            {"level": g.get("level"), "kind": g.get("kind"), "name": g.get("name")}
            for g in gems_by_skill.get(skill["name"], [])
        ]

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
        "using_skill_point": profile.get("UsingSkillPoint"),
        "total_skill_point": profile.get("TotalSkillPoint"),
        "profile_stats": parse_profile_stats(stats),
        "skills": skills,
        "ark_passive": parse_ark_passive(raw.get("ArkPassive")),
        "equipment": equipment,
        "accessories": accessories,
        "extra_equipment": extra_equipment,
        "gems": gems,
        "gem_summary": summarize_gems(gems),
        "ark_grid": parse_ark_grid(raw.get("ArkGrid")),
        "stat_effects": parse_stat_effects(stats),
        "engravings": engravings,
        "cards": parse_cards(raw.get("ArmoryCard")),
        "aggregate_effects": parse_aggregate_effects(
            stats, engravings, equipment, accessories, extra_equipment
        ),
    }
