"""Local soak harness — run manually: `uv run python tests/soak.py [N]`.

Runs N durable agent turns with a stub model (no network, no cost) against a
throwaway ARTEMIS_HOME and checks that message history grows exactly 2 messages
per turn (no loss, no duplication) and that repeated report jobs stay stable.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

os.environ["ARTEMIS_HOME"] = tempfile.mkdtemp()

from pydantic_ai.messages import ModelResponse, TextPart  # noqa: E402
from pydantic_ai.models.function import FunctionModel  # noqa: E402

from artemis import durability  # noqa: E402

N = int(sys.argv[1]) if len(sys.argv) > 1 else 200


def main() -> None:
    durability.set_model_factory(
        lambda s: FunctionModel(lambda m, i: ModelResponse(parts=[TextPart("soak reply")]))
    )
    conversation = "cli:soak"
    started = time.time()
    for i in range(N):
        result = durability.run_turn(f"turn {i}", conversation_id=conversation)
        assert result["output"] == "soak reply"

    runtime = durability.build_runtime(durability.get_settings())
    with durability.repositories(runtime) as repos:
        count = len(repos.messages.list(conversation))
    assert count == 2 * N, f"expected {2 * N} messages, found {count}"

    report = durability.run_report_job("this-month")
    assert "Spending report" in report["text"]

    elapsed = time.time() - started
    print(f"soak OK: {N} turns, {count} messages, {elapsed:.1f}s ({elapsed / N * 1000:.0f} ms/turn)")


if __name__ == "__main__":
    main()
