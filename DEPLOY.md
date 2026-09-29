# Деплой сайта на VPS 217.60.37.143 (тот же сервер, что и бот)

## 0. Предпосылки

- Бот развёрнут в `/opt/vpn_tg`, домен для сайта (напр. `vpn.example.com`) указывает
  A-записью на 217.60.37.143. Домен обязателен: пользователям нужен прямой HTTPS
  без VPN.
- Код сайта — в `/opt/vpn_site`.

## 1. Код и окружение

```bash
# залить код (rsync/git) в /opt/vpn_site, затем:
cd /opt/vpn_site
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# общий .env с ботом (сайт читает общие DATABASE_URL/SECRET_KEY/YOOKASSA_*)
ln -sf /opt/vpn_tg/.env /opt/vpn_site/.env
# затем добавить переменные сайта (SITE_BASE_URL и т.п.) — удобно держать их
# в /opt/vpn_tg/.env рядом с общими, они не мешают боту (extra="ignore")
```

## 2. Разовая миграция БД (в репо бота!)

```bash
cd /opt/vpn_tg
.venv/bin/alembic upgrade head      # применит b4f2a0c7d901_web_accounts
```

Остановите бота на время миграции (systemctl stop vpn-bot) — миграция секундная.
Миграция делает: `users.telegram_id` → nullable, добавляет `email/password_hash/
is_site_admin`, создаёт `activation_codes` и `support_tickets`. Данные не трогает.

## 2.1 Настройки ТЗ v2 (личные коды + модерация оплат в TG)

В `/opt/vpn_tg/.env` (общем) дополнить:

```ini
SITE_BASE_URL=https://vpn.example.com      # включит личные коды в боте
INTERNAL_API_TOKEN=<openssl rand -hex 32>  # один токен для бота и сайта
INTERNAL_API_PORT=8081
SITE_RECEIPTS_DIR=/opt/vpn_site/data/receipts
ACTIVATION_CODE_DAYS=7
```

- **Личные коды**: бот при первом `/start` сам выдаёт код сайта; кнопка «🌐 Кабинет
  на сайте» показывает/перевыпускает код. Юзер активирует аккаунт на `/activate`.
- **Модерация ручных оплат**: юзер грузит чек на сайте → сайт шлёт уведомление на
  `127.0.0.1:8081` (внутренний API бота, только localhost + токен) → админ получает
  в TG фото чека и кнопки «✅ Подтвердить / ❌ Отклонить» → после подтверждения
  страница платежа на сайте сама обновляется (поллинг 5 сек) и показывает ключ.
- Страховка: джоба бота `notify_web_manual` (10 мин) досылает пропущенные уведомления.
- Перезапустить бота после изменения `.env`: `systemctl restart vpn-bot`.

## 3. WAL для SQLite (один раз)

```bash
sqlite3 /opt/vpn_tg/data/bot.db "PRAGMA journal_mode=WAL;"
```

Снимает 99% блокировок между ботом и сайтом. Сайт дополнительно ставит
`busy_timeout=5000` на каждом соединении. **Бэкап: копировать `bot.db` + `bot.db-wal`.**

## 4. Первый админ сайта

```bash
cd /opt/vpn_site
.venv/bin/python -m app.cli create-admin --email you@example.com
# либо повысить пользователя бота (его подписки/баланс уже в БД):
.venv/bin/python -m app.cli promote --telegram-id <TG_ID>
```

## 5. systemd

```bash
cp /opt/vpn_site/deploy/vpn-site.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now vpn-site
systemctl status vpn-site
```

Юнит поднимает uvicorn на `127.0.0.1:8000` (снаружи только nginx).

## 6. nginx + certbot

```bash
cp /opt/vpn_site/deploy/nginx-vpn-site.conf /etc/nginx/sites-available/vpn-site
ln -sf /etc/nginx/sites-available/vpn-site /etc/nginx/sites-enabled/
# замените vpn.example.com на ваш домен, затем:
certbot --nginx -d vpn.example.com
nginx -t && systemctl reload nginx
```

## 7. Файрвол

```bash
ufw allow 80,443/tcp
# панель 3x-ui и VPN-порты не трогать
```

## 8. Вебхук ЮKassa

- В кабинете ЮKassa → Настройки → Вебхуки → добавьте
  `https://vpn.example.com/webhooks/yookassa` для события `payment.succeeded`.
- Бот работает в polling-режиме и вебхуков не слушает — конфликтов не будет.
- Reconcile-джоба бота остаётся страховкой: оба пути идемпотентны.

## 9. Приёмочные проверки

1. Пользователь бота: `/start` или кнопка «🌐 Кабинет на сайте» → получает личный
   код → `/activate` → в кабинете видны его подписки, трафик, рабочая `vless://`-ссылка и QR.
2. Покупка с промокодом: клиент появляется в inbound 3x-ui, ключ работает.
3. Вебхук ЮKassa выдаёт подписку автоматически и идемпотентно (повтор вебхука
   не создаёт вторую подписку).
4. Ручная оплата: чек на сайте → уведомление в TG-админ-чат → «Подтвердить» в TG →
   на сайте страница счёта сама показывает ключ (≤ 5 сек).
5. `systemctl restart vpn-site vpn-bot` — оба процесса живут на одной sqlite (WAL).
6. Админка: подтвердить ручной платёж, сменить inbound с переносом, ответить в тикет.

## 10. Обновление

```bash
cd /opt/vpn_site && git pull && .venv/bin/pip install -r requirements.txt
systemctl restart vpn-site
```
