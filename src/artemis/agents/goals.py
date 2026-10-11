"""Goals sub-agent: savings goals, contributions, and projections."""

from __future__ import annotations

from pydantic_ai import Agent, RunContext

from artemis.agents.deps import Deps
from artemis.agents.prompts import GOALS_INSTRUCTIONS
from artemis.agents.schemas import GoalRecord
from artemis.domain.money import format_minor, parse_amount
from artemis.domain.reports import GoalProjection, project_goal
from artemis.services import ledger


def _record(ctx: RunContext[Deps], goal) -> GoalRecord:
    contributed = ctx.deps.repos.goals.contributed_minor(goal.id)
    return GoalRecord(
        id=goal.id,
        name=goal.name,
        target_minor=goal.target_minor,
        target_display=format_minor(goal.target_minor, goal.currency),
        contributed_minor=contributed,
        contributed_display=format_minor(contributed, goal.currency),
        remaining_minor=max(goal.target_minor - contributed, 0),
        currency=goal.currency,
        target_date=goal.target_date,
    )


def _find_goal(ctx: RunContext[Deps], goal_id: int | None, goal_name: str | None):
    if goal_id is not None:
        return ctx.deps.repos.goals.get(goal_id)
    if goal_name is not None:
        return ctx.deps.repos.goals.find_by_name(goal_name)
    return None


goals_agent = Agent(
    name="goals",
    deps_type=Deps,
    output_type=str,
    instructions=GOALS_INSTRUCTIONS,
)


@goals_agent.tool
async def create_goal(
    ctx: RunContext[Deps],
    name: str,
    target: str,
    target_date: str | None = None,
    currency: str | None = None,
) -> GoalRecord:
    """Create a savings goal.

    Args:
        name: Goal name, e.g. "Holiday".
        target: Target amount, e.g. "5000".
        target_date: Optional ISO date (YYYY-MM-DD) to reach the goal.
        currency: ISO-4217 code; defaults to USD.
    """
    currency = (currency or "USD").upper()
    goal = ctx.deps.repos.goals.create(
        name=name,
        target_minor=parse_amount(target, currency),
        currency=currency,
        target_date=ledger.parse_date(target_date) if target_date else None,
    )
    return _record(ctx, goal)


@goals_agent.tool
async def add_contribution(
    ctx: RunContext[Deps],
    amount: str,
    goal_id: int | None = None,
    goal_name: str | None = None,
    contributed_at: str | None = None,
) -> GoalRecord | None:
    """Record a contribution to a goal (identify it by id or name)."""
    goal = _find_goal(ctx, goal_id, goal_name)
    if goal is None:
        return None
    ctx.deps.repos.goals.add_contribution(
        goal.id,
        parse_amount(amount, goal.currency),
        currency=goal.currency,
        contributed_at=ledger.parse_date(contributed_at) if contributed_at else None,
    )
    return _record(ctx, goal)


@goals_agent.tool
async def list_goals(ctx: RunContext[Deps]) -> list[GoalRecord]:
    """List all savings goals with progress."""
    return [_record(ctx, g) for g in ctx.deps.repos.goals.list()]


@goals_agent.tool
async def project_goal_progress(
    ctx: RunContext[Deps],
    goal_id: int | None = None,
    goal_name: str | None = None,
    monthly_contribution: str | None = None,
) -> GoalProjection | None:
    """Project required monthly savings (and an optional what-if scenario)."""
    goal = _find_goal(ctx, goal_id, goal_name)
    if goal is None:
        return None
    monthly_minor = (
        parse_amount(monthly_contribution, goal.currency) if monthly_contribution else None
    )
    return project_goal(
        goal_id=goal.id,
        name=goal.name,
        target_minor=goal.target_minor,
        contributed_minor=ctx.deps.repos.goals.contributed_minor(goal.id),
        currency=goal.currency,
        target_date=goal.target_date,
        monthly_contribution_minor=monthly_minor,
    )
