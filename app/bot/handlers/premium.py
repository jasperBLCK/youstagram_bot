from datetime import UTC, datetime
from typing import Any

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot import keyboards
from app.bot.texts import t
from app.db.models import Payment, User
from app.services import stats
from app.services.gate import is_premium
from app.services.premium import extend_premium, find_plan

router = Router(name="premium")


def _fmt_date(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%d.%m.%Y %H:%M UTC")


async def show_premium(message: Message, user: User, cfg: dict[str, Any]) -> None:
    if not cfg["premium_enabled"]:
        await message.answer(t("premium_disabled", user.lang))
        return
    now = datetime.now(UTC)
    status = (
        t("premium_active", user.lang, until=_fmt_date(user.premium_until))
        if is_premium(user, now) and user.premium_until
        else ""
    )
    await message.answer(
        t("premium", user.lang, status=status),
        reply_markup=keyboards.premium_plans(cfg["premium_plans"], user.lang),
    )


@router.message(Command("premium"))
async def cmd_premium(message: Message, user: User, cfg: dict[str, Any]) -> None:
    await show_premium(message, user, cfg)


@router.callback_query(F.data.startswith("buy:"))
async def cb_buy(call: CallbackQuery, bot: Bot, user: User, cfg: dict[str, Any]) -> None:
    days = int((call.data or "buy:0").split(":")[1])
    plan = find_plan(cfg["premium_plans"], days)
    if not plan or not cfg["premium_enabled"]:
        await call.answer(t("premium_disabled", user.lang), show_alert=True)
        return
    await call.answer()
    await bot.send_invoice(
        chat_id=user.id,
        title=t("premium_invoice_title", user.lang, days=days),
        description=t("premium_invoice_desc", user.lang),
        payload=f"premium:{days}:{plan['stars']}",
        currency="XTR",
        prices=[LabeledPrice(label="Premium", amount=int(plan["stars"]))],
    )


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery, cfg: dict[str, Any]) -> None:
    try:
        _, days, stars = query.invoice_payload.split(":")
        plan = find_plan(cfg["premium_plans"], int(days))
        ok = plan is not None and int(plan["stars"]) == int(stars) == query.total_amount
    except ValueError:
        ok = False
    await query.answer(ok=ok, error_message=None if ok else "Тариф изменился, откройте /premium заново")


@router.message(F.successful_payment)
async def on_paid(message: Message, session: AsyncSession, user: User) -> None:
    sp = message.successful_payment
    if sp is None:
        return
    exists = await session.scalar(
        select(Payment.id).where(Payment.charge_id == sp.telegram_payment_charge_id)
    )
    if exists:
        return
    _, days, _ = sp.invoice_payload.split(":")
    now = datetime.now(UTC)
    until = extend_premium(user, now, days=int(days))
    session.add(
        Payment(
            user_id=user.id, stars=sp.total_amount, days=int(days), charge_id=sp.telegram_payment_charge_id
        )
    )
    await stats.incr(session, "premium_sales")
    await stats.incr(session, "premium_stars", sp.total_amount)
    await session.commit()
    await message.answer(t("premium_thanks", user.lang, until=_fmt_date(until)))
