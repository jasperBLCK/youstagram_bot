"""Тексты бота. Добавить язык = добавить колонку в TEXTS и код в services/users.SUPPORTED_LANGS."""

from typing import Any

TEXTS: dict[str, dict[str, str]] = {
    "start": {
        "ru": (
            "👋 <b>Привет, {name}!</b>\n\n"
            "Я скачиваю видео без водяных знаков из:\n"
            "▫️ <b>YouTube</b> — видео, Shorts и музыку в MP3\n"
            "▫️ <b>Instagram</b> — Reels, посты, IGTV\n"
            "▫️ <b>TikTok</b> — без водяного знака\n\n"
            "📎 <b>Просто пришли мне ссылку</b> — и через пару секунд получишь файл."
        ),
        "en": (
            "👋 <b>Hi, {name}!</b>\n\n"
            "I download videos without watermarks from:\n"
            "▫️ <b>YouTube</b> — videos, Shorts and MP3 music\n"
            "▫️ <b>Instagram</b> — Reels, posts, IGTV\n"
            "▫️ <b>TikTok</b> — no watermark\n\n"
            "📎 <b>Just send me a link</b> and get the file in seconds."
        ),
    },
    "help": {
        "ru": (
            "ℹ️ <b>Как пользоваться</b>\n\n"
            "1. Скопируй ссылку на видео в YouTube, Instagram или TikTok\n"
            "2. Отправь её сюда\n"
            "3. Для YouTube выбери: видео или MP3\n\n"
            "Добавь меня в групповой чат — буду скачивать видео по ссылкам прямо там 👥\n\n"
            "/premium — без рекламы и подписок\n/ref — пригласить друга и получить Premium бесплатно"
        ),
        "en": (
            "ℹ️ <b>How to use</b>\n\n"
            "1. Copy a YouTube, Instagram or TikTok link\n"
            "2. Send it here\n"
            "3. For YouTube choose: video or MP3\n\n"
            "Add me to a group chat — I'll download videos from links right there 👥\n\n"
            "/premium — no ads and no subscriptions\n/ref — invite a friend and get Premium for free"
        ),
    },
    "no_link": {
        "ru": "🤔 Не вижу ссылки. Пришли ссылку на видео из YouTube, Instagram или TikTok.",
        "en": "🤔 I don't see a link. Send a YouTube, Instagram or TikTok video link.",
    },
    "choose_format": {
        "ru": "🎬 <b>Что скачать?</b>",
        "en": "🎬 <b>What to download?</b>",
    },
    "btn_video": {"ru": "🎬 Видео", "en": "🎬 Video"},
    "btn_audio": {"ru": "🎵 Аудио MP3", "en": "🎵 Audio MP3"},
    "downloading": {
        "ru": "⏳ <b>Скачиваю…</b> обычно это занимает 5–20 секунд",
        "en": "⏳ <b>Downloading…</b> usually takes 5–20 seconds",
    },
    "queued_busy": {
        "ru": "⏳ Дождись окончания предыдущей загрузки, и пришли ссылку снова.",
        "en": "⏳ Please wait for the previous download to finish, then send the link again.",
    },
    "rate_limited": {
        "ru": "🐢 Слишком много запросов. Подожди минуту.",
        "en": "🐢 Too many requests. Please wait a minute.",
    },
    "expired": {
        "ru": "⌛️ Запрос устарел — пришли ссылку ещё раз.",
        "en": "⌛️ Request expired — send the link again.",
    },
    "err_too_big": {
        "ru": "😔 Видео слишком большое для Telegram. Попробуй MP3 или более короткое видео.",
        "en": "😔 The video is too large for Telegram. Try MP3 or a shorter video.",
    },
    "err_too_long": {
        "ru": "😔 Видео слишком длинное (лимит — {minutes} мин).",
        "en": "😔 The video is too long (limit is {minutes} min).",
    },
    "err_private": {
        "ru": "🔒 Видео закрыто или требует входа в аккаунт. Я могу скачивать только публичные видео.",
        "en": "🔒 The video is private or requires login. I can only download public videos.",
    },
    "err_unavailable": {
        "ru": "🚫 Видео недоступно или удалено.",
        "en": "🚫 The video is unavailable or has been removed.",
    },
    "err_failed": {
        "ru": "⚠️ Не получилось скачать. Попробуй ещё раз через минуту.",
        "en": "⚠️ Download failed. Please try again in a minute.",
    },
    "gate": {
        "ru": (
            "🔓 <b>Остался один шаг!</b>\n\n"
            "Бот бесплатный благодаря нашим спонсорам. "
            "Подпишись на {count} и нажми <b>«✅ Проверить»</b> — видео придёт сразу, "
            "ссылку повторно отправлять не нужно."
        ),
        "en": (
            "🔓 <b>One last step!</b>\n\n"
            "This bot is free thanks to our sponsors. "
            "Subscribe to {count} and tap <b>«✅ Check»</b> — your video will arrive instantly, "
            "no need to resend the link."
        ),
    },
    "gate_count_1": {"ru": "канал ниже", "en": "the channel below"},
    "gate_count_n": {"ru": "каналы ниже", "en": "the channels below"},
    "btn_check": {"ru": "✅ Проверить", "en": "✅ Check"},
    "btn_skip_premium": {"ru": "⭐ Скачивать без подписок", "en": "⭐ Download without subscriptions"},
    "gate_not_done": {
        "ru": "❌ Ты ещё не подписался на: {names}",
        "en": "❌ You haven't subscribed to: {names}",
    },
    "gate_ok": {"ru": "✅ Спасибо! Отправляю видео…", "en": "✅ Thanks! Sending your video…"},
    "caption_brand": {"ru": "📥 Скачано через {bot}", "en": "📥 Downloaded via {bot}"},
    "premium": {
        "ru": (
            "⭐ <b>Premium</b>\n\n"
            "✔️ Никаких обязательных подписок\n"
            "✔️ Никакой рекламы после скачивания\n"
            "✔️ Поддерживаешь развитие бота 💙\n\n"
            "{status}Оплата — Telegram Stars, в пару касаний 👇"
        ),
        "en": (
            "⭐ <b>Premium</b>\n\n"
            "✔️ No mandatory subscriptions\n"
            "✔️ No ads after downloads\n"
            "✔️ Support the bot development 💙\n\n"
            "{status}Pay with Telegram Stars in a couple of taps 👇"
        ),
    },
    "premium_active": {
        "ru": "✅ Premium активен до <b>{until}</b>\n\n",
        "en": "✅ Premium is active until <b>{until}</b>\n\n",
    },
    "premium_plan": {"ru": "{days} дн. — {stars} ⭐", "en": "{days} days — {stars} ⭐"},
    "premium_invoice_title": {"ru": "Premium на {days} дн.", "en": "Premium for {days} days"},
    "premium_invoice_desc": {
        "ru": "Скачивание без обязательных подписок и рекламы",
        "en": "Downloads without mandatory subscriptions and ads",
    },
    "premium_thanks": {
        "ru": "🎉 <b>Premium активирован</b> до {until}. Спасибо за поддержку!",
        "en": "🎉 <b>Premium activated</b> until {until}. Thanks for your support!",
    },
    "premium_disabled": {"ru": "Premium временно недоступен.", "en": "Premium is temporarily unavailable."},
    "ref": {
        "ru": (
            "🎁 <b>Приглашай друзей — получай Premium бесплатно</b>\n\n"
            "За каждого друга, который скачает первое видео, ты получаешь "
            "<b>{hours} ч</b> без подписок и рекламы.\n\n"
            "Твоя ссылка:\n<code>{link}</code>\n\n"
            "Приглашено: <b>{count}</b>"
        ),
        "en": (
            "🎁 <b>Invite friends — get Premium for free</b>\n\n"
            "For every friend who downloads their first video you get "
            "<b>{hours} h</b> without subscriptions and ads.\n\n"
            "Your link:\n<code>{link}</code>\n\n"
            "Invited: <b>{count}</b>"
        ),
    },
    "btn_share": {"ru": "📤 Поделиться ссылкой", "en": "📤 Share link"},
    "share_text": {
        "ru": "Скачивай видео из YouTube, Instagram и TikTok прямо в Telegram 👇",
        "en": "Download YouTube, Instagram and TikTok videos right in Telegram 👇",
    },
    "ref_reward": {
        "ru": "🎉 Твой друг скачал первое видео! Тебе начислено <b>{hours} ч Premium</b>.",
        "en": "🎉 Your friend downloaded their first video! You got <b>{hours} h of Premium</b>.",
    },
    "upsell_ref": {
        "ru": "💡 Хочешь скачивать без подписок? Пригласи друга — получишь {hours} ч Premium бесплатно.",
        "en": "💡 Want to download without subscriptions? Invite a friend and get {hours} h of Premium free.",
    },
    "btn_premium": {"ru": "⭐ Premium", "en": "⭐ Premium"},
    "btn_invite": {"ru": "🎁 Пригласить друга", "en": "🎁 Invite a friend"},
    "btn_add_group": {"ru": "👥 Добавить в группу", "en": "👥 Add to group"},
    "btn_lang": {"ru": "🌐 English", "en": "🌐 Русский"},
    "lang_changed": {"ru": "Язык: русский 🇷🇺", "en": "Language: English 🇬🇧"},
    "maintenance": {
        "ru": "🛠 Бот на техническом обслуживании. Вернёмся через несколько минут!",
        "en": "🛠 The bot is under maintenance. We'll be back in a few minutes!",
    },
    "banned": {"ru": "⛔️ Доступ ограничен.", "en": "⛔️ Access restricted."},
    "ad_label": {"ru": "Реклама", "en": "Ad"},
}


def t(key: str, lang: str, **kwargs: Any) -> str:
    entry = TEXTS[key]
    text = entry.get(lang) or entry["ru"]
    return text.format(**kwargs) if kwargs else text
