"""Tests for the agent-facing consent "propose" tool (tools/consent_propose_tool.py).

This module is the ONLY consent-center module with a top-level
registry.register(...) call: it registers a single tool, ``propose_memory``,
under the ``consent-dev`` toolset. The handler wraps consent_memory.propose_memory
and returns a JSON string; it NEVER writes personal memory directly.
HERMES_HOME points at a tmp dir throughout.
"""

import json
from pathlib import Path

import pytest

# Importing the module registers ``propose_memory`` into the global registry.
from tools import consent_propose_tool as cpt
from tools.registry import registry


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def _staged_payload(home):
    files = list((home / "consent_proposals").glob("*.json"))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


def test_propose_memory_is_registered_under_consent_dev():
    """The module registers propose_memory in the consent-dev toolset."""
    entry = registry.get_entry("propose_memory")
    assert entry is not None
    assert entry.name == "propose_memory"
    assert entry.toolset == "consent-dev"
    assert "propose_memory" in registry.get_tool_names_for_toolset("consent-dev")


def test_handler_returns_valid_json_and_stages_file(home):
    """Calling the handler returns parseable JSON with a proposal_id and
    actually stages a file under HERMES_HOME/consent_proposals/."""
    out = cpt.handler({"items": [{"content": "User lives in Taipei"}]})
    parsed = json.loads(out)
    assert "proposal_id" in parsed
    assert parsed["item_count"] == 1

    path, payload = _staged_payload(home)
    assert payload["proposal_id"] == parsed["proposal_id"]
    assert str(path) == parsed["path"]
    assert payload["items"][0]["content"] == "User lives in Taipei"


def test_handler_defaults_source_to_google_calendar(home):
    """Omitting source falls back to 'google_calendar' in the staged payload."""
    cpt.handler({"items": [{"content": "no source given"}]})
    _, payload = _staged_payload(home)
    assert payload["source"] == "google_calendar"


def test_handler_passes_through_explicit_source(home):
    """An explicit source is forwarded into the staged payload."""
    cpt.handler({"items": [{"content": "from agent"}], "source": "agent"})
    _, payload = _staged_payload(home)
    assert payload["source"] == "agent"


def test_dispatch_via_registry_stages_file(home):
    """Dispatching through the registry by name works end to end."""
    out = registry.dispatch("propose_memory", {"items": [{"content": "via dispatch"}]})
    parsed = json.loads(out)
    assert "proposal_id" in parsed
    _, payload = _staged_payload(home)
    assert payload["items"][0]["content"] == "via dispatch"


def test_module_registers_tools_is_true():
    """RED LINE #5 counterpart: this module IS the consent-center's sole
    registration point, so _module_registers_tools must be True for it."""
    from tools.registry import _module_registers_tools
    src = Path(cpt.__file__)
    assert _module_registers_tools(src) is True
