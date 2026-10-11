"""Outbound A2A client (re-exported from agentkit, settings-bound helpers)."""

from __future__ import annotations

from agentkit.a2a.client import A2AClient, Peer, _texts_from
from agentkit.a2a.client import build_a2a_client as build_a2a_client
from agentkit.a2a.client import load_peers as _load_peers

from artemis.config import Settings

__all__ = ["A2AClient", "Peer", "build_a2a_client", "load_peers", "_texts_from"]


def load_peers(settings: Settings) -> dict[str, Peer]:
    """Load configured A2A peers from ``settings.peers_file``."""
    return _load_peers(settings.peers_file)
