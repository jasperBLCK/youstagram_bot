"""Апдейты из каналов спонсоров: заявки на вступление, вступления по нашей ссылке, отписки."""

from datetime import UTC, datetime

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatJoinRequest, ChatMemberUpdated
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Sponsor, SubStatus, User
from app.services import gate, stats

router = Router(name="channels")

INVITE_PREFIX = "OP#"
LEFT = {ChatMemberStatus.LEFT, ChatMemberStatus.KICKED}


@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest, session: AsyncSession) -> None:
    sponsors = (
        (
            await session.execute(
                select(Sponsor).where(Sponsor.chat_id == req.chat.id, Sponsor.join_request.is_(True))
            )
        )
        .scalars()
        .all()
    )
    if not sponsors or not await session.get(User, req.from_user.id):
        return
    now = datetime.now(UTC)
    for s in sponsors:
        if await gate.record_subscription(
            session, s, req.from_user.id, SubStatus.REQUESTED, via_bot=True, now=now
        ):
            await stats.incr(session, "sponsor_joins")
    await session.commit()


@router.chat_member(F.chat.type.in_({ChatType.CHANNEL, ChatType.SUPERGROUP, ChatType.GROUP}))
async def on_chat_member(event: ChatMemberUpdated, session: AsyncSession) -> None:
    now = datetime.now(UTC)
    user_id = event.new_chat_member.user.id
    new_status = event.new_chat_member.status
    old_status = event.old_chat_member.status
    if new_status in LEFT and old_status not in LEFT:
        await gate.record_leave(session, event.chat.id, user_id, now)
        await session.commit()
        return
    link = event.invite_link
    if new_status == ChatMemberStatus.MEMBER and link and (link.name or "").startswith(INVITE_PREFIX):
        sponsor = await session.scalar(select(Sponsor).where(Sponsor.chat_id == event.chat.id))
        member = await session.get(User, user_id)
        if sponsor and member:
            if await gate.record_subscription(
                session, sponsor, user_id, SubStatus.JOINED, via_bot=True, now=now
            ):
                await stats.incr(session, "sponsor_joins")
            await session.commit()


@router.my_chat_member(F.chat.type == ChatType.PRIVATE)
async def on_block(event: ChatMemberUpdated, session: AsyncSession) -> None:
    user = await session.get(User, event.chat.id)
    if user is None:
        return
    blocked = event.new_chat_member.status in LEFT
    if blocked and not user.is_blocked:
        await stats.incr(session, "blocked")
    user.is_blocked = blocked
    await session.commit()
