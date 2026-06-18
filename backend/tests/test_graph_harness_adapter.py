"""Tests for the graph-harness adapter and its routing inside services.

The adapter module is importable without the ``harness.host`` package
installed (lazy import inside :func:`make_graph_harness_agent`); these tests
exercise the routing predicates and :func:`resolve_agent_factory` without
ever compiling a real preset.
"""

from __future__ import annotations

import pytest


def test_is_graph_harness_assistant_recognizes_prefix() -> None:
    """``gh:`` prefix selects the graph-harness adapter; anything else does not."""
    from app.gateway.adapters.graph_harness import is_graph_harness_assistant

    assert is_graph_harness_assistant("gh:echo") is True
    assert is_graph_harness_assistant("gh:multi-step-llm") is True
    assert is_graph_harness_assistant("lead_agent") is False
    assert is_graph_harness_assistant("finalis") is False
    # Defensive: None and empty string must NOT match — assistant_id is optional
    # and ``None``/``""`` is the path the existing lead-agent tests cover.
    assert is_graph_harness_assistant(None) is False
    assert is_graph_harness_assistant("") is False


def test_resolve_agent_factory_returns_graph_harness_for_gh_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """``gh:*`` assistant IDs route to ``make_graph_harness_agent`` from the adapter."""
    from app.gateway import services
    from app.gateway.adapters.graph_harness import make_graph_harness_agent

    # Stub the lead-agent import target so the test stays self-contained
    # (no need to exercise the real lead agent / config stack here).
    sentinel_lead = object()
    monkeypatch.setattr("deerflow.agents.lead_agent.agent.make_lead_agent", sentinel_lead, raising=False)

    assert services.resolve_agent_factory("gh:echo") is make_graph_harness_agent
    assert services.resolve_agent_factory("gh:multi-step-llm") is make_graph_harness_agent


def test_resolve_agent_factory_returns_lead_for_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-``gh:`` assistant IDs (including ``None`` and ``"lead_agent"``) keep the lead-agent path."""
    from app.gateway import services
    from deerflow.agents.lead_agent.agent import make_lead_agent

    assert services.resolve_agent_factory(None) is make_lead_agent
    assert services.resolve_agent_factory("lead_agent") is make_lead_agent
    assert services.resolve_agent_factory("finalis") is make_lead_agent


def test_graph_preset_in_context_whitelist() -> None:
    """``graph_preset`` must be in the run-context whitelist so ``merge_run_context_overrides``
    also forwards it when callers supply it via ``body.context``."""
    from app.gateway.services import _CONTEXT_CONFIGURABLE_KEYS

    assert "graph_preset" in _CONTEXT_CONFIGURABLE_KEYS
    assert "agent_name" in _CONTEXT_CONFIGURABLE_KEYS  # baseline keys preserved


def test_make_graph_harness_agent_raises_without_preset() -> None:
    """Calling the factory without ``graph_preset`` in configurable must fail loudly
    (instead of silently returning a misconfigured graph)."""
    from app.gateway.adapters.graph_harness import make_graph_harness_agent

    with pytest.raises(ValueError, match="graph_preset"):
        make_graph_harness_agent({})
    with pytest.raises(ValueError, match="graph_preset"):
        make_graph_harness_agent({"configurable": {}})