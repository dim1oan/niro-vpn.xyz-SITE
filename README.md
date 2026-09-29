# Сайт-кабинет VPN (веб-версия Telegram-бота)

Веб-приложение (FastAPI + Jinja2) для пользователей из РФ, у которых заблокирован Telegram.
Работает с **той же базой**, что и бот (`/opt/vpn_tg/data/bot.db`), и повторяет всю
пользовательскую функциональность бота: ключи (ссылка/QR/перевыпуск/сброс трафика),
покупка (ЮKassa / вручную / с баланса) с промокодами, триал, профиль, рефералы,
поддержка тикетами + админка.

## Структура

```
app/
  config.py            # pydantic-settings: читает свой .env + .env бота (общие SECRET_KEY/DATABASE_URL/YOOKASSA_*)
  db/                  # зеркало моделей бота + repos (миграции — только в репо бота)
  services/            # копия сервисного слоя бота (billing, provisioning, xui, yookassa) — без aiogram
  web/
    security.py        # bcrypt, rate-limit входа 5/15мин, CSRF
    vless.py           # build_vless_url + TTL-кэш inbound'ов
    services.py        # выдача по платежу, вебхук-логика
    routes/            # public, auth, cabinet, buy, admin, webhooks
  templates/, static/  # Bootstrap 5 (CDN), тёмная тема
  cli.py               # create-admin / promote
tests/                 # pytest + httpx ASGI (30 тестов)
deploy/                # systemd, nginx
```

## Запуск локально

```bash
python3 -m venv .venv --without-pip   # или обычный venv
.venv/bin/python <(curl -sS https://bootstrap.pypa.io/get-pip.py)
.venv/bin/pip install -r requirements.txt -r requirements-dev.txt
ln -sf ../vpn_tg/.env .env            # общий .env с ботом (или скопируйте)
.venv/bin/python -m pytest tests -q   # тесты
.venv/bin/python -m app               # http://127.0.0.1:8000
```

Первый админ сайта:

```bash
.venv/bin/python -m app.cli create-admin --email admin@example.com
# или повысить существующего пользователя бота:
.venv/bin/python -m app.cli promote --telegram-id 123456789
```

## Переменные окружения (см. .env.example)

Общие с ботом (берутся из его .env): `DATABASE_URL`, `SECRET_KEY`, `YOOKASSA_*`,
`BRAND_NAME`, `TIMEZONE`, `TRIAL_ENABLED`, `REFERRAL_PERCENT`, `MANUAL_PAY_*`.

Свои: `SITE_BASE_URL` (публичный https-домен — нужен для return_url ЮKassa и реферальных
ссылок), `BOT_BASE_DIR` (каталог бота для относительного sqlite-пути), `RECEIPTS_DIR`,
опционально SMTP (`SMTP_*`, `NOTIFY_EMAIL`, `SUPPORT_EMAIL`).

## Важное про общую БД

- Схемой владеет бот (alembic в репо бота). У сайта **нет** своих миграций.
- Разовая миграция `b4f2a0c7d901_web_accounts` (в репо бота) добавляет:
  `users.telegram_id` → nullable, `users.email/password_hash/is_site_admin`,
  таблицы `activation_codes` и `support_tickets`.
- Один раз на VPS включить WAL:
  `sqlite3 /opt/vpn_tg/data/bot.db "PRAGMA journal_mode=WAL;"`.
  Движок сайта сам ставит `busy_timeout=5000` на каждом соединении.
- Идемпотентность: `settle` и выдача подписки идемпотентны, вебхук сайта и
  reconcile-джоба бота могут сработать параллельно — это нормально.

## Активация существующих пользователей бота

1. Админ сайта: `/admin/users` → поиск → карточка → «🔑 Код активации».
2. Код передаётся пользователю любым каналом (действует 7 дней).
3. Пользователь открывает `/activate`, вводит код + email + пароль →
   привязка к его старому `User` (подписки, баланс, рефералы сохраняются).
