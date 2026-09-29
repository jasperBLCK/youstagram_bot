import html
from datetime import UTC, datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards
from app.bot.handlers import premium, referral
from app.bot.texts import t
from app.db.models import User
from app.services import delivery, stats, users

router = Router(name="common")
router.message.filter(F.chat.type == ChatType.PRIVATE)


@router.message(CommandStart())
async def cmd_start(
    message: Message, command: CommandObject, bot: Bot, session: AsyncSession, user: User, is_new_user: bool
) -> None:
    if is_new_user:
        await users.attach_payload(session, user, users.parse_start_payload(command.args))
        await session.commit()
    name = html.escape(message.from_user.first_name if message.from_user else "")
    uname = await delivery.bot_username(bot)
    await message.answer(t("start", user.lang, name=name), reply_markup=keyboards.main_menu(user.lang, uname))


@router.message(Command("help"))
async def cmd_help(message: Message, user: User) -> None:
    await message.answer(t("help", user.lang))


@router.message(Command("lang"))
async def cmd_lang(message: Message, session: AsyncSession, user: User) -> None:
    await _toggle_lang(session, user)
    await message.answer(t("lang_changed", user.lang))


async def _toggle_lang(session: AsyncSession, user: User) -> None:
    user.lang = "en" if user.lang == "ru" else "ru"
    await session.commit()


@router.callback_query(F.data == "menu:lang")
async def cb_lang(call: CallbackQuery, bot: Bot, session: AsyncSession, user: User) -> None:
    await _toggle_lang(session, user)
    await call.answer(t("lang_changed", user.lang))
    if isinstance(call.message, Message):
        uname = await delivery.bot_username(bot)
        name = html.escape(call.from_user.first_name or "")
        await call.message.edit_text(
            t("start", user.lang, name=name), reply_markup=keyboards.main_menu(user.lang, uname)
        )


@router.callback_query(F.data == "menu:premium")
async def cb_premium(call: CallbackQuery, user: User, cfg: dict[str, object]) -> None:
    await call.answer()
    if isinstance(call.message, Message):
        await premium.show_premium(call.message, user, cfg)


@router.callback_query(F.data == "menu:ref")
async def cb_ref(
    call: CallbackQuery, bot: Bot, session: AsyncSession, user: User, cfg: dict[str, object]
) -> None:
    await call.answer()
    if isinstance(call.message, Message):
        await referral.show_referral(call.message, bot, session, user, cfg)


@router.message(Command("stats"))
async def cmd_stats(message: Message, session: AsyncSession, is_admin: bool) -> None:
    if not is_admin:
        return
    now = datetime.now(UTC)
    total = await session.scalar(select(func.count()).select_from(User)) or 0
    alive = (
        await session.scalar(select(func.count()).select_from(User).where(User.is_blocked.is_(False))) or 0
    )
    mau = (
        await session.scalar(
            select(func.count()).select_from(User).where(User.last_seen_at >= now - timedelta(days=30))
        )
        or 0
    )
    today = stats.today()
    new = await stats.total(session, "new_users", today)
    dau = await stats.total(session, "dau", today)
    dl = await stats.total(session, "downloads", today)
    shown = await stats.total(session, "gate_shown", today)
    passed = await stats.total(session, "gate_passed", today)
    conv = f"{passed / shown * 100:.0f}%" if shown else "—"
    await message.answer(
        "📊 <b>Статистика</b>\n\n"
        f"Всего: <b>{total}</b> (живых {alive})\nMAU: <b>{mau}</b>\n\n"
        f"<b>Сегодня</b>\nНовых: {new}\nDAU: {dau}\nСкачиваний: {dl}\nОП: {passed}/{shown} ({conv})"
    )
