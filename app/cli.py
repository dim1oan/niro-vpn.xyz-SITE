"""CLI сайта: python -m app.cli create-admin --email admin@example.com

Первый админ: создаёт пользователя с паролем и is_site_admin=true
(или повышает существующего).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass

from app.config import get_config
from app.db.base import Base
from app.db.models import User
from app.db.repositories.site import SiteUserRepo
from app.db.session import make_engine, make_session_factory
from app.web.security import hash_password


async def create_admin(email: str, password: str) -> None:
    cfg = get_config()
    engine = make_engine(cfg)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)
    async with factory() as session:
        repo = SiteUserRepo(session)
        user = await repo.get_by_email(email)
        if user is None:
            user = User(telegram_id=None, email=email, password_hash=hash_password(password))
            session.add(user)
        else:
            user.password_hash = hash_password(password)
        user.is_site_admin = True
        session.add(user)
        await session.commit()
        print(f"OK: {email} — site admin (id={user.id})")
    await engine.dispose()


async def promote(telegram_id: int) -> None:
    cfg = get_config()
    engine = make_engine(cfg)
    factory = make_session_factory(engine)
    from sqlalchemy import select

    async with factory() as session:
        user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
        if user is None:
            print(f"Пользователь с telegram_id={telegram_id} не найден")
            return
        user.is_site_admin = True
        session.add(user)
        await session.commit()
        print(f"OK: tg {telegram_id} — site admin (id={user.id})")
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="CLI vpn-site")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_create = sub.add_parser("create-admin", help="создать/обновить админа сайта по email")
    p_create.add_argument("--email", required=True)

    p_promote = sub.add_parser("promote", help="сделать админом сайта пользователя бота по telegram_id")
    p_promote.add_argument("--telegram-id", type=int, required=True)

    args = parser.parse_args()
    if args.cmd == "create-admin":
        password = getpass.getpass("Пароль (мин. 8 символов): ")
        if len(password) < 8:
            raise SystemExit("Пароль слишком короткий")
        asyncio.run(create_admin(args.email, password))
    elif args.cmd == "promote":
        asyncio.run(promote(args.telegram_id))


if __name__ == "__main__":
    main()
