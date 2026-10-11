"""Cross-cutting safety helpers.

Artemis' guardrails are structural:

* write/bulk tools require explicit approval (PydanticAI deferred tools);
* imported CSV text, MCP resource text and remote A2A replies are treated as
  untrusted data in every prompt, never as instructions;
* the MCP and A2A servers bind loopback by default (see
  :func:`warn_if_exposed`), and the MCP server exposes read-only tools only;
* no monetary amounts or secrets are written to logs.
"""

from __future__ import annotations

import ipaddress
import sys


def is_loopback(host: str | None) -> bool:
    if host in (None, "", "localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def warn_if_exposed(host: str | None, service: str) -> None:
    """Warn when a server is bound to a non-loopback interface."""
    if not is_loopback(host):
        print(
            f"WARNING: {service} is binding {host!r}, which is reachable beyond "
            "loopback. Put it behind a reverse proxy with authentication.",
            file=sys.stderr,
        )
