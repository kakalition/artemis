"""Repository layer.

Every repository is bound to a :class:`~sqlalchemy.orm.Session` and an
``owner_id`` so all reads/writes are owner-scoped (single-user today,
multi-user-ready). Repositories return ORM/SQLModel objects; pure aggregation
lives in :mod:`artemis.domain.reports`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime

from agentkit.db.repositories import AuditRepo, UsageRepo
from sqlalchemy import func
from sqlmodel import Session, select

from artemis.db.models import (
    A2ATaskRecord,
    Account,
    Budget,
    Category,
    Conversation,
    Goal,
    GoalContribution,
    Holding,
    MerchantRule,
    Message,
    PriceSnapshot,
    Transaction,
)


class AccountRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def list(self) -> list[Account]:
        return list(
            self.session.exec(
                select(Account).where(Account.owner_id == self.owner_id).order_by(Account.id)
            ).all()
        )

    def get(self, account_id: int) -> Account | None:
        account = self.session.get(Account, account_id)
        if account and account.owner_id == self.owner_id:
            return account
        return None

    def get_or_create_default(self, name: str = "Default", currency: str = "USD") -> Account:
        existing = self.session.exec(
            select(Account).where(Account.owner_id == self.owner_id).order_by(Account.id)
        ).first()
        if existing:
            return existing
        account = Account(owner_id=self.owner_id, name=name, kind="checking", currency=currency)
        self.session.add(account)
        self.session.flush()
        return account


class CategoryRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def list(self, kind: str | None = None) -> list[Category]:
        stmt = select(Category).where(Category.owner_id == self.owner_id)
        if kind:
            stmt = stmt.where(Category.kind == kind)
        return list(self.session.exec(stmt.order_by(Category.name)).all())

    def get(self, category_id: int) -> Category | None:
        category = self.session.get(Category, category_id)
        if category and category.owner_id == self.owner_id:
            return category
        return None

    def get_by_name(self, name: str) -> Category | None:
        return self.session.exec(
            select(Category).where(
                Category.owner_id == self.owner_id,
                func.lower(Category.name) == name.strip().lower(),
            )
        ).first()

    def create(self, name: str, kind: str = "expense") -> Category:
        category = Category(owner_id=self.owner_id, name=name.strip(), kind=kind)
        self.session.add(category)
        self.session.flush()
        return category

    def get_or_create(self, name: str, kind: str = "expense") -> Category:
        return self.get_by_name(name) or self.create(name, kind)

    def rename(self, category_id: int, new_name: str) -> Category:
        category = self.get(category_id)
        if category is None:
            raise KeyError(f"category {category_id} not found")
        category.name = new_name.strip()
        self.session.add(category)
        self.session.flush()
        return category


class MerchantRuleRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def list(self) -> list[MerchantRule]:
        return list(
            self.session.exec(
                select(MerchantRule)
                .where(MerchantRule.owner_id == self.owner_id)
                .order_by(MerchantRule.priority, MerchantRule.id)
            ).all()
        )

    def add(self, pattern: str, category_id: int, priority: int = 100) -> MerchantRule:
        rule = MerchantRule(
            owner_id=self.owner_id,
            pattern=pattern.strip().lower(),
            category_id=category_id,
            priority=priority,
        )
        self.session.add(rule)
        self.session.flush()
        return rule

    def delete(self, rule_id: int) -> None:
        rule = self.session.get(MerchantRule, rule_id)
        if rule and rule.owner_id == self.owner_id:
            self.session.delete(rule)
            self.session.flush()


class TransactionRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def add(
        self,
        *,
        posted_at: date,
        amount_minor: int,
        currency: str = "USD",
        description: str = "",
        merchant: str | None = None,
        category_id: int | None = None,
        account_id: int | None = None,
        source: str = "manual",
        external_id: str | None = None,
    ) -> Transaction:
        txn = Transaction(
            owner_id=self.owner_id,
            account_id=account_id,
            posted_at=posted_at,
            amount_minor=amount_minor,
            currency=currency.upper(),
            description=description,
            merchant=merchant,
            category_id=category_id,
            source=source,
            external_id=external_id,
        )
        self.session.add(txn)
        self.session.flush()
        return txn

    def external_id_exists(self, external_id: str, source: str | None = None) -> bool:
        stmt = select(Transaction.id).where(
            Transaction.owner_id == self.owner_id,
            Transaction.external_id == external_id,
        )
        if source:
            stmt = stmt.where(Transaction.source == source)
        return self.session.exec(stmt).first() is not None

    def bulk_add(self, txns: Sequence[Transaction]) -> tuple[list[Transaction], int]:
        """Insert transactions, skipping duplicates within the batch and by
        ``(owner_id, external_id)``. Returns ``(inserted, skipped)``."""
        inserted: list[Transaction] = []
        skipped = 0
        seen: set[str] = set()
        for txn in txns:
            txn.owner_id = self.owner_id
            ext = txn.external_id
            if ext:
                if ext in seen or self.external_id_exists(ext, txn.source):
                    skipped += 1
                    continue
                seen.add(ext)
            self.session.add(txn)
            inserted.append(txn)
        self.session.flush()
        return inserted, skipped

    def list(
        self,
        *,
        start: date | None = None,
        end: date | None = None,
        category_id: int | None = None,
        merchant: str | None = None,
        currency: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Transaction]:
        stmt = select(Transaction).where(Transaction.owner_id == self.owner_id)
        if start is not None:
            stmt = stmt.where(Transaction.posted_at >= start)
        if end is not None:
            stmt = stmt.where(Transaction.posted_at <= end)
        if category_id is not None:
            stmt = stmt.where(Transaction.category_id == category_id)
        if merchant is not None:
            stmt = stmt.where(func.lower(Transaction.merchant) == merchant.lower())
        if currency is not None:
            stmt = stmt.where(func.upper(Transaction.currency) == currency.upper())
        stmt = stmt.order_by(Transaction.posted_at.desc(), Transaction.id.desc())
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list(self.session.exec(stmt).all())

    def count(self) -> int:
        return (
            self.session.exec(
                select(func.count()).select_from(Transaction).where(
                    Transaction.owner_id == self.owner_id
                )
            ).one()
        )

    def set_category(self, transaction_id: int, category_id: int | None) -> Transaction | None:
        txn = self.session.get(Transaction, transaction_id)
        if txn is None or txn.owner_id != self.owner_id:
            return None
        txn.category_id = category_id
        self.session.add(txn)
        self.session.flush()
        return txn

    def delete(self, transaction_id: int) -> bool:
        txn = self.session.get(Transaction, transaction_id)
        if txn is None or txn.owner_id != self.owner_id:
            return False
        self.session.delete(txn)
        self.session.flush()
        return True

    def currencies(self) -> list[str]:
        rows = self.session.exec(
            select(Transaction.currency).where(Transaction.owner_id == self.owner_id).distinct()
        ).all()
        return sorted({r for r in rows if r})


class BudgetRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def upsert(self, category_id: int, period: str, amount_minor: int, currency: str = "USD") -> Budget:
        existing = self.get(category_id, period)
        if existing:
            existing.amount_minor = amount_minor
            existing.currency = currency.upper()
            self.session.add(existing)
            self.session.flush()
            return existing
        budget = Budget(
            owner_id=self.owner_id,
            category_id=category_id,
            period=period,
            amount_minor=amount_minor,
            currency=currency.upper(),
        )
        self.session.add(budget)
        self.session.flush()
        return budget

    def get(self, category_id: int, period: str) -> Budget | None:
        return self.session.exec(
            select(Budget).where(
                Budget.owner_id == self.owner_id,
                Budget.category_id == category_id,
                Budget.period == period,
            )
        ).first()

    def list(self, period: str | None = None) -> list[Budget]:
        stmt = select(Budget).where(Budget.owner_id == self.owner_id)
        if period:
            stmt = stmt.where(Budget.period == period)
        return list(self.session.exec(stmt.order_by(Budget.period.desc(), Budget.id)).all())

    def delete(self, budget_id: int) -> bool:
        budget = self.session.get(Budget, budget_id)
        if budget is None or budget.owner_id != self.owner_id:
            return False
        self.session.delete(budget)
        self.session.flush()
        return True


class GoalRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def list(self) -> list[Goal]:
        return list(
            self.session.exec(
                select(Goal).where(Goal.owner_id == self.owner_id).order_by(Goal.id)
            ).all()
        )

    def get(self, goal_id: int) -> Goal | None:
        goal = self.session.get(Goal, goal_id)
        if goal and goal.owner_id == self.owner_id:
            return goal
        return None

    def find_by_name(self, name: str) -> Goal | None:
        return self.session.exec(
            select(Goal).where(
                Goal.owner_id == self.owner_id,
                func.lower(Goal.name) == name.strip().lower(),
            )
        ).first()

    def create(
        self,
        name: str,
        target_minor: int,
        currency: str = "USD",
        target_date: date | None = None,
    ) -> Goal:
        goal = Goal(
            owner_id=self.owner_id,
            name=name.strip(),
            target_minor=target_minor,
            currency=currency.upper(),
            target_date=target_date,
        )
        self.session.add(goal)
        self.session.flush()
        return goal

    def add_contribution(
        self,
        goal_id: int,
        amount_minor: int,
        currency: str = "USD",
        contributed_at: date | None = None,
        note: str | None = None,
    ) -> GoalContribution:
        contribution = GoalContribution(
            goal_id=goal_id,
            amount_minor=amount_minor,
            currency=currency.upper(),
            contributed_at=contributed_at or date.today(),
            note=note,
        )
        self.session.add(contribution)
        self.session.flush()
        return contribution

    def contributions(self, goal_id: int) -> list[GoalContribution]:
        return list(
            self.session.exec(
                select(GoalContribution)
                .where(GoalContribution.goal_id == goal_id)
                .order_by(GoalContribution.contributed_at)
            ).all()
        )

    def contributed_minor(self, goal_id: int) -> int:
        total = self.session.exec(
            select(func.coalesce(func.sum(GoalContribution.amount_minor), 0)).where(
                GoalContribution.goal_id == goal_id
            )
        ).one()
        return int(total or 0)

    def delete(self, goal_id: int) -> bool:
        goal = self.get(goal_id)
        if goal is None:
            return False
        for contribution in self.contributions(goal_id):
            self.session.delete(contribution)
        self.session.delete(goal)
        self.session.flush()
        return True


class HoldingRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def list(self) -> list[Holding]:
        return list(
            self.session.exec(
                select(Holding).where(Holding.owner_id == self.owner_id).order_by(Holding.symbol)
            ).all()
        )

    def get(self, holding_id: int) -> Holding | None:
        holding = self.session.get(Holding, holding_id)
        if holding and holding.owner_id == self.owner_id:
            return holding
        return None

    def get_by_symbol(self, symbol: str) -> Holding | None:
        return self.session.exec(
            select(Holding).where(
                Holding.owner_id == self.owner_id,
                func.upper(Holding.symbol) == symbol.upper(),
            )
        ).first()

    def upsert(
        self,
        symbol: str,
        quantity,
        cost_basis_minor: int = 0,
        currency: str = "USD",
    ) -> Holding:
        holding = self.get_by_symbol(symbol)
        if holding:
            holding.quantity = quantity
            holding.cost_basis_minor = cost_basis_minor
            holding.currency = currency.upper()
            self.session.add(holding)
            self.session.flush()
            return holding
        holding = Holding(
            owner_id=self.owner_id,
            symbol=symbol.upper(),
            quantity=quantity,
            cost_basis_minor=cost_basis_minor,
            currency=currency.upper(),
        )
        self.session.add(holding)
        self.session.flush()
        return holding

    def delete(self, holding_id: int) -> bool:
        holding = self.get(holding_id)
        if holding is None:
            return False
        self.session.delete(holding)
        self.session.flush()
        return True


class PriceSnapshotRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def add(
        self, symbol: str, price_minor: int, currency: str = "USD", as_of: date | None = None, source: str = "manual"
    ) -> PriceSnapshot:
        snapshot = PriceSnapshot(
            symbol=symbol.upper(),
            as_of=as_of or date.today(),
            price_minor=price_minor,
            currency=currency.upper(),
            source=source,
        )
        self.session.add(snapshot)
        self.session.flush()
        return snapshot

    def latest(self, symbol: str) -> PriceSnapshot | None:
        return self.session.exec(
            select(PriceSnapshot)
            .where(func.upper(PriceSnapshot.symbol) == symbol.upper())
            .order_by(PriceSnapshot.as_of.desc(), PriceSnapshot.id.desc())
        ).first()

    def history(self, symbol: str) -> list[PriceSnapshot]:
        return list(
            self.session.exec(
                select(PriceSnapshot)
                .where(func.upper(PriceSnapshot.symbol) == symbol.upper())
                .order_by(PriceSnapshot.as_of)
            ).all()
        )


class ConversationRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def get_or_create(self, conversation_id: str, channel: str = "cli") -> Conversation:
        conv = self.session.get(Conversation, conversation_id)
        if conv:
            return conv
        conv = Conversation(id=conversation_id, owner_id=self.owner_id, channel=channel)
        self.session.add(conv)
        self.session.flush()
        return conv

    def touch(self, conversation_id: str) -> None:
        conv = self.session.get(Conversation, conversation_id)
        if conv:
            conv.updated_at = datetime.now(UTC)
            self.session.add(conv)
            self.session.flush()


class MessageRepo:
    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def append(self, conversation_id: str, payloads: Iterable[str]) -> int:
        seq = self.next_seq(conversation_id)
        count = 0
        for payload in payloads:
            self.session.add(Message(conversation_id=conversation_id, seq=seq, payload=payload))
            seq += 1
            count += 1
        self.session.flush()
        return count

    def next_seq(self, conversation_id: str) -> int:
        current = self.session.exec(
            select(func.coalesce(func.max(Message.seq), -1)).where(
                Message.conversation_id == conversation_id
            )
        ).one()
        return int(current) + 1

    def list(self, conversation_id: str, limit: int | None = None) -> list[Message]:
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.seq)
        )
        messages = list(self.session.exec(stmt).all())
        if limit is not None and len(messages) > limit:
            messages = messages[-limit:]
        return messages

    def clear(self, conversation_id: str) -> None:
        for message in self.list(conversation_id):
            self.session.delete(message)
        self.session.flush()


class A2ATaskRepo:
    """Durable store of A2A tasks (protobuf JSON payloads)."""

    def __init__(self, session: Session, owner_id: str) -> None:
        self.session = session
        self.owner_id = owner_id

    def upsert(
        self,
        task_id: str,
        owner: str,
        context_id: str | None,
        state: str,
        payload: str,
    ) -> A2ATaskRecord:
        existing = self.session.get(A2ATaskRecord, task_id)
        if existing is not None:
            existing.owner_id = owner
            existing.context_id = context_id
            existing.state = state
            existing.payload = payload
            existing.updated_at = datetime.now(UTC)
            self.session.add(existing)
            self.session.flush()
            return existing
        record = A2ATaskRecord(
            id=task_id, owner_id=owner, context_id=context_id, state=state, payload=payload
        )
        self.session.add(record)
        self.session.flush()
        return record

    def get(self, task_id: str) -> A2ATaskRecord | None:
        return self.session.get(A2ATaskRecord, task_id)

    def delete(self, task_id: str) -> None:
        record = self.session.get(A2ATaskRecord, task_id)
        if record is not None:
            self.session.delete(record)
            self.session.flush()

    def list(self) -> list[A2ATaskRecord]:
        return list(
            self.session.exec(
                select(A2ATaskRecord).order_by(A2ATaskRecord.updated_at.desc())
            ).all()
        )


@dataclass
class Repositories:
    """Container bundling every repository for one owner."""

    session: Session
    owner_id: str

    def __post_init__(self) -> None:
        self.accounts = AccountRepo(self.session, self.owner_id)
        self.categories = CategoryRepo(self.session, self.owner_id)
        self.rules = MerchantRuleRepo(self.session, self.owner_id)
        self.transactions = TransactionRepo(self.session, self.owner_id)
        self.budgets = BudgetRepo(self.session, self.owner_id)
        self.goals = GoalRepo(self.session, self.owner_id)
        self.holdings = HoldingRepo(self.session, self.owner_id)
        self.prices = PriceSnapshotRepo(self.session, self.owner_id)
        self.conversations = ConversationRepo(self.session, self.owner_id)
        self.messages = MessageRepo(self.session, self.owner_id)
        self.a2a = A2ATaskRepo(self.session, self.owner_id)
        self.usage = UsageRepo(self.session, self.owner_id)
        self.audit = AuditRepo(self.session, self.owner_id)
