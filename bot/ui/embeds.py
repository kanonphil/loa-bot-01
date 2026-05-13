from __future__ import annotations

import re
import discord
from datetime import datetime, timezone, timedelta

from bot.data.raids import RAIDS, get_applicable_raids, CIRCLE_NUMBERS
from bot.database.manager import get_week_key

_KST = timezone(timedelta(hours=9))

KST = timezone(timedelta(hours=9))

CLASS_COLORS: dict[str, int] = {
    "워로드": 0x4A90D9, "버서커": 0xE74C3C, "디스트로이어": 0xDFE6E9, "홀리나이트": 0xF1C40F, 
    "슬레이어": 0xD63031, "발키리": 0xE6E6FA,

    "배틀마스터": 0xE67E22, "인파이터": 0x8E44AD, "기공사": 0x1ABC9C, "창술사": 0x27AE60, 
    "스트라이커": 0xD35400, "브레이커": 0x6D214F,

    "데빌헌터": 0x7F8C8D, "호크아이": 0x00B894, "스카우터": 0x0984E3, "블래스터": 0xB2BEC3, 
    "건슬링어": 0x95A5A6,  

    "블레이드": 0xC0392B, "데모닉": 0x6C3483, "소울이터": 0x2D3436, "리퍼": 0x636E72,

    "아르카나": 0xF39C12, "소서리스": 0x2980B9, "서머너": 0x16A085, "바드": 0xA29BFE, 

    "도화가": 0xFD79A8, "기상술사": 0x74B9FF, "환수사": 0x2ECC71,

    "가디언나이트": 0x34495E,
    
}
DEFAULT_COLOR = 0x7289DA
FOOTER = "⚔️ 로스트아크 봇"


def _color(class_name: str | None) -> int:
    if not class_name:
        return DEFAULT_COLOR
    return CLASS_COLORS.get(class_name, DEFAULT_COLOR)


def _ts() -> datetime:
    return datetime.now(KST)


def _item_level(char: dict) -> str:
    """ItemMaxLevel → ItemAvgLevel 순으로 fallback"""
    level = char.get("ItemMaxLevel") or char.get("ItemAvgLevel")
    return str(level) if level else "?"


# ─────────────────────────────────────────────────────
# 캐릭터 대시보드
# ─────────────────────────────────────────────────────

def _combat_power(profile: dict) -> str:
    """Stats 배열에서 전투력 추출"""
    for stat in profile.get("Stats") or []:
        if stat.get("Type") == "전투력":
            return stat.get("Value", "?")
    return None


def _gem_skill_from_tooltip(tooltip_str: str) -> str:
    """Tooltip JSON에서 #FFD200 색상(스킬명) 추출."""
    try:
        import json as _json
        tooltip = _json.loads(tooltip_str)
        for elem in tooltip.values():
            if not isinstance(elem, dict):
                continue
            if elem.get("type") == "ItemPartBox":
                text = (elem.get("value") or {}).get("Element_001", "")
                m = re.search(r"<FONT COLOR='#FFD200'>([^<]+)</FONT>", text)
                if m:
                    return m.group(1).strip()
    except Exception:
        pass
    return ""


def _format_gems(armory_gem: dict) -> str | None:
    """보석 목록을 '레벨 타입 (스킬명)' 형식으로 포맷"""
    gems = armory_gem.get("Gems") or []
    if not gems:
        return None

    # 레벨 내림차순, 같은 레벨이면 슬롯 번호 오름차순
    sorted_gems = sorted(gems, key=lambda g: (-g.get("Level", 0), g.get("Slot", 99)))

    lines = []
    for gem in sorted_gems:
        gem_name = re.sub(r"<[^>]+>", "", gem.get("Name", "?")).strip()
        skill    = _gem_skill_from_tooltip(gem.get("Tooltip", ""))
        lines.append(f"{gem_name} ({skill})" if skill else gem_name)

    return "\n".join(lines)


def character_embed(armory: dict) -> discord.Embed:
    profile    = armory.get("ArmoryProfile") or {}
    name       = profile.get("CharacterName", "알 수 없음")
    class_name = profile.get("CharacterClassName", "?")

    embed = discord.Embed(title=f"⚔️ {name}", color=_color(class_name))

    # ── 기본 정보 (3열) ──────────────────────────────
    embed.add_field(name="서버",       value=profile.get("ServerName", "?"),              inline=True)
    embed.add_field(name="직업",       value=class_name,                                  inline=True)
    embed.add_field(name="아이템레벨", value=f"**{_item_level(profile)}**",               inline=True)
    embed.add_field(name="캐릭터레벨", value=str(profile.get("CharacterLevel", "?")),     inline=True)
    embed.add_field(name="원정대레벨", value=str(profile.get("ExpeditionLevel", "?")),    inline=True)
    embed.add_field(name="길드",       value=profile.get("GuildName") or "없음",          inline=True)

    # ── 전투력 ───────────────────────────────────────
    cp = _combat_power(profile)
    if cp:
        embed.add_field(name="⚡ 전투력", value=f"**{cp}**", inline=False)

    # ── 칭호 ─────────────────────────────────────────
    if profile.get("Title"):
        embed.add_field(name="칭호", value=profile["Title"], inline=False)

    # ── 전투 각인 ─────────────────────────────────────
    effects = (armory.get("ArmoryEngraving") or {}).get("Effects") or []
    if effects:
        lines = [f"`{e['Name']} Lv.{e['Level']}`" for e in effects[:6]]
        embed.add_field(name="🔮 전투 각인", value="  ".join(lines), inline=False)

    # ── 보석 ─────────────────────────────────────────
    gem_text = _format_gems(armory.get("ArmoryGem") or {})
    if gem_text:
        embed.add_field(name="💎 보석", value=gem_text, inline=False)

    if profile.get("CharacterImage"):
        embed.set_thumbnail(url=profile["CharacterImage"])

    embed.set_footer(text=FOOTER)
    embed.timestamp = _ts()
    return embed


# ─────────────────────────────────────────────────────
# 원정대
# ─────────────────────────────────────────────────────

def expedition_embed(user: discord.User | discord.Member, characters: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=f"🗺️ {user.display_name}의 원정대",
        description=f"등록된 캐릭터 **{len(characters)}**개",
        color=0x2ECC71,
    )

    def _lv(c: dict) -> float:
        try:
            return float(_item_level(c).replace(",", ""))
        except ValueError:
            return 0.0

    for c in sorted(characters, key=_lv, reverse=True):
        embed.add_field(
            name=c.get("CharacterName", "?"),
            value=f"{c.get('CharacterClassName','?')}  |  {_item_level(c)}",
            inline=False,
        )

    embed.set_footer(text=FOOTER)
    embed.timestamp = _ts()
    return embed


def no_characters_embed(user: discord.User | discord.Member) -> discord.Embed:
    return discord.Embed(
        title="🗺️ 원정대",
        description=(
            f"**{user.display_name}**님의 등록된 캐릭터가 없습니다.\n\n"
            "아래 **캐릭터 추가** 버튼으로 원정대를 구성해보세요."
        ),
        color=0x95A5A6,
    )


# ─────────────────────────────────────────────────────
# 레이드 체크리스트
# ─────────────────────────────────────────────────────

def raid_checklist_embed(
    character_name: str, item_level: float, completions: set[str]
) -> discord.Embed:
    applicable  = get_applicable_raids(item_level)
    raid_names  = dict.fromkeys(r for r, _, _ in applicable)  # 순서 유지 unique
    total       = len(raid_names)
    done_count  = sum(1 for r in raid_names if any(k.startswith(f"{r}_") for k in completions))
    week_key   = get_week_key()

    if total:
        bar_fill = round(done_count / total * 10)
        bar = "█" * bar_fill + "░" * (10 - bar_fill)
        desc = (
            f"아이템 레벨 **{item_level:.0f}** · 주간 `{week_key}`\n"
            f"`{bar}` **{done_count} / {total}** 완료"
        )
    else:
        desc = f"아이템 레벨 **{item_level:.0f}** — 입장 가능한 레이드가 없습니다"

    embed = discord.Embed(title=f"📋 {character_name}의 레이드 체크리스트", description=desc, color=0x9B59B6)

    # 카테고리별 그룹화
    by_cat: dict[str, list] = {}
    for raid_name, diff_name, diff_info in applicable:
        cat = RAIDS[raid_name]["category"]
        by_cat.setdefault(cat, []).append((raid_name, diff_name, diff_info))

    for cat, raids in by_cat.items():
        lines = []
        for raid_name, diff_name, diff_info in raids:
            icon      = RAIDS[raid_name]["icon"]
            done      = f"{raid_name}_{diff_name}" in completions
            name_text = f"**{raid_name} {diff_name}**" if done else f"{raid_name} {diff_name}"
            status    = "✅" if done else "⬜"
            lines.append(f"{status} {icon} {name_text}  _최소 {diff_info['min_level']}_")
        embed.add_field(name=f"◈ {cat}", value="\n".join(lines), inline=False)

    embed.set_footer(text=f"{FOOTER} • 매주 수요일 06:00 KST 초기화")
    embed.timestamp = _ts()
    return embed


# ─────────────────────────────────────────────────────
# 공대 모집
# ─────────────────────────────────────────────────────

def _slot_text(slot: dict | None) -> str:
    if slot:
        role = slot.get("role", "dps")
        icon = "🛡️" if role == "support" else "⚔️"
        return f"{icon} **{slot['character_name']}** · _{slot['character_class']}_"
    return "➖ _빈 자리_"


def party_embed(party: dict, slots: list[dict]) -> discord.Embed:
    raid_name    = party["raid_name"]
    difficulty   = party["difficulty"]
    proficiency  = party["proficiency"]
    sched_time   = party["scheduled_time"]
    total_slots  = party["total_slots"]
    min_level    = party["min_level"]
    status       = party["status"]

    raid_info  = RAIDS.get(raid_name, {})
    short_name = raid_info.get("short_name", raid_name)
    icon       = raid_info.get("icon", "⚔️")

    leader_class = None
    for s in slots:
        if s["discord_id"] == party["leader_id"]:
            leader_class = s["character_class"]
            break

    if status == "recruiting":
        color      = _color(leader_class)
        status_text = "🟢 모집 중"
    elif status == "full":
        color      = 0x3498DB
        status_text = "🔵 파티 완성"
    elif status == "closed":
        color      = 0xE67E22
        status_text = "🔴 모집 마감"
    else:
        color      = 0x95A5A6
        status_text = "⚫ 모집 종료"

    slot_map = {s["slot_number"]: s for s in slots}
    filled   = len(slots)

    # Discord 타임스탬프 (사용자 로컬 시간 자동 변환)
    ts_display = sched_time
    if party.get("scheduled_datetime"):
        try:
            dt = datetime.fromisoformat(party["scheduled_datetime"])
            ts_display = f"<t:{int(dt.timestamp())}:F>"
        except Exception:
            pass

    is_extreme = raid_info.get("is_extreme", False)
    title_prefix = "⚡ " if is_extreme else ""
    embed = discord.Embed(
        title=f"{title_prefix}{icon} {short_name} {difficulty} {proficiency} 공격대 모집",
        color=color,
    )

    period_line = ""
    if is_extreme:
        avail_from  = raid_info.get("available_from")
        avail_until = raid_info.get("available_until")
        if avail_from and avail_until:
            try:
                f_dt = datetime.fromisoformat(avail_from)
                u_dt = datetime.fromisoformat(avail_until)
                period_line = (
                    f"\n⏰ 운영 기간: <t:{int(f_dt.timestamp())}:D>"
                    f" ~ <t:{int(u_dt.timestamp())}:D>"
                )
            except ValueError:
                pass

    embed.description = (
        f"📅 {ts_display}\n"
        f"👑 <@{party['leader_id']}>\n"
        f"{status_text} ({filled}/{total_slots}) | 최소 {min_level}"
        + period_line
        + (f"\n📌 {party['memo']}" if party.get("memo") else "")
    )

    party_split: int | None = (raid_info.get("difficulties") or {}).get(difficulty, {}).get("party_split")

    if party_split and total_slots > party_split:
        num_parties = total_slots // party_split
        remainder   = total_slots % party_split
        all_lines: list[str] = []

        for p in range(num_parties):
            start = p * party_split + 1
            p_filled = sum(1 for sn in range(start, start + party_split) if sn in slot_map)
            if all_lines:
                all_lines.append("")
            all_lines.append(f"**[{p + 1}파티]**  `{p_filled}/{party_split}`")
            for sn in range(start, start + party_split):
                all_lines.append(f"{CIRCLE_NUMBERS[sn - 1]} {_slot_text(slot_map.get(sn))}")

        if remainder:
            start = num_parties * party_split + 1
            p_filled = sum(1 for sn in range(start, total_slots + 1) if sn in slot_map)
            all_lines.append("")
            all_lines.append(f"**[{num_parties + 1}파티]**  `{p_filled}/{remainder}`")
            for sn in range(start, total_slots + 1):
                all_lines.append(f"{CIRCLE_NUMBERS[sn - 1]} {_slot_text(slot_map.get(sn))}")

        embed.add_field(name="​", value="\n".join(all_lines), inline=False)
    else:
        lines = []
        for sn in range(1, total_slots + 1):
            lines.append(f"{CIRCLE_NUMBERS[sn - 1]} {_slot_text(slot_map.get(sn))}")
        embed.add_field(name="​", value="\n".join(lines), inline=False)

    if status in ("recruiting", "full"):
        footer_hint = "참여하기 버튼을 눌러 참여하세요"
    elif status == "closed":
        footer_hint = "모집이 마감되었습니다 • 클리어 버튼으로 클리어 처리하세요"
    else:
        footer_hint = "모집이 종료되었습니다"
    embed.set_footer(text=f"{FOOTER} • {footer_hint}")
    embed.timestamp = _ts()
    return embed


# ─────────────────────────────────────────────────────
# 공대 목록 (/공대확인)
# ─────────────────────────────────────────────────────

def party_list_embed(pairs: list[tuple[dict, list[dict]]]) -> discord.Embed:
    embed = discord.Embed(
        title="📋 현재 모집 중인 공대",
        description=f"총 **{len(pairs)}**개 파티 모집 중",
        color=0x2ECC71,
    )

    for party, slots in pairs:
        raid_info = RAIDS.get(party["raid_name"], {})
        icon      = raid_info.get("icon", "⚔️")
        short     = raid_info.get("short_name", party["raid_name"])
        total     = party["total_slots"]
        slot_map  = {s["slot_number"]: s for s in slots}
        filled    = len(slots)

        if party["status"] == "recruiting":
            status_icon = "🟢"
        elif party["status"] == "full":
            status_icon = "🔵"
        else:
            status_icon = "🔴"

        member_lines = []
        for sn in range(1, total + 1):
            s = slot_map.get(sn)
            circle = CIRCLE_NUMBERS[sn - 1]
            if s:
                r_icon = "🛡️" if s.get("role") == "support" else "⚔️"
                member_lines.append(f"{circle} {r_icon} **{s['character_name']}** · _{s['character_class']}_")
            else:
                member_lines.append(f"{circle} ➖ _빈 자리_")

        guild_id = party["guild_id"]
        ch_id    = party["channel_id"]
        msg_id   = party["message_id"]
        link     = f"https://discord.com/channels/{guild_id}/{ch_id}/{msg_id}"

        ts_display = party["scheduled_time"]
        if party.get("scheduled_datetime"):
            try:
                dt = datetime.fromisoformat(party["scheduled_datetime"])
                ts_display = f"<t:{int(dt.timestamp())}:F>"
            except Exception:
                pass

        field_name  = f"{status_icon} {icon} {short} {party['difficulty']} {party['proficiency']}  `{filled}/{total}`"
        field_value = (
            f"📅 {ts_display}\n"
            f"👑 <@{party['leader_id']}>\n"
            + "\n".join(member_lines)
            + f"\n[→ 공대 게시물 바로가기]({link})"
        )
        embed.add_field(name=field_name, value=field_value, inline=False)

    embed.set_footer(text=FOOTER)
    embed.timestamp = _ts()
    return embed
