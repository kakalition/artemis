"""Outbound A2A client built on the official ``a2a-sdk``.

Card resolution and ``message/send`` are handled by the SDK; this module adds
peer/credential loading and text extraction from the SDK's ``StreamResponse``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from a2a import types as t
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory

from artemis.config import Settings


@dataclass
class Peer:
    name: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    token: str | None = None


def load_peers(settings: Settings) -> dict[str, Peer]:
    if not settings.peers_file:
        return {}
    path = Path(settings.peers_file).expanduser()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    peers_raw = raw.get("peers", raw)
    peers: dict[str, Peer] = {}
    for name, spec in peers_raw.items():
        if isinstance(spec, str):
            peers[name] = Peer(name=name, url=spec)
        else:
            peers[name] = Peer(
                name=name,
                url=spec["url"],
                headers=dict(spec.get("headers", {})),
                token=spec.get("token"),
            )
    return peers


def _parts_text(parts: Any) -> list[str]:
    return [part.text for part in parts or [] if getattr(part, "text", None)]


def _texts_from(response: Any) -> list[str]:
    """Extract text from an a2a-sdk ``StreamResponse``."""
    which = response.WhichOneof("payload")
    target = getattr(response, which, None)
    if target is None:
        return []
    texts: list[str] = []
    if which == "artifact_update":
        texts += _parts_text(getattr(target.artifact, "parts", None))
        return texts
    for artifact in getattr(target, "artifacts", None) or []:
        texts += _parts_text(artifact.parts)
    texts += _parts_text(getattr(target, "parts", None))
    status = getattr(target, "status", None)
    if status is not None and getattr(status, "message", None) is not None:
        texts += _parts_text(status.message.parts)
    return texts


def build_a2a_client(settings: Settings) -> A2AClient:
    """Build an A2A client with the peers configured in ``PEERS_FILE``."""
    return A2AClient(load_peers(settings))


class A2AClient:
    """Calls configured or ad-hoc remote A2A agents via the official SDK."""

    def __init__(
        self,
        peers: dict[str, Peer] | None = None,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.peers = peers or {}
        self.timeout = timeout
        self.transport = transport

    def _headers(self, url: str) -> dict[str, str]:
        for peer in self.peers.values():
            if url.rstrip("/") == peer.url.rstrip("/"):
                headers = dict(peer.headers)
                if peer.token:
                    headers.setdefault("Authorization", f"Bearer {peer.token}")
                return headers
        return {}

    def _http(self, base: str) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport, headers=self._headers(base)
        )

    async def fetch_card(self, base_url: str) -> t.AgentCard:
        base = base_url.rstrip("/")
        async with self._http(base) as http:
            return await A2ACardResolver(http, base).get_agent_card()

    async def call_agent(
        self, agent_url: str, message: str, *, context_id: str | None = None
    ) -> str:
        base = agent_url.rstrip("/")
        async with self._http(base) as http:
            card = await A2ACardResolver(http, base).get_agent_card()
            client = ClientFactory(ClientConfig(httpx_client=http, streaming=False)).create(card)
            request = t.SendMessageRequest(
                message=t.Message(
                    message_id=str(uuid.uuid4()),
                    role=t.Role.ROLE_USER,
                    parts=[t.Part(text=message)],
                    **({"context_id": context_id} if context_id else {}),
                ),
                configuration=t.SendMessageConfiguration(accepted_output_modes=["text/plain"]),
            )
            texts: list[str] = []
            async for response in client.send_message(request):
                texts.extend(_texts_from(response))
        return "\n".join(text for text in texts if text).strip() or "(no reply)"
