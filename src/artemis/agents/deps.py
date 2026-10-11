"""Artemis agent deps: agentkit's :class:`Deps` plus a price source."""

from __future__ import annotations

from dataclasses import dataclass

from agentkit.deps import ApprovalCallback, ApprovalRequest
from agentkit.deps import Deps as _BaseDeps

from artemis.prices.base import PriceSource

__all__ = ["Deps", "ApprovalRequest", "ApprovalCallback"]


@dataclass
class Deps(_BaseDeps):
    """Everything an Artemis tool needs; ``settings`` is an Artemis ``Settings``.

    ``owner_id``, ``artifacts``, ``remember_artifact``, ``now`` etc. come from
    the agentkit base.
    """

    price_source: PriceSource | None = None
