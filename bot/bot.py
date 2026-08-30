from __future__ import annotations

import discord
from discord.ext import commands, tasks
from datetime import datetime, time, timezone, timedelta

import bot.database.manager as db
import bot.api.lostark as loa
from bot.services.expedition import sync_all_accounts_daily
from bot.ui.views import PartyView, _refresh_party_embed_with_reserved, _send_dm
from bot.ui.embeds import party_embed
from bot.data import raids as raids_module

import asyncio
import uvicorn

KST = timezone(timedelta(hours=9))

COGS = [
    "bot.cogs.account",
    "bot.cogs.dashboard",
    "bot.cogs.expedition",
    "bot.cogs.raid",
    "bot.cogs.party",
    "bot.cogs.admin",
    "bot.cogs.subscription",
    "bot.cogs.invite",
    "bot.cogs.guide",
]


class LoABot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        # 파티 스레드 댓글을 웹에도 보여주려면 메시지 "내용"을 읽어야 한다 — 특권
        # 인텐트라 Discord 개발자 포털에서 이 봇 앱에 대해 별도로 켜야 코드와 무관하게
        # 실제로 켜진다(코드만 True로 바꿔도 포털에서 안 켜져 있으면 계속 빈 문자열이 옴).
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self._thread_purge_failures: dict[str, int] = {}  # channel_id → 실패 횟수
        self._api_server_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        await db.init_db()
        await raids_module.reload()
        # PartyView 버튼(party:join/leave/waitlist/manage/switch)을 custom_id 기준으로
        # 전역 등록 — timeout=None이라 가능하다. _restore_party_views가 재시작 시 활성
        # 파티 메시지를 일일이 edit해서 View를 재연결하는데, 그 edit이 실패(레이트리밋,
        # 일시적 네트워크 오류 등)한 메시지의 버튼은 살아있는 View에 안 묶여서 죽는다.
        # 이 등록은 total_slots/closed 값과 무관하게(실제 검증은 핸들러가 매번 DB에서
        # 다시 조회) 모든 파티 메시지의 버튼 클릭을 항상 받아낼 수 있게 하는 이중
        # 안전장치 — _restore_party_views의 embed 최신화 자체는 계속 그대로 수행한다.
        self.add_view(PartyView(total_slots=8))
        for cog in COGS:
            await self.load_extension(cog)
        await self.tree.sync()
        print("[LoABot] 슬래시 커맨드 동기화 완료")
        # FastAPI 서버 시작 ────────────────────────────────────
        from bot.api.server import app
        from bot.api import bot_ref
        bot_ref.set_bot(self)
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=8000,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        # 태스크 참조를 인스턴스에 보관 — asyncio는 태스크를 약한 참조로만 들고 있어서,
        # 참조를 안 잡아두면 실행 중에도 가비지 컬렉션될 수 있다(공식 문서에 명시된
        # 함정). done_callback으로 예외 발생 시 로그를 남겨, API 서버가 조용히
        # 죽어버려도(포트 충돌 등) 알아챌 수 있게 한다.
        self._api_server_task = asyncio.get_event_loop().create_task(server.serve())
        self._api_server_task.add_done_callback(self._on_api_server_done)
        print("[LoABot] FastAPI 서버 시작 완료 (port 8000)")

    def _on_api_server_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            print(f"[LoABot] FastAPI 서버가 예외로 종료됨: {type(exc).__name__}: {exc}")

    async def on_message(self, message: discord.Message) -> None:
        # 봇 자신(웹 댓글을 웹훅으로 릴레이한 메시지 포함)이 보낸 메시지가 다시
        # 저장되면 무한 중복이 생긴다 — webhook_id가 있으면(웹훅으로 온 메시지)
        # 무조건 무시하고, author.bot도 별도로 걸러 다른 봇의 메시지도 막는다.
        if message.author.bot or message.webhook_id is not None:
            await self.process_commands(message)
            return

        party = await db.get_party_by_channel(str(message.channel.id))
        if party and party["status"] != "disbanded":
            await db.add_party_comment(
                party["message_id"], str(message.author.id), message.author.display_name,
                message.content, source="discord", discord_message_id=str(message.id),
            )
        await self.process_commands(message)

    async def on_ready(self) -> None:
        print(f"[LoABot] {self.user} 로그인 완료")
        await self._restore_party_views()
        if not self.party_notification_task.is_running():
            self.party_notification_task.start()
        if not self.account_sync_task.is_running():
            self.account_sync_task.start()
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.playing,
                name="로스트아크 | /원정대",
            )
        )

    # hours=24 대신 KST 새벽 4시 고정 시각 실행 — hours=24는 루프의 첫 실행이 .start()를
    # 호출한 "그 즉시"라서, 봇이 재시작될 때마다(하루에도 여러 번일 수 있음) 등록된 모든
    # 유저의 모든 캐릭터를 다시 전부 동기화하는 낭비가 있었다. time= 방식은 하루 중
    # 지정된 시각에 한 번만 실행되므로 재시작 횟수와 무관하다.
    @tasks.loop(time=time(hour=4, minute=0, tzinfo=KST))
    async def account_sync_task(self) -> None:
        """등록된 모든 유저의 모든 계정(부계정 포함) 캐릭터 정보를 매일 새벽 4시(KST)에
        자동 동기화. 수동 "동기화" 버튼/웹 sync API와 동일한 핵심 로직을 공유한다
        (bot.services.expedition.sync_all_accounts_daily)."""
        print("[LoABot] 일일 계정 동기화 시작")
        await sync_all_accounts_daily()
        print("[LoABot] 일일 계정 동기화 완료")

    @account_sync_task.before_loop
    async def before_account_sync(self) -> None:
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def party_notification_task(self) -> None:
        """30초마다 일정 알림 발송 + 24시간 지난 파티 자동 정리"""
        now     = datetime.now(KST)
        now_iso = now.isoformat()

        # 시작 시각 알림 (채널 멘션)
        # 파티 하나에서 채널을 못 찾거나 전송이 실패해도(아카이브된 스레드, 권한 문제 등)
        # 이 루프 자체가 죽어서 이후 처리(주간 정리 등)까지 멈추지 않도록
        # 각 파티를 개별적으로 감싼다. get_channel만 쓰면 캐시에 없는(아카이브된) 스레드는
        # 알림이 영영 안 나가고 notified도 안 찍혀 매 30초 재시도만 반복하므로
        # fetch_channel fallback도 함께 추가.
        for party in await db.get_parties_due_notification(now_iso):
            try:
                channel = self.get_channel(int(party["channel_id"]))
                if channel is None:
                    channel = await self.fetch_channel(int(party["channel_id"]))
                slots      = await db.get_party_slots(party["message_id"])
                mentions   = " ".join(f"<@{s['discord_id']}>" for s in slots)
                raid_title = f"{party['raid_name']} {party['difficulty']} {party['proficiency']}"
                leader_mention = f"<@{party['leader_id']}>"
                await channel.send(
                    f"⏰ **{raid_title}** 공격대 시작 시간입니다!\n"
                    f"{mentions or leader_mention}"
                )
                await db.mark_notified(party["message_id"])
            except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
                print(f"[시작 알림] 발송 실패 (message_id={party.get('message_id')}): {type(e).__name__}: {e}")
                await db.mark_notified(party["message_id"])

        # 초대(예약 슬롯) 만료 정리 — InviteResponseView의 1시간 timeout은 메모리(뷰
        # 인스턴스)에만 있어서 봇이 재시작되면 사라진다. 그러면 party_invites 행이
        # 영구히 남아 슬롯 하나가 계속 "예약중"으로 막히는 문제가 있었다. DB의
        # invited_at 기준으로 1시간 지난 초대를 여기서 주기적으로 정리한다.
        for invite in await db.get_expired_invites(hours=1):
            try:
                await db.delete_invite(invite["message_id"], invite["discord_id"])
                party = await db.get_party(invite["message_id"])
                if party and party["status"] != "disbanded":
                    await _refresh_party_embed_with_reserved(self, party)
            except Exception as e:
                print(f"[초대 만료] 정리 실패 (message_id={invite.get('message_id')}): {type(e).__name__}: {e}")

        # 익스트림 레이드 운영 기간 만료 → 알림만 발송, 파티는 유지
        # embed/버튼/스레드 잠금 없음 — 공대장이 직접 클리어/해체 처리하도록
        for party in await db.get_expired_extreme_parties(now_iso):
            await db.mark_extreme_period_notified(party["message_id"])
            thread = self.get_channel(int(party["channel_id"]))
            if thread is None:
                try:
                    thread = await self.fetch_channel(int(party["channel_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    thread = None
            if thread is None:
                continue
            raid_title = f"{party['raid_name']} {party['difficulty']}"
            try:
                await thread.send(
                    f"⏰ **{raid_title}** 익스트림 레이드 운영 기간이 종료되었습니다.\n"
                    f"클리어 또는 파티 해체를 처리해 주세요."
                )
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
                try:
                    thread = await self.fetch_channel(int(party["channel_id"]))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    thread = None
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
            try:
                await thread.send(f"🔒 **{raid_title}** 공대 모집이 자동 종료되었습니다.")
            except discord.HTTPException:
                pass
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
                    self._thread_purge_failures.pop(party["channel_id"], None)
                    await db.purge_party(party["message_id"])
                except discord.NotFound:
                    # 이미 삭제된 스레드 → DB도 정리
                    await db.purge_party(party["message_id"])
                except (discord.Forbidden, discord.HTTPException) as e:
                    ch_key   = party["channel_id"]
                    failures = self._thread_purge_failures.get(ch_key, 0) + 1
                    self._thread_purge_failures[ch_key] = failures
                    if failures >= 3:
                        print(f"[스레드 정리] 3회 연속 실패, DB만 정리: {raid_title}")
                        await db.purge_party(party["message_id"])
                        self._thread_purge_failures.pop(ch_key, None)
                    else:
                        print(f"[스레드 정리] 삭제 실패 ({failures}/3회, 재시도 예정): {type(e).__name__}: {e}")
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
                try:
                    channel = await self.fetch_channel(int(channel_id))
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    continue
            try:
                msg   = await channel.fetch_message(int(msg_id))
                party = await db.get_party(msg_id)
                slots = await db.get_party_slots(msg_id)
                if not party:
                    continue
                reserved = await db.get_reserved_slots(msg_id)
                view  = PartyView(total_slots=party["total_slots"], closed=(party["status"] == "closed"))
                embed = party_embed(party, slots, reserved)
                await msg.edit(embed=embed, view=view)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                pass

    async def close(self) -> None:
        await loa.close_session()
        await super().close()
