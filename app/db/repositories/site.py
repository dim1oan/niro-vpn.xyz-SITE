"""Репозитории сущностей, появившихся для сайта (миграция b4f2a0c7d901 в репо бота)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_config
from app.db.models import ActivationCode, EmailToken, PayoutRequest, SupportTicket, User


class SiteUserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        return await self.session.scalar(
            select(User).where(func.lower(User.email) == email.strip().lower())
        )

    async def email_taken(self, email: str, *, exclude_user_id: int | None = None) -> bool:
        q = select(func.count()).select_from(User).where(
            func.lower(User.email) == email.strip().lower()
        )
        if exclude_user_id is not None:
            q = q.where(User.id != exclude_user_id)
        return bool(await self.session.scalar(q) or 0)

    async def search(self, query: str) -> list[User]:
        """Поиск для админки: по id, telegram_id, email или username."""
        q = query.strip().lstrip("@")
        stmt = select(User).limit(20)
        if q.isdigit():
            n = int(q)
            stmt = stmt.where(or_(User.id == n, User.telegram_id == n))
        else:
            like = f"%{q.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(func.coalesce(User.email, "")).like(like),
                    func.lower(func.coalesce(User.username, "")).like(like),
                    func.lower(func.coalesce(User.first_name, "")).like(like),
                )
            )
        return list((await self.session.scalars(stmt.order_by(User.id))).all())

    async def audit(
        self,
        actor: User | None,
        action: str,
        entity: str | None = None,
        entity_id: int | None = None,
        payload: dict | None = None,
    ) -> None:
        from app.db.models import AuditLog

        self.session.add(
            AuditLog(
                actor_telegram_id=actor.telegram_id if actor else None,
                action=action,
                entity=entity,
                entity_id=entity_id,
                payload={**(payload or {}), "actor_user_id": actor.id if actor else None},
            )
        )


class ActivationRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, user_id: int) -> ActivationCode:
        import secrets

        cfg = get_config()
        code = ActivationCode(
            code=secrets.token_hex(5).upper(),  # 10 символов — удобно передавать голосом
            user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(days=cfg.activation_code_days),
        )
        self.session.add(code)
        await self.session.flush()
        return code

    async def find_valid(self, code: str) -> ActivationCode | None:
        row = await self.session.scalar(
            select(ActivationCode).where(
                func.upper(ActivationCode.code) == code.strip().upper(),
                ActivationCode.used_at.is_(None),
                ActivationCode.expires_at > datetime.now(UTC),
            )
        )
        return row

    async def mark_used(self, row: ActivationCode) -> None:
        row.used_at = datetime.now(UTC)
        self.session.add(row)


class TicketRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, user_id: int, subject: str, body: str, category: str = "support") -> SupportTicket:
        ticket = SupportTicket(
            user_id=user_id,
            subject=subject.strip()[:255],
            body=body.strip(),
            category=category,
        )
        self.session.add(ticket)
        await self.session.flush()
        return ticket

    async def get(self, ticket_id: int) -> SupportTicket | None:
        return await self.session.get(SupportTicket, ticket_id)

    async def get_for_user(self, ticket_id: int, user_id: int) -> SupportTicket | None:
        return await self.session.scalar(
            select(SupportTicket).where(SupportTicket.id == ticket_id, SupportTicket.user_id == user_id)
        )

    async def list_for_user(self, user_id: int) -> list[SupportTicket]:
        rows = await self.session.scalars(
            select(SupportTicket)
            .where(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.created_at.desc())
            .limit(50)
        )
        return list(rows)

    async def list_all(
        self, *, open_only: bool = False, category: str | None = None, limit: int = 50
    ) -> list[SupportTicket]:
        q = select(SupportTicket).order_by(SupportTicket.created_at.desc()).limit(limit)
        if open_only:
            q = q.where(SupportTicket.status == "open")
        if category:
            q = q.where(SupportTicket.category == category)
        rows = await self.session.scalars(q)
        return list(rows)

    async def open_count(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count()).select_from(SupportTicket).where(SupportTicket.status == "open")
            )
            or 0
        )

    async def reply(self, ticket: SupportTicket, reply: str) -> SupportTicket:
        ticket.admin_reply = reply.strip()
        ticket.answered_at = datetime.now(UTC)
        ticket.status = "closed"
        self.session.add(ticket)
        return ticket

    async def close(self, ticket: SupportTicket) -> SupportTicket:
        ticket.status = "closed"
        self.session.add(ticket)
        return ticket


class PayoutRepo:
    """Заявки на выплату реферальных начислений."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def totals(self, user_id: int) -> dict[str, int]:
        """earned/pending/approved/paid/available в копейках."""
        from sqlalchemy import func

        from app.db.models import Referral

        earned = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(Referral.reward_kopeks), 0)).where(
                    Referral.referrer_id == user_id
                )
            )
            or 0
        )
        pending = approved = paid = 0
        rows = await self.session.scalars(
            select(PayoutRequest).where(PayoutRequest.user_id == user_id)
        )
        for r in rows:
            if r.status == "pending":
                pending += r.amount_kopeks
            elif r.status == "approved":
                approved += r.amount_kopeks
            elif r.status == "paid":
                paid += r.amount_kopeks
        return {
            "earned": earned,
            "pending": pending,
            "approved": approved,
            "paid": paid,
            "available": max(0, earned - paid - pending - approved),
        }

    async def create(
        self, *, user_id: int, amount_kopeks: int, contact: str, ticket_id: int | None = None
    ) -> PayoutRequest:
        req = PayoutRequest(
            user_id=user_id, amount_kopeks=amount_kopeks, contact=contact.strip()[:255], ticket_id=ticket_id
        )
        self.session.add(req)
        await self.session.flush()
        return req

    async def get(self, req_id: int) -> PayoutRequest | None:
        return await self.session.get(PayoutRequest, req_id)

    async def list_for_user(self, user_id: int, limit: int = 30) -> list[PayoutRequest]:
        rows = await self.session.scalars(
            select(PayoutRequest)
            .where(PayoutRequest.user_id == user_id)
            .order_by(PayoutRequest.created_at.desc())
            .limit(limit)
        )
        return list(rows)

    async def list_all(self, *, pending_only: bool = False, limit: int = 100) -> list[PayoutRequest]:
        q = select(PayoutRequest).order_by(PayoutRequest.created_at.desc()).limit(limit)
        if pending_only:
            q = q.where(PayoutRequest.status == "pending")
        rows = await self.session.scalars(q)
        return list(rows)

    async def set_status(
        self, req: PayoutRequest, status: str, *, comment: str | None = None
    ) -> PayoutRequest:
        from app.utils.time import utcnow

        req.status = status
        req.admin_comment = comment
        req.processed_at = utcnow()
        self.session.add(req)
        return req


class EmailTokenRepo:
    """Токены подтверждения email. Повторная отправка — не чаще раза в 2 минуты."""

    RESEND_COOLDOWN = 120

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def issue(self, user_id: int, *, ttl_hours: int = 24) -> EmailToken:
        import secrets
        from datetime import timedelta

        from app.utils.time import utcnow

        recent = await self.session.scalar(
            select(EmailToken)
            .where(
                EmailToken.user_id == user_id,
                EmailToken.used_at.is_(None),
                EmailToken.created_at > utcnow() - timedelta(seconds=self.RESEND_COOLDOWN),
            )
            .limit(1)
        )
        if recent is not None:  # кулдаун — вернём существующий токен
            return recent
        token = EmailToken(
            token=secrets.token_urlsafe(32),
            user_id=user_id,
            expires_at=utcnow() + timedelta(hours=ttl_hours),
        )
        self.session.add(token)
        await self.session.flush()
        return token

    async def find_valid(self, token: str) -> EmailToken | None:
        from app.utils.time import utcnow

        return await self.session.scalar(
            select(EmailToken).where(
                EmailToken.token == token,
                EmailToken.used_at.is_(None),
                EmailToken.expires_at > utcnow(),
            )
        )

    async def mark_used(self, row: EmailToken) -> None:
        from app.utils.time import utcnow

        row.used_at = utcnow()
        self.session.add(row)
