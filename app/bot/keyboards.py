from typing import Any
from urllib.parse import quote

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.texts import t
from app.db.models import Sponsor, SponsorKind
from app.services.tracking import tracked_url


def formats(token: str, lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_video", lang), callback_data=f"fmt:{token}:video"),
                InlineKeyboardButton(text=t("btn_audio", lang), callback_data=f"fmt:{token}:audio"),
            ]
        ]
    )


def sponsor_url(s: Sponsor, user_id: int) -> str:
    if s.kind == SponsorKind.LINK:
        return tracked_url("s", s.id, s.url, u=user_id)
    return s.url


def gate(
    sponsors: list[Sponsor], user_id: int, lang: str, *, done: set[int] | None = None, premium: bool = True
) -> InlineKeyboardMarkup:
    done = done or set()
    rows = [
        [InlineKeyboardButton(text=("✅ " if s.id in done else "➕ ") + s.title, url=sponsor_url(s, user_id))]
        for s in sponsors
    ]
    rows.append([InlineKeyboardButton(text=t("btn_check", lang), callback_data="gate:check")])
    if premium:
        rows.append([InlineKeyboardButton(text=t("btn_skip_premium", lang), callback_data="menu:premium")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def main_menu(lang: str, bot_username: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=t("btn_premium", lang), callback_data="menu:premium"),
                InlineKeyboardButton(text=t("btn_invite", lang), callback_data="menu:ref"),
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_add_group", lang), url=f"https://t.me/{bot_username}?startgroup=src_group"
                ),
                InlineKeyboardButton(text=t("btn_lang", lang), callback_data="menu:lang"),
            ],
        ]
    )


def premium_plans(plans: list[dict[str, Any]], lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("premium_plan", lang, days=p["days"], stars=p["stars"]),
                    callback_data=f"buy:{p['days']}",
                )
            ]
            for p in plans
        ]
    )


def share(link: str, lang: str) -> InlineKeyboardMarkup:
    url = f"https://t.me/share/url?url={quote(link)}&text={quote(t('share_text', lang))}"
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=t("btn_share", lang), url=url)]])
