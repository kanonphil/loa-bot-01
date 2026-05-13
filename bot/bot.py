from __future__ import annotations

import discord
from discord.ext import commands, tasks
from datetime import datetime, timezone, timedelta

import bot.database.manager as db
import bot.api.lostark as loa
from bot.ui.views import PartyView
from bot.ui.embeds import party_embed
from bot.data import raids as raids_module

KST = timezone(timedelta(hours=9))

COGS = [
    "bot.cogs.account",
    "bot.cogs.dashboard",
    "bot.cogs.expedition",
    "bot.cogs.raid",
    "bot.cogs.party",
    "bot.cogs.admin",
]


class LoABot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def setup_hook(self) -> None:
        await db.init_db()
        await raids_module.reload()
        for cog in COGS:
            await self.load_extension(cog)
        await self.tree.sync()
        print("[LoABot] 슬래시 커맨드 동기화 완료")

    async def on_ready(self) -> None:
        print(f"[LoABot] {self.user} 로그인 완료")
        await self._restore_party_views()
        if not self.party_notification_task.is_running():
            self.party_notification_task.start()
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name="로스트아크 | /원정대",
            )
        )

    @tasks.loop(seconds=30)
    async def party_notification_task(self) -> None:
        """30초마다 일정 알림 발송 + 24시간 지난 파티 자동 정리"""
        now     = datetime.now(KST)
        now_iso = now.isoformat()

        # 일정 알림
        for party in await db.get_parties_due_notification(now_iso):
            channel = self.get_channel(int(party["channel_id"]))
            if channel is None:
                continue
            slots      = await db.get_party_slots(party["message_id"])
            mentions   = " ".join(f"<@{s['discord_id']}>" for s in slots)
            raid_title = f"{party['raid_name']} {party['difficulty']} {party['proficiency']}"
            leader_mention = f"<@{party['leader_id']}>"
            await channel.send(
                f"⏰ **{raid_title}** 공격대 시작 시간입니다!\n"
                f"{mentions or leader_mention}"
            )
            await db.mark_notified(party["message_id"])

        # 익스트림 레이드 운영 기간 만료 → 활성 파티 자동 종료
        for party in await db.get_expired_extreme_parties(now_iso):
            await db.disband_party(party["message_id"])
            thread = self.get_channel(int(party["channel_id"]))
            if thread is None:
                continue
            try:
                msg = await thread.fetch_message(int(party["message_id"]))
                party["status"] = "disbanded"
                slots = await db.get_party_slots(party["message_id"])
                await msg.edit(embed=party_embed(party, slots), view=None)
            except (discord.NotFound, discord.Forbidden):
                pass
            raid_title = f"{party['raid_name']} {party['difficulty']}"
            await thread.send(
                f"⏰ **{raid_title}** 익스트림 레이드 운영 기간이 종료되었습니다."
            )
            try:
                await thread.edit(archived=True, locked=True)
            except discord.HTTPException:
                pass

        week_start = db.get_week_start_iso()

        # 이전 주차 파티 자동 종료 (recruiting/full/closed → disbanded + archive)
        expired = await db.get_prev_week_active_parties(week_start)
        just_disbanded: set[str] = set()
        for party in expired:
            await db.disband_party(party["message_id"])
            just_disbanded.add(party["message_id"])
            thread = self.get_channel(int(party["channel_id"]))
            if thread is None:
                continue
            try:
                msg   = await thread.fetch_message(int(party["message_id"]))
                party["status"] = "disbanded"
                slots = await db.get_party_slots(party["message_id"])
                await msg.edit(embed=party_embed(party, slots), view=None)
            except (discord.NotFound, discord.Forbidden):
                pass
            raid_title = f"{party['raid_name']} {party['difficulty']}"
            await thread.send(f"🔒 **{raid_title}** 공대 모집이 자동 종료되었습니다.")
            try:
                await thread.edit(archived=True, locked=True)
            except discord.HTTPException:
                pass

        # 이전 주차 disbanded 파티 스레드 삭제 + DB 레코드 정리
        # (이번 사이클에 방금 disband된 파티는 제외 — 다음 주간 리셋에서 삭제)
        old_disbanded = await db.get_prev_week_disbanded_parties(week_start)
        for party in old_disbanded:
            if party["message_id"] in just_disbanded:
                continue
            raid_title = f"{party['raid_name']} {party['difficulty']}"
            print(f"[스레드 정리] {raid_title} / channel_id={party['channel_id']}")
            # 아카이브된 스레드는 캐시에 없으므로 fetch_channel fallback 사용
            thread = self.get_channel(int(party["channel_id"]))
            if thread is None:
                try:
                    thread = await self.fetch_channel(int(party["channel_id"]))
                    print(f"[스레드 정리] fetch_channel 성공: {thread}")
                except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                    print(f"[스레드 정리] fetch_channel 실패: {type(e).__name__}: {e}")
                    thread = None
            if thread is not None:
                try:
                    await thread.delete()
                    print(f"[스레드 정리] 삭제 성공: {raid_title}")
                    await db.purge_party(party["message_id"])
                except discord.NotFound:
                    # 이미 삭제된 스레드 → DB도 정리
                    await db.purge_party(party["message_id"])
                except (discord.Forbidden, discord.HTTPException) as e:
                    # 권한 없음 → DB 유지, 다음 리셋에서 재시도
                    print(f"[스레드 정리] 삭제 실패 (재시도 예정): {type(e).__name__}: {e}")
            else:
                # 스레드 자체를 찾을 수 없음 → DB만 정리
                await db.purge_party(party["message_id"])

    @party_notification_task.before_loop
    async def before_party_notification(self) -> None:
        await self.wait_until_ready()

    async def _restore_party_views(self) -> None:
        """봇 재시작 후 활성 파티 메시지에 View 재연결"""
        active = await db.get_all_active_party_ids()
        for msg_id, channel_id in active:
            channel = self.get_channel(int(channel_id))
            if channel is None:
                continue
            try:
                msg   = await channel.fetch_message(int(msg_id))
                party = await db.get_party(msg_id)
                slots = await db.get_party_slots(msg_id)
                if not party:
                    continue
                view  = PartyView(total_slots=party["total_slots"], closed=(party["status"] == "closed"))
                embed = party_embed(party, slots)
                await msg.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    async def close(self) -> None:
        await loa.close_session()
        await super().close()
