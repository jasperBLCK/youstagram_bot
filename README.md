# Youstagram Bot

Telegram-бот для скачивания видео из **YouTube, Instagram и TikTok** по ссылке + веб-админка для монетизации:
обязательная подписка (ОП) на каналы спонсоров, реклама после видео, платные рассылки, Premium за Telegram Stars,
реферальная программа и аналитика источников трафика.

Стратегия заработка и почему всё устроено именно так — в [docs/MONETIZATION.md](docs/MONETIZATION.md).

## Архитектура

```
Telegram ──► bot (aiogram 3, polling/webhook) ──► Redis (очередь arq, состояние, лимиты)
                    │                                   │
                    ▼                                   ▼
               PostgreSQL ◄──────────────────── worker (arq: yt-dlp + ffmpeg, рассылки, cron)
                    ▲
                    │
             admin (FastAPI + Jinja2) ── /r/* трекинг кликов
```

| Сервис   | Что делает | Масштабирование |
|----------|------------|-----------------|
| `bot`    | Принимает апдейты, ОП, выбор формата, кэш `file_id` → мгновенная выдача | webhook + несколько реплик за балансировщиком |
| `worker` | Скачивание (yt-dlp), конвертация, отправка, рассылки, крон | `docker compose up --scale worker=N`, по серверу на регион/прокси |
| `admin`  | Веб-админка, трекинг кликов | stateless, любое число реплик |
| Postgres | Пользователи, спонсоры, реклама, статистика по дням | один инстанс держит миллионы пользователей |
| Redis    | Очередь задач, отложенные запросы, локи, rate-limit | — |

Ключевые решения:
* **Кэш `file_id`**: популярное видео качается один раз, дальше отдаётся за миллисекунды без нагрузки на сервер.
* **Очередь**: бот никогда не блокируется загрузкой; один пользователь — одна загрузка одновременно.
* **Выбор формата под лимит Telegram**: лучшее H.264 ≤720p, влезающее в 50 МБ (или 2 ГБ со своим Bot API сервером).
* **Статистика по дням** (`daily_stats`) — дашборд не делает тяжёлых запросов по сырым данным.

## Быстрый старт (Docker)

1. Создайте бота у [@BotFather](https://t.me/BotFather), получите токен.
   Для работы в группах: `/setprivacy` → Disable. Для приёма Stars ничего настраивать не нужно.
2. Настройте окружение:
   ```bash
   cp .env.example .env
   # BOT_TOKEN, ADMIN_IDS, ADMIN_PASSWORD, ADMIN_SECRET_KEY (openssl rand -hex 32), PUBLIC_BASE_URL
   ```
3. Запустите:
   ```bash
   docker compose up -d --build
   ```
   Миграции применяются автоматически (сервис `migrate`). Админка: http://localhost:8000.
4. В админке: **Спонсоры → Добавить** → добавьте бота админом в канал спонсора → «Проверить канал».

### Instagram
Instagram отдаёт большинство публикаций только залогиненным. Экспортируйте `cookies.txt` (формат Netscape)
из браузера с запасного аккаунта, положите в `./data/cookies.txt`, смонтируйте в `worker` и укажите
`YTDLP_COOKIES_FILE=/data/cookies.txt`. При объёмах от тысяч загрузок в день используйте несколько аккаунтов
и резидентные прокси (`YTDLP_PROXY`), иначе YouTube/Instagram начнут ограничивать IP сервера.

### Большие файлы
Bot API ограничивает загрузку 50 МБ. Поднимите [telegram-bot-api](https://github.com/tdlib/telegram-bot-api)
(`--local`) и укажите `BOT_API_URL` — лимит станет 2 ГБ.

### Продакшен
* `WEBHOOK_URL=https://bot.example.com/webhook` + `WEBHOOK_SECRET` вместо polling.
* Админку — за HTTPS (Caddy/nginx), `PUBLIC_BASE_URL` = её адрес (нужен для трекинга кликов).
* Воркеры масштабируются горизонтально; yt-dlp обновляйте регулярно (`uv lock --upgrade-package yt-dlp`).

## Локальная разработка

```bash
uv sync
docker compose up -d postgres redis            # или свои
export DATABASE_URL=postgresql+asyncpg://bot:bot@localhost:5432/bot REDIS_URL=redis://localhost:6379/0
uv run alembic upgrade head
uv run python -m app.bot                        # бот
uv run python -m app.worker                     # воркер
uv run uvicorn app.admin.main:app --reload      # админка
```

Проверки:
```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy app tests
uv run pytest
```

Новая миграция после изменения моделей: `uv run alembic revision --autogenerate -m "..."`.

## Структура

```
app/
  bot/        хендлеры aiogram, клавиатуры, тексты (ru/en), флоу ОП
  worker/     задачи arq: загрузка, рассылка, крон
  admin/      FastAPI-админка: роуты, шаблоны, статика
  services/   бизнес-логика: ОП, реклама, загрузчик, статистика, настройки
  db/         модели SQLAlchemy
migrations/   Alembic
tests/        pytest
docs/         стратегия монетизации
```
