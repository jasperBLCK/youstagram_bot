import json

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.deps import f_bool, f_str
from app.admin.routes.common import DB, Admin, back, flash, render
from app.services import settings_store

router = APIRouter(prefix="/settings")

GROUPS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Обязательная подписка",
        [
            ("gate_enabled", "Включить ОП", "Главный источник дохода. Выключайте только на время."),
            (
                "gate_free_downloads",
                "Бесплатных скачиваний до первой ОП",
                "1 = первое видео без условий: сначала ценность, потом «цена».",
            ),
            (
                "gate_cooldown_hours",
                "Часов свободы после ОП",
                "Сколько часов после прохождения ОП не показывать её снова.",
            ),
            (
                "gate_every_n",
                "…или каждые N скачиваний",
                "ОП вернётся раньше, если пользователь скачал N видео. 0 — только по времени.",
            ),
            (
                "gate_max_sponsors",
                "Каналов за раз",
                "2–3 — оптимум. Больше — сильнее падает конверсия и растёт отток.",
            ),
            (
                "gate_check_leavers",
                "Возвращать отписавшихся",
                "Отписался от спонсора — канал снова появится в ОП.",
            ),
        ],
    ),
    (
        "Реклама после скачивания",
        [
            ("ads_enabled", "Показывать рекламный блок", "Сообщение от рекламодателя сразу после видео."),
            ("ads_every_n", "Каждые N выдач", "1 — после каждого видео."),
            (
                "caption_branding",
                "Подпись «Скачано через @бот»",
                "Вирусный рост: пересланные видео ведут новых людей (источник share).",
            ),
        ],
    ),
    (
        "Premium и рефералка",
        [
            ("premium_enabled", "Продажа Premium за Telegram Stars", ""),
            ("premium_plans", "Тарифы (JSON)", 'Например: [{"days": 30, "stars": 150}]'),
            ("referral_enabled", "Реферальная программа", ""),
            (
                "referral_bonus_hours",
                "Часов Premium за друга",
                "Начисляется, когда друг скачал первое видео (защита от накрутки).",
            ),
            ("upsell_every_n", "Предлагать пригласить друга каждые N скачиваний", "0 — выключено."),
        ],
    ),
    (
        "Лимиты и режимы",
        [
            ("rate_limit_per_min", "Запросов в минуту на пользователя", ""),
            ("max_duration_min", "Макс. длительность видео, мин", ""),
            (
                "group_mode",
                "Работа в группах",
                "Бот качает ссылки в чатах (нужно выключить privacy mode в @BotFather).",
            ),
            ("maintenance", "Режим обслуживания", "Бот отвечает заглушкой всем, кроме админов."),
        ],
    ),
]


@router.get("", response_class=HTMLResponse)
async def index(request: Request, _: str = Admin, session: AsyncSession = DB) -> HTMLResponse:
    values = await settings_store.load_all(session, force=True)
    display = {
        k: json.dumps(v, ensure_ascii=False) if isinstance(v, list | dict) else v for k, v in values.items()
    }
    return render(request, "settings.html", groups=GROUPS, values=display, defaults=settings_store.DEFAULTS)


@router.post("")
async def save(request: Request, _: str = Admin, session: AsyncSession = DB) -> RedirectResponse:
    form = await request.form()
    new: dict[str, object] = {}
    for key, default in settings_store.DEFAULTS.items():
        if isinstance(default, bool):
            new[key] = f_bool(form, key)
        elif isinstance(default, int):
            try:
                new[key] = int(f_str(form, key) or default)
            except ValueError:
                flash(request, f"«{key}» должно быть целым числом", "err")
                return back("/settings")
        elif isinstance(default, list):
            try:
                parsed = json.loads(f_str(form, key) or "[]")
                assert isinstance(parsed, list)
                assert all(int(p["days"]) > 0 and int(p["stars"]) > 0 for p in parsed)
            except (ValueError, AssertionError, KeyError, TypeError):
                flash(request, f"«{key}»: неверный JSON", "err")
                return back("/settings")
            new[key] = parsed
    await settings_store.save(session, new)
    flash(request, "Настройки сохранены — применятся в течение 15 секунд")
    return back("/settings")
