"""Конфигурация сайта. Читает тот же .env, что и бот (общие DATABASE_URL, SECRET_KEY,
YOOKASSA_*, BRAND_NAME, TIMEZONE). BOT_TOKEN сайту не нужен.

Порядок загрузки переменных: реальные переменные окружения > SITE_ENV_FILE (.env сайта)
> bot .env (общие значения). Файл бота: /opt/vpn_tg/.env на VPS, ../vpn_tg/.env локально
(или явно через BOT_ENV_FILE).
"""

from __future__ import annotations

import functools
import os
import secrets
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import dotenv_values
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


def _default_bot_dir() -> Path:
    env = os.environ.get("BOT_BASE_DIR")
    if env:
        return Path(env)
    if Path("/opt/vpn_tg").is_dir():
        return Path("/opt/vpn_tg")
    sibling = BASE_DIR.parent / "vpn_tg"
    if sibling.is_dir():
        return sibling
    return BASE_DIR


def load_env_files() -> None:
    """dotenv-файлы через setdefault: реальные env-переменные всегда сильнее."""
    chain: list[Path] = []
    site_env = os.environ.get("SITE_ENV_FILE")
    if site_env:
        chain.append(Path(site_env))
    else:
        chain.append(BASE_DIR / ".env")
    bot_env_raw = os.environ.get("BOT_ENV_FILE")
    bot_env = Path(bot_env_raw) if bot_env_raw else _default_bot_dir() / ".env"
    if bot_env.exists():
        chain.append(bot_env)
    for path in chain:
        if not path.exists():
            continue
        for key, value in dotenv_values(path).items():
            if value is None:
                continue
            os.environ.setdefault(key, value)


load_env_files()


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,  # переменные уже в os.environ (см. load_env_files)
        extra="ignore",
        case_sensitive=False,
    )

    # --- общие с ботом ---
    brand_name: str = "Niro VPN"
    timezone: str = "Europe/Moscow"
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    secret_key: str = ""
    bot_base_dir_raw: str | None = Field(default="", validation_alias="bot_base_dir")

    xui_base_url: str = ""
    xui_username: str = ""
    xui_password: str = ""

    # --- платежи ---
    yookassa_shop_id: str = ""
    yookassa_secret_key: str = ""
    manual_pay_enabled: bool = True
    manual_pay_details: str = ""

    # --- логика ---
    trial_enabled: bool = True
    referral_percent: int = 20
    referral_fixed_kopeks: int = 0  # фикс-вознаграждение за оплату приглашённого (0 = процентный режим)
    resend_api_key: str = ""  # Resend API: письма через HTTPS (порт 443), без SMTP
    email_from: str = "noreply@niro-vpn.xyz"  # адрес отправителя для Resend
    payout_min_kopeks: int = 10000  # минимальная сумма заявки на выплату (100 ₽)
    log_level: str = "INFO"

    # --- сайт ---
    site_base_url: str = "http://127.0.0.1:8000"  # публичный https://домен на VPS
    site_host: str = "127.0.0.1"
    site_port: int = 8000
    session_secret: str | None = ""  # подпись cookie-сессий; пусто => SECRET_KEY
    cookie_https_only: bool = False
    activation_code_days: int = 7
    receipts_dir: str = str(BASE_DIR / "data" / "receipts")

    # Внутренний API бота (ТЗ v2): уведомление о ручных оплатах
    internal_api_url: str = "http://127.0.0.1:8081"
    internal_api_token: str | None = ""  # INTERNAL_API_TOKEN из общего .env; пусто => не уведомляем

    # --- опциональный SMTP (уведомления админу о тикетах/оплатах, рассылка) ---
    smtp_host: str | None = ""
    smtp_port: int = 587
    smtp_user: str | None = ""
    smtp_password: str | None = ""
    notify_email: str | None = ""  # куда слать письма; пусто => выключено
    support_email: str | None = ""  # показывается на публичной странице поддержки

    @field_validator(
        "session_secret",
        "bot_base_dir_raw",
        "notify_email",
        "support_email",
        "smtp_host",
        "smtp_user",
        "smtp_password",
        "internal_api_token",
        mode="before",
    )
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    # --- пути и урлы ---

    @property
    def bot_base_dir(self) -> Path:
        return Path(self.bot_base_dir_raw) if self.bot_base_dir_raw else _default_bot_dir()

    @property
    def database_url_resolved(self) -> str:
        """DATABASE_URL с относительным sqlite-путём, привязанным к каталогу бота.

        Бот запускается из /opt/vpn_tg, сайт — из /opt/vpn_site: «./data/bot.db»
        обязан указывать на /opt/vpn_tg/data/bot.db для обоих процессов.
        Схема сохраняется целиком (sqlite+aiosqlite://), иначе драйвер станет sync.
        """
        import re

        url = self.database_url
        m = re.match(r"^(sqlite(?:\+[a-z0-9_]+)?):///(.+)$", url)
        if not m:
            return url
        scheme, tail = m.group(1), m.group(2)
        if tail.startswith("/"):  # абсолютный путь — не трогаем
            return url
        return f"{scheme}:///{(self.bot_base_dir / tail.lstrip('./')).resolve()}"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url_resolved.startswith("sqlite")

    @property
    def session_secret_value(self) -> str:
        return self.session_secret or self.secret_key or "insecure-dev-secret"

    @property
    def yookassa_enabled(self) -> bool:
        return bool(self.yookassa_shop_id and self.yookassa_secret_key)

    @property
    def smtp_enabled(self) -> bool:
        return bool(self.smtp_host and self.notify_email)

    def ensure_runtime(self) -> None:
        if not self.secret_key:
            raise RuntimeError("SECRET_KEY не задан (общий с ботом, Fernet base64)")

    def generate_missing_secret(self) -> None:
        """Идентично боту: пустой ключ генерирует, произвольный деривирует.
        Иначе расшифровка паролей панелей (Fernet) разъедется с ботом."""
        import base64
        import hashlib

        from cryptography.fernet import Fernet

        if not self.secret_key:
            self.secret_key = Fernet.generate_key().decode()
        else:
            try:
                Fernet(self.secret_key.encode())
            except ValueError:
                digest = hashlib.sha256(self.secret_key.encode()).digest()
                self.secret_key = base64.urlsafe_b64encode(digest).decode()


@functools.lru_cache
def get_config() -> Config:
    cfg = Config()
    cfg.generate_missing_secret()
    return cfg


def random_token(n: int = 16) -> str:
    return secrets.token_hex(n // 2)
