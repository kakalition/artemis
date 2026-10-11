from __future__ import annotations

from typer.testing import CliRunner

from artemis.cli import app
from artemis.config import Settings, get_settings
from artemis.soul import load_soul, resolve_soul_path


def test_project_soul_is_used():
    # The repo ships a SOUL.md at the project root.
    text = load_soul(Settings(owner_id="owner"))
    assert "Artemis" in text
    assert resolve_soul_path(Settings(owner_id="owner")).name == "SOUL.md"


def test_soul_command_prints_persona():
    result = CliRunner().invoke(app, ["soul"])
    assert result.exit_code == 0
    assert "Artemis" in result.output


def test_orchestrator_instructions_include_soul():
    from artemis.agents.orchestrator import orchestrator_agent

    parts = [getattr(item, "instruction", str(item)) for item in orchestrator_agent._instructions]
    assert "Artemis" in "\n".join(parts)
    assert get_settings() is not None
