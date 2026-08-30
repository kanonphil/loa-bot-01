"""웹에서 쓴 댓글을 파티 스레드에 그 작성자 이름/아바타로 릴레이한다.

디스코드 API는 실제 유저 계정으로 대신 메시지를 보내는 것을 지원하지 않는다
(계정 도용 문제) — 대신 웹훅(Webhook)의 username/avatar_url을 매 전송마다
바꿔서, 봇이 아니라 그 사람이 쓴 것처럼 보이게 한다(디스코드가 작게 웹훅
표시는 붙인다). 웹훅은 스레드가 아니라 부모(포럼) 채널에 딸리므로, 채널당
하나만 만들어두고 매번 thread= 파라미터로 목적지 스레드를 지정해 재사용한다.
"""
import discord

_WEBHOOK_NAME = "로아봇 댓글 브릿지"
_webhook_cache: dict[int, discord.Webhook] = {}


async def _get_or_create_bridge_webhook(parent_channel: discord.abc.GuildChannel) -> discord.Webhook:
    cached = _webhook_cache.get(parent_channel.id)
    if cached is not None:
        return cached

    for wh in await parent_channel.webhooks():
        if wh.name == _WEBHOOK_NAME:
            _webhook_cache[parent_channel.id] = wh
            return wh

    wh = await parent_channel.create_webhook(name=_WEBHOOK_NAME)
    _webhook_cache[parent_channel.id] = wh
    return wh


async def relay_comment_to_discord(
    bot: discord.Client, party: dict, display_name: str, avatar_url: str, content: str,
) -> tuple[bool, str | None]:
    """성공 시 (True, None), 실패(스레드 잠김/권한 없음 등) 시 (False, 사유)."""
    try:
        thread = bot.get_channel(int(party["channel_id"]))
        if thread is None:
            thread = await bot.fetch_channel(int(party["channel_id"]))
        parent = thread.parent
        if parent is None:
            return False, "스레드의 부모 채널을 찾을 수 없습니다."

        webhook = await _get_or_create_bridge_webhook(parent)
        await webhook.send(
            content=content, username=display_name, avatar_url=avatar_url,
            thread=discord.Object(id=int(party["channel_id"])),
        )
        return True, None
    except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
        return False, f"디스코드에 전달하지 못했습니다: {e}"
