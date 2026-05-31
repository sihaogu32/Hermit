"""Tests for the consent-center managed-store helpers (tools/consent_memory.py).

propose_memory only stages candidates into the review area; apply_proposal is
the SOLE gated writer that lands confirmed items into the managed store.
HERMES_HOME points at a tmp dir throughout.

RED LINE #5: the module body must contain NO top-level registry.register(...)
call — apply_proposal is never reachable as an agent tool.
"""

import json
from pathlib import Path

import pytest

from tools import consent_memory as cm


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    return tmp_path


def _staged_payload(home):
    files = list((home / "consent_proposals").glob("*.json"))
    assert len(files) == 1
    return files[0], json.loads(files[0].read_text(encoding="utf-8"))


def _confirmed_path(home):
    return home / "memories" / "managed" / "CONFIRMED.md"


def test_propose_writes_staging_only(home):
    """propose only stages; it never touches the managed store."""
    res = cm.propose_memory(
        [{"content": "User prefers morning meetings", "target": "memory"}],
        source="agent",
    )
    assert res["item_count"] == 1
    path, payload = _staged_payload(home)
    assert res["path"] == str(path)
    assert res["proposal_id"] == payload["proposal_id"]
    assert payload["status"] == "pending"
    assert payload["source"] == "agent"
    # The managed store must not exist yet — staging only.
    assert not _confirmed_path(home).exists()


def test_propose_fills_default_id_and_target_and_counts(home):
    """Items missing id/target get item-N / 'memory'; summary counts are right."""
    cm.propose_memory(
        [
            {"content": "fact A"},  # no id, no target -> item-1 / memory
            {"content": "fact B", "id": "b", "target": "user"},
        ],
        source="google_calendar",
    )
    _, payload = _staged_payload(home)
    items = payload["items"]
    assert items[0]["id"] == "item-1"
    assert items[0]["target"] == "memory"
    assert items[1]["id"] == "b"
    assert items[1]["target"] == "user"
    summary = payload["summary"]
    assert summary["item_count"] == 2
    assert summary["targets"] == {"memory": 1, "user": 1}


def test_apply_writes_confirmed_audit_and_unlinks(home):
    """apply: CONFIRMED.md gets content, audit lands in consent_history/,
    staging is unlinked, returned count is correct."""
    cm.propose_memory(
        [{"content": "Likes oolong tea", "id": "tea", "target": "memory"}],
        source="google_calendar",
    )
    path, payload = _staged_payload(home)
    proposal_id = payload["proposal_id"]

    result = cm.apply_proposal(proposal_id)

    assert result["count"] == 1
    assert result["written"] == ["tea"]
    assert result["proposal_id"] == proposal_id

    # Confirmed managed store has the content.
    confirmed = _confirmed_path(home)
    assert confirmed.exists()
    body = confirmed.read_text(encoding="utf-8")
    assert "Likes oolong tea" in body
    assert "item=tea" in body
    assert f"proposal={proposal_id}" in body

    # Audit written to consent_history/ as confirm_*.json.
    audit_files = list((home / "consent_history").glob("confirm_*.json"))
    assert len(audit_files) == 1
    assert str(audit_files[0]) == result["audit_path"]
    audit = json.loads(audit_files[0].read_text(encoding="utf-8"))
    assert audit["proposal_id"] == proposal_id
    assert audit["counts"]["written"] == 1
    assert audit["selected_item_ids"] == ["tea"]
    assert "CONFIRMED.md" in audit["target_path"]

    # Staging removed.
    assert not path.exists()


def test_apply_selected_item_ids_writes_only_selected(home):
    """selected_item_ids filters; None means all."""
    cm.propose_memory(
        [
            {"content": "alpha", "id": "a"},
            {"content": "beta", "id": "b"},
            {"content": "gamma", "id": "c"},
        ],
    )
    _, payload = _staged_payload(home)
    result = cm.apply_proposal(payload["proposal_id"], selected_item_ids=["a", "c"])

    assert result["count"] == 2
    assert result["written"] == ["a", "c"]
    body = _confirmed_path(home).read_text(encoding="utf-8")
    assert "alpha" in body
    assert "gamma" in body
    assert "beta" not in body


def test_apply_none_writes_all_items(home):
    """selected_item_ids=None confirms every staged item."""
    cm.propose_memory(
        [
            {"content": "one", "id": "1"},
            {"content": "two", "id": "2"},
        ],
    )
    _, payload = _staged_payload(home)
    result = cm.apply_proposal(payload["proposal_id"], selected_item_ids=None)

    assert result["count"] == 2
    assert result["written"] == ["1", "2"]
    body = _confirmed_path(home).read_text(encoding="utf-8")
    assert "one" in body
    assert "two" in body


def test_apply_missing_proposal_raises(home):
    with pytest.raises(FileNotFoundError):
        cm.apply_proposal("does-not-exist")


def test_module_registers_no_agent_tools(home):
    """RED LINE #5: apply_proposal is the sole writer and is NOT an agent tool;
    the module body must contain no top-level registry.register(...) call."""
    from tools import registry
    src = Path(cm.__file__)
    assert registry._module_registers_tools(src) is False
