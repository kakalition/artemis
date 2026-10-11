"""Human-in-the-loop approval wiring.

Tools marked ``requires_approval=True`` make the agent pause with a
``DeferredToolRequests`` output. We attach :class:`HandleDeferredToolCalls` to
the agent so the run continues automatically once the owner (CLI prompt or
Telegram inline buttons) approves or denies each call.
"""

from __future__ import annotations

from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.tools import (
    DeferredToolRequests,
    DeferredToolResults,
    RunContext,
    ToolApproved,
    ToolDenied,
)

from artemis.agents.deps import ApprovalRequest, Deps


async def approval_handler(
    ctx: RunContext[Deps], requests: DeferredToolRequests
) -> DeferredToolResults | None:
    pending = [
        ApprovalRequest(
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            args=call.args if isinstance(call.args, dict) else {},
        )
        for call in requests.approvals
    ]
    if not pending:
        return None
    if ctx.deps.approve is None:
        # Non-interactive context: deny destructive/bulk actions by default.
        decided: dict[str, bool] = {request.tool_call_id: False for request in pending}
    else:
        decided = await ctx.deps.approve(pending)
    # Any call the callback did not mention is denied explicitly so the deferred
    # batch is fully resolved and the run can continue.
    approvals: dict[str, bool | ToolApproved | ToolDenied] = {
        request.tool_call_id: bool(decided.get(request.tool_call_id, False)) for request in pending
    }
    return DeferredToolResults(approvals=approvals)


approval_capability = HandleDeferredToolCalls(handler=approval_handler)
