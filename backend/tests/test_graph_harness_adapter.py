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
    _METRICS,
    _MIN_HOST_API_MAJOR,
    GraphHarnessPresetAccessError,
    _allowed_presets,
    check_preset_access,
    reset_metrics,
    snapshot_metrics,
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
        check_preset_access(preset)  # should not raise


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
        check_preset_access(bad_name)
    assert exc_info.value.code == 400
    assert "invalid preset name format" in str(exc_info.value)


def test_check_preset_access_rejects_non_whitelisted() -> None:
    """A syntactically valid name that is not on the whitelist raises ``code=403``."""
    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        check_preset_access("unlisted/preset")
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
        check_preset_access("nonexistent/something")
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


def test_min_host_api_major_is_1_0_0() -> None:
    """Sanity: the adapter's minimum host-API major is "1.0.0".

    graph-harness upstream bumped HOST_API_VERSION from "1.0.0" to
    "1.1.0" — same major, still compatible via
    ``check_host_api_compatible``. If a future bump crosses into 2.x,
    this test will fail and force a deliberate adapter update — silent
    major-version drift is the failure mode this lock exists to
    prevent.
    """
    assert _MIN_HOST_API_MAJOR == "1.0.0"


def test_make_graph_harness_agent_passes_preset_produces_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """The adapter must thread ``manifest['produces_keys']`` through to
    ``compile_workflow`` as the ``preset_produces_keys`` keyword. Without
    this, action-level presets (e.g. ``echo``, ``multi_step_llm``) trigger
    a spurious ``DATAFLOW_PATH_INPUT_MISSING`` from the validator.
    """
    import sys
    import types

    fake = types.ModuleType("harness")
    host = types.ModuleType("harness.host")

    # A minimal valid manifest with produces_keys declared.
    sentinel_compiled = object()
    captured_kwargs: dict = {}

    def fake_load_preset(_name: str):
        return {"preset_name": "echo", "produces_keys": ["branch.key", "branch.operator"], "graph": {}}

    def fake_compile_workflow(_dsl, **kwargs):
        captured_kwargs.update(kwargs)
        return sentinel_compiled

    def fake_check_compatible(_expected: str) -> None:
        return None

    host.load_preset = fake_load_preset
    host.compile_workflow = fake_compile_workflow
    host.check_host_api_compatible = fake_check_compatible
    host.HostApiVersionMismatch = type("HostApiVersionMismatch", (Exception,), {})
    fake.host = host
    monkeypatch.setitem(sys.modules, "harness", fake)
    monkeypatch.setitem(sys.modules, "harness.host", host)

    from app.gateway.adapters.graph_harness import make_graph_harness_agent

    proxy = make_graph_harness_agent({"configurable": {"graph_preset": "echo/echo"}})
    assert captured_kwargs.get("preset_produces_keys") == {"branch.key", "branch.operator"}
    # Sanity: returned proxy wraps the sentinel.
    assert proxy._compiled is sentinel_compiled


def test_make_graph_harness_agent_handles_missing_produces_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Manifests without ``produces_keys`` (older presets, custom DSLs)
    must still compile — the adapter passes an empty set so the validator
    uses its default ``{user.goal}`` initial_keys.
    """
    import sys
    import types

    fake = types.ModuleType("harness")
    host = types.ModuleType("harness.host")

    sentinel_compiled = object()
    captured_kwargs: dict = {}

    def fake_load_preset(_name: str):
        # Old-style manifest without produces_keys field.
        return {"preset_name": "old", "graph": {}}

    def fake_compile_workflow(_dsl, **kwargs):
        captured_kwargs.update(kwargs)
        return sentinel_compiled

    def fake_check_compatible(_expected: str) -> None:
        return None

    host.load_preset = fake_load_preset
    host.compile_workflow = fake_compile_workflow
    host.check_host_api_compatible = fake_check_compatible
    host.HostApiVersionMismatch = type("HostApiVersionMismatch", (Exception,), {})
    fake.host = host
    monkeypatch.setitem(sys.modules, "harness", fake)
    monkeypatch.setitem(sys.modules, "harness.host", host)

    from app.gateway.adapters.graph_harness import make_graph_harness_agent

    make_graph_harness_agent({"configurable": {"graph_preset": "echo/echo"}})
    assert captured_kwargs.get("preset_produces_keys") == set()


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


# ---------------------------------------------------------------------------
# MON-1: metrics accumulator
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_metrics_between_tests():
    """Ensure metric state from one test does not bleed into the next."""
    reset_metrics()
    yield
    reset_metrics()


def test_snapshot_metrics_shape_matches_prometheus() -> None:
    """The snapshot exposes all four MON-1 counters and the run_duration histogram
    with Prometheus-friendly naming (counters end in ``_total``)."""
    snap = snapshot_metrics()
    assert snap["bridge_overflow_total"] == 0
    assert snap["sse_frame_missing_end_total"] == 0
    assert snap["preset_load_failure_total"] == {
        "pattern": 0,
        "not_allowed": 0,
        "not_found": 0,
        "unknown": 0,
    }
    histogram = snap["run_duration_seconds"]
    assert histogram["count"] == 0
    assert histogram["sum"] == 0.0
    assert histogram["max"] == 0.0
    # Buckets match the prometheus_histogram layout from the v2 plan.
    assert set(histogram["buckets"]) == {0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 300.0}


def test_preset_load_failure_pattern_counter_increments() -> None:
    """Each ``check_preset_access`` pattern rejection increments
    ``preset_load_failure_total{reason="pattern"}``."""
    with pytest.raises(GraphHarnessPresetAccessError):
        check_preset_access("../../etc/passwd")
    with pytest.raises(GraphHarnessPresetAccessError):
        check_preset_access("/abs/path")
    assert _METRICS.preset_load_failure_total["pattern"] == 2


def test_preset_load_failure_not_allowed_counter_increments() -> None:
    """Well-formed but unlisted preset names bump the ``not_allowed`` counter."""
    with pytest.raises(GraphHarnessPresetAccessError):
        check_preset_access("unlisted/preset")
    assert _METRICS.preset_load_failure_total["not_allowed"] == 1


def test_preset_load_failure_unknown_counter_on_load_exception(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-ValueError exceptions from ``load_preset`` are counted as ``unknown`` and rewrapped as ``GraphHarnessPresetAccessError(code=500)`` with the original exception preserved on ``__cause__`` (P1-5)."""
    # Stub harness.host so the adapter can import it for this test.
    import sys
    import types

    fake = types.ModuleType("harness")
    host = types.ModuleType("harness.host")

    def fake_load_preset(_name: str):
        raise RuntimeError("disk on fire")

    def fake_compile_workflow(_dsl: dict):
        return object()

    host.load_preset = fake_load_preset
    host.compile_workflow = fake_compile_workflow

    def fake_check_compatible(_expected: str) -> None:
        return None  # default: accept

    host.check_host_api_compatible = fake_check_compatible
    host.HostApiVersionMismatch = type("HostApiVersionMismatch", (Exception,), {})
    fake.host = host
    monkeypatch.setitem(sys.modules, "harness", fake)
    monkeypatch.setitem(sys.modules, "harness.host", host)

    from app.gateway.adapters.graph_harness import GraphHarnessPresetAccessError, make_graph_harness_agent

    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        make_graph_harness_agent({"configurable": {"graph_preset": "echo/echo"}})
    assert exc_info.value.code == 500
    # P1-5: the original RuntimeError must be chained on __cause__ so
    # log consumers and observability hooks see the actual failure cause
    # instead of a bare ``None``/unknown.
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "disk on fire" in str(exc_info.value.__cause__)
    assert _METRICS.preset_load_failure_total["unknown"] == 1


def test_preset_load_failure_not_found_counter_on_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ValueError from ``load_preset`` (preset file missing) is counted as ``not_found``."""
    import sys
    import types

    fake = types.ModuleType("harness")
    host = types.ModuleType("harness.host")

    def fake_load_preset(_name: str):
        raise ValueError("preset not registered")

    def fake_compile_workflow(_dsl: dict):
        return object()

    host.load_preset = fake_load_preset
    host.compile_workflow = fake_compile_workflow

    def fake_check_compatible(_expected: str) -> None:
        return None  # default: accept

    host.check_host_api_compatible = fake_check_compatible
    host.HostApiVersionMismatch = type("HostApiVersionMismatch", (Exception,), {})
    fake.host = host
    monkeypatch.setitem(sys.modules, "harness", fake)
    monkeypatch.setitem(sys.modules, "harness.host", host)

    from app.gateway.adapters.graph_harness import GraphHarnessPresetAccessError, make_graph_harness_agent

    with pytest.raises(GraphHarnessPresetAccessError) as exc_info:
        make_graph_harness_agent({"configurable": {"graph_preset": "echo/echo"}})
    assert exc_info.value.code == 404
    assert _METRICS.preset_load_failure_total["not_found"] == 1


def test_bridge_overflow_counter_increments_on_buffer_error() -> None:
    """An async iterator raising ``BufferError`` increments
    ``bridge_overflow_total`` and re-raises so the upstream can surface it."""

    async def fake_astream(*_args, **_kwargs):
        raise BufferError("queue full")
        yield  # unreachable; makes this an async generator

    class _FakeCompiled:
        astream = fake_astream

    from app.gateway.adapters.graph_harness import _GraphHarnessCompiledProxy

    proxy = _GraphHarnessCompiledProxy(_FakeCompiled(), "echo/echo")

    async def _drain():
        async for _ in proxy.astream({}, {}):
            pass

    import asyncio

    with pytest.raises(BufferError):
        asyncio.run(_drain())
    assert _METRICS.bridge_overflow_total == 1


def test_p1_3_buffer_error_does_not_double_count_missing_end() -> None:
    """P1-3: a ``BufferError`` on the bridge must increment only
    ``bridge_overflow_total``, not also ``sse_frame_missing_end_total``.

    Before the fix, the ``finally`` clause fired unconditionally on any
    non-end-bearing stream, so a single bridge overflow was double-counted
    as both observations. This test pins down the corrected behaviour:
    the missing-end counter stays at zero on the exception path.
    """

    async def fake_astream(*_args, **_kwargs):
        # Yield one non-end frame, then raise BufferError before the end
        # marker ever appears. Pre-fix this would have bumped both counters.
        yield {"event": "values", "data": {"foo": "bar"}}
        raise BufferError("queue full")

    class _FakeCompiled:
        astream = fake_astream

    from app.gateway.adapters.graph_harness import _GraphHarnessCompiledProxy

    proxy = _GraphHarnessCompiledProxy(_FakeCompiled(), "echo/echo")

    async def _drain():
        async for _ in proxy.astream({}, {}):
            pass

    import asyncio

    with pytest.raises(BufferError):
        asyncio.run(_drain())
    # Bridge overflow IS counted (single observation of one event).
    assert _METRICS.bridge_overflow_total == 1
    # Missing-end counter must NOT increment on the exception path —
    # the failure is already accounted for via bridge_overflow_total.
    assert _METRICS.sse_frame_missing_end_total == 0


def test_p1_3_other_exception_does_not_count_missing_end() -> None:
    """P1-3: any exception path (not just ``BufferError``) must not
    increment ``sse_frame_missing_end_total``. The missing-end signal is
    only meaningful when the stream ran to completion normally.
    """

    async def fake_astream(*_args, **_kwargs):
        yield {"event": "values", "data": {}}
        raise RuntimeError("bridge exploded for unrelated reasons")

    class _FakeCompiled:
        astream = fake_astream

    from app.gateway.adapters.graph_harness import _GraphHarnessCompiledProxy

    proxy = _GraphHarnessCompiledProxy(_FakeCompiled(), "echo/echo")

    async def _drain():
        async for _ in proxy.astream({}, {}):
            pass

    import asyncio

    with pytest.raises(RuntimeError):
        asyncio.run(_drain())
    assert _METRICS.bridge_overflow_total == 0
    assert _METRICS.sse_frame_missing_end_total == 0


def test_sse_frame_missing_end_counter_unchanged_on_normal_completion() -> None:
    """P1-4 regression: a stream that completes cleanly (no in-band end marker,
    because LangGraph ``values`` mode does not emit one) does NOT increment
    ``sse_frame_missing_end_total``.

    Before P1-4 the predicate ``chunk['event'] in _STREAM_END_MARKERS`` was
    checked against LangGraph values-mode chunks (plain state dicts with no
    ``\"event\"`` key), so the counter incremented on 100% of successful runs.
    The corrected behaviour: ``sse_frame_missing_end_total`` is a no-op in
    practice (see the P1-4 docstring in ``_GraphHarnessCompiledProxy``); the
    counter stays at 0 on normal completion.
    """

    async def fake_astream(*_args, **_kwargs):
        # Real LangGraph values-mode chunk: plain state dict, no "event" key.
        yield {"messages": ["hello"], "user_goal": "summarise"}
        # Stream ends via clean StopAsyncIteration (no in-band end marker).

    class _FakeCompiled:
        astream = fake_astream

    from app.gateway.adapters.graph_harness import _GraphHarnessCompiledProxy

    proxy = _GraphHarnessCompiledProxy(_FakeCompiled(), "echo/echo")

    async def _drain():
        async for _ in proxy.astream({}, {}):
            pass

    import asyncio

    asyncio.run(_drain())
    assert _METRICS.sse_frame_missing_end_total == 0


def test_sse_frame_missing_end_counter_unchanged_when_end_marker_seen() -> None:
    """Defence-in-depth coverage: even if a future stream mode emits an
    in-band end marker (``event in (\"end\", \"__end__\")``), the counter still
    does not increment (P1-4 keeps the counter as a no-op for stability).
    """

    async def fake_astream(*_args, **_kwargs):
        yield {"event": "values", "data": {}}
        yield {"event": "end"}

    class _FakeCompiled:
        astream = fake_astream

    from app.gateway.adapters.graph_harness import _GraphHarnessCompiledProxy

    proxy = _GraphHarnessCompiledProxy(_FakeCompiled(), "echo/echo")

    async def _drain():
        async for _ in proxy.astream({}, {}):
            pass

    import asyncio

    asyncio.run(_drain())
    assert _METRICS.sse_frame_missing_end_total == 0


def test_run_duration_histogram_records_observation() -> None:
    """``ainvoke`` records an observation in the histogram (count increments, sum > 0)."""

    class _FakeCompiled:
        async def ainvoke(self, _input, _config):
            import asyncio

            await asyncio.sleep(0.01)
            return {"ok": True}

    from app.gateway.adapters.graph_harness import _GraphHarnessCompiledProxy

    proxy = _GraphHarnessCompiledProxy(_FakeCompiled(), "echo/echo")

    async def _run():
        await proxy.ainvoke({}, {})

    import asyncio

    asyncio.run(_run())
    snap = snapshot_metrics()
    assert snap["run_duration_seconds"]["count"] == 1
    assert snap["run_duration_seconds"]["sum"] > 0.0
    # 0.01s lands in the 0.1 bucket.
    assert snap["run_duration_seconds"]["buckets"][0.1] == 1


# ---------------------------------------------------------------------------
# P1-1: closed-set validation for preset_load_failure reason labels
# ---------------------------------------------------------------------------


def test_p1_1_incr_preset_load_failure_rejects_unknown_reason() -> None:
    """P1-1: passing a ``reason`` label outside the closed set raises ``ValueError``
    instead of silently mutating the counter dict (which would create a 5th
    key in the snapshot that dashboards do not know how to interpret).

    The error message must name the offending label and list the known
    reasons so a future maintainer can extend the constant deliberately
    rather than guessing what values are accepted.
    """
    from app.gateway.adapters.graph_harness import (
        _KNOWN_PRESET_FAILURE_REASONS,
        _MetricsAccumulator,
    )

    acc = _MetricsAccumulator()
    with pytest.raises(ValueError) as exc_info:
        acc.incr_preset_load_failure("quota_exceeded")
    msg = str(exc_info.value)
    assert "quota_exceeded" in msg
    # All known reasons must be listed in the error message.
    for known in _KNOWN_PRESET_FAILURE_REASONS:
        assert known in msg, f"known reason {known!r} should appear in error message"
    # Internal counter dict is not polluted by the rejected call.
    assert "quota_exceeded" not in acc.preset_load_failure_total


def test_p1_1_incr_preset_load_failure_accepts_all_known_reasons() -> None:
    """P1-1: every entry in ``_KNOWN_PRESET_FAILURE_REASONS`` is accepted (no
    regression on the four legitimate labels)."""
    from app.gateway.adapters.graph_harness import _MetricsAccumulator

    acc = _MetricsAccumulator()
    for reason in ("pattern", "not_allowed", "not_found", "unknown"):
        acc.incr_preset_load_failure(reason)
    # Each reason incremented exactly once.
    assert all(acc.preset_load_failure_total[r] == 1 for r in ("pattern", "not_allowed", "not_found", "unknown"))


# ---------------------------------------------------------------------------
# P1-2: env-override entries are validated against _PRESET_NAME_PATTERN
# ---------------------------------------------------------------------------


def test_p1_2_env_override_drops_invalid_keeps_valid(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P1-2: a mixed override (``echo/echo,BadPattern``) drops the invalid
    entries and keeps the well-formed ones, with a warning naming both.

    Before the fix, ``BadPattern`` (uppercase) would have been loaded into
    the active whitelist silently and then rejected with a 400 on every
    request — confusing operators because the env value was accepted at
    parse time but unusable at runtime.
    """
    import logging

    from app.gateway.adapters import graph_harness

    monkeypatch.setenv(
        "DEERFLOW_GRAPH_HARNESS_PRESETS",
        "echo/echo,BadPattern",
    )
    with caplog.at_level(logging.WARNING, logger=graph_harness.__name__):
        result = _allowed_presets()
    assert result == frozenset({"echo/echo"})
    # Warning must name the dropped entries.
    warning_text = " ".join(record.getMessage() for record in caplog.records)
    assert "BadPattern" in warning_text
    assert "echo/echo" in warning_text


def test_p1_2_env_override_all_invalid_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """P1-2: when *every* override entry fails ``_PRESET_NAME_PATTERN`` the
    override is rejected wholesale and the default whitelist is used.

    A wholesale rejection is preferable to silently installing an empty
    whitelist (which would 403 every request) — operators get a clear
    warning instead of a runtime lockout.
    """
    import logging

    from app.gateway.adapters import graph_harness

    monkeypatch.setenv(
        "DEERFLOW_GRAPH_HARNESS_PRESETS",
        "BadPattern,../etc/passwd",
    )
    with caplog.at_level(logging.WARNING, logger=graph_harness.__name__):
        result = _allowed_presets()
    assert result == _DEFAULT_ALLOWED_PRESETS
    # Warning must mention the all-invalid condition.
    warning_text = " ".join(record.getMessage() for record in caplog.records)
    assert "falling back to default" in warning_text
    assert "BadPattern" in warning_text
    assert "../etc/passwd" in warning_text
