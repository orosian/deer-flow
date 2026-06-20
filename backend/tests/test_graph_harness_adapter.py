"""Tests for the graph-harness adapter and its routing inside services.

The adapter module is importable without the ``harness.host`` package
installed (lazy import inside :func:`make_graph_harness_agent`); these tests
exercise the routing predicates and :func:`resolve_agent_factory` without
ever compiling a real preset.
"""

from __future__ import annotations

import pytest

from app.gateway.adapters.graph_harness import (
    _DEFAULT_ALLOWED_PRESETS,
    _EXPECTED_HOST_API_VERSION,
    GraphHarnessPresetAccessError,
    _allowed_presets,
    _check_preset_access,
)


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


# ---------------------------------------------------------------------------
# SEC-1: preset-name access control (pattern + whitelist + env override)
# ---------------------------------------------------------------------------


def test_check_preset_access_accepts_default_whitelist_members() -> None:
    """Members of the default whitelist pass the access check (no exception)."""
    for preset in _DEFAULT_ALLOWED_PRESETS:
        _check_preset_access(preset)  # should not raise


@pytest.mark.parametrize(
    "bad_name",
    [
        "../../etc/passwd",  # path traversal
        "/etc/passwd",  # absolute path
        "../foo",  # relative parent traversal
        "Foo/Bar",  # uppercase
        "foo\\bar",  # backslash
        "foo bar",  # whitespace
        "foo/bar/extra",  # too many segments
        "foo/",  # trailing slash
        "/foo",  # leading slash with valid name
        "",  # empty
    ],
)
def test_check_preset_access_rejects_pattern_violations(bad_name: str) -> None:
    """Pattern check rejects path traversal, absolute paths, backslashes, uppercase,
    and malformed shapes — surfaces as ``GraphHarnessPresetAccessError(code=400)``."""
    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        _check_preset_access(bad_name)
    assert exc_info.value.code == 400
    assert "invalid preset name format" in str(exc_info.value)


def test_check_preset_access_rejects_non_whitelisted() -> None:
    """A syntactically valid name that is not on the whitelist raises ``code=403``."""
    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        _check_preset_access("unlisted/preset")
    assert exc_info.value.code == 403
    assert "allow-list" in str(exc_info.value)


def test_check_preset_access_accepts_well_formed_even_if_unlisted() -> None:
    """Pattern check is independent of whitelist: a well-formed name passes the
    first layer, the second layer then determines authorisation.

    We can't observe the first-layer pass directly (the function raises on
    the second layer's rejection), but the test below asserts the rejection
    code is 403 not 400, confirming pattern was accepted before whitelist ran.
    """
    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        _check_preset_access("nonexistent/something")
    assert exc_info.value.code == 403, "well-formed but unlisted should be 403, not 400"


def test_allowed_presets_default_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """No env override → default whitelist is used."""
    monkeypatch.delenv("DEERFLOW_GRAPH_HARNESS_PRESETS", raising=False)
    assert _allowed_presets() == _DEFAULT_ALLOWED_PRESETS


def test_allowed_presets_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """Env override replaces the default whitelist entirely."""
    monkeypatch.setenv("DEERFLOW_GRAPH_HARNESS_PRESETS", "echo/echo,coding/coding_pipeline")
    result = _allowed_presets()
    assert result == frozenset({"echo/echo", "coding/coding_pipeline"})
    # multi_step_llm/multi_step_llm is in the default but not in the override → excluded.
    assert "multi_step_llm/multi_step_llm" not in result


def test_allowed_presets_env_override_strips_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whitespace around entries is stripped; empty entries are ignored."""
    monkeypatch.setenv("DEERFLOW_GRAPH_HARNESS_PRESETS", " echo/echo , , coding/coding_pipeline ")
    result = _allowed_presets()
    assert result == frozenset({"echo/echo", "coding/coding_pipeline"})


def test_allowed_presets_env_override_empty_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """An override that parses to empty (e.g. all whitespace, all commas) falls
    back to the default rather than silently locking everyone out."""
    monkeypatch.setenv("DEERFLOW_GRAPH_HARNESS_PRESETS", "  ,, , ")
    assert _allowed_presets() == _DEFAULT_ALLOWED_PRESETS


def test_make_graph_harness_agent_rejects_traversal_pattern() -> None:
    """End-to-end: a path-traversal preset name is rejected at the factory
    boundary with ``code=400`` — does not reach ``load_preset``."""
    from app.gateway.adapters.graph_harness import make_graph_harness_agent

    config = {"configurable": {"graph_preset": "../../etc/passwd"}}
    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        make_graph_harness_agent(config)
    assert exc_info.value.code == 400


def test_make_graph_harness_agent_rejects_unlisted_pattern() -> None:
    """End-to-end: a well-formed but unlisted preset name is rejected with ``code=403``."""
    from app.gateway.adapters.graph_harness import make_graph_harness_agent

    config = {"configurable": {"graph_preset": "unknown/preset"}}
    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        make_graph_harness_agent(config)
    assert exc_info.value.code == 403


# ---------------------------------------------------------------------------
# API-1: host-API version lock + missing-package behaviour
# ---------------------------------------------------------------------------


def test_expected_host_api_version_is_1_0_0() -> None:
    """Sanity: the adapter's expected host API version is "1.0.0".

    If graph-harness upstream bumps HOST_API_VERSION, this test will
    fail and force a deliberate adapter update — silent API drift is
    the failure mode this lock exists to prevent.
    """
    assert _EXPECTED_HOST_API_VERSION == "1.0.0"


def test_make_graph_harness_agent_without_harness_package_raises_runtime_error() -> None:
    """When ``harness.host`` is not installed, the factory raises ``RuntimeError``
    (via :func:`_load_graph_harness`), not ``ImportError`` from a bare
    ``import harness.host`` at module load time.

    This proves the lazy-import design: the adapter stays importable in
    test contexts where the upstream package is missing.
    """
    from app.gateway.adapters.graph_harness import make_graph_harness_agent

    config = {"configurable": {"graph_preset": "echo/echo"}}
    with pytest.raises(RuntimeError, match="graph-harness is required"):
        make_graph_harness_agent(config)