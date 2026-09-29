from typing import Any

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards
from app.bot.texts import t
from app.db.models import User
from app.services import delivery

router = Router(name="referral")


async def show_referral(
    message: Message, bot: Bot, session: AsyncSession, user: User, cfg: dict[str, Any]
) -> None:
    uname = await delivery.bot_username(bot)
    link = f"https://t.me/{uname}?start=ref_{user.id}"
    count = (
        await session.scalar(select(func.count()).select_from(User).where(User.referrer_id == user.id)) or 0
    )
    await message.answer(
        t("ref", user.lang, hours=cfg["referral_bonus_hours"], link=link, count=count),
        reply_markup=keyboards.share(link, user.lang),
    )


@router.message(Command("ref", "invite"))
async def cmd_ref(message: Message, bot: Bot, session: AsyncSession, user: User, cfg: dict[str, Any]) -> None:
    await show_referral(message, bot, session, user, cfg)
