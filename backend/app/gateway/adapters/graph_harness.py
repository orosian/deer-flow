"""Adapter that routes graph-harness (``gh:``) presets through DeerFlow's gateway.

When a request carries an ``assistant_id`` with the ``gh:`` prefix
(e.g. ``gh:echo``, ``gh:multi-step-llm``), :func:`app.gateway.services.resolve_agent_factory`
returns :func:`make_graph_harness_agent`, which compiles the named preset from
the external ``graph-harness`` library and returns a thin proxy exposing
``ainvoke`` / ``astream``.  The proxy delegates straight to the compiled
LangGraph workflow so DeerFlow's existing ``RunManager`` + ``MemoryStreamBridge``
+ ``sse_consumer`` plumbing (checkpointer, interrupts, SSE framing) is reused
without modification.

The ``harness.host`` import is deferred to runtime so this module is always
importable — even when the graph-harness package is not installed (e.g. for
unit tests of :func:`is_graph_harness_assistant` and the gateway routing).

Security (SEC-1, v2-integration roadmap):
    Three layers of defence, applied before any graph-harness call touches the
    file system. The graph-harness library has its own path-validation
    (H1 commit ``ea9943f``); these checks add belt-and-suspenders access
    control on the DeerFlow side so untrusted preset names cannot reach the
    engine regardless of any library regression.

    1. Pattern check (``^[a-z0-9_-]+(/[a-z0-9_-]+)?$``) — rejects path
       traversal, backslashes, uppercase, and absolute paths. Maps to 400.
    2. Whitelist check — only preset names explicitly listed (or matching an
       env override) are accepted. Maps to 403.
    3. ``load_preset`` failure (e.g. file not found) is re-raised as a
       distinguishable ``GraphHarnessPresetAccessError`` with ``code=404``
       (vs. ``500`` for unknown errors). The gateway layer is expected to
       translate ``code`` into ``fastapi.HTTPException``.
"""

from __future__ import annotations

import os
import re
import threading
import time
from typing import Any

_GRAPH_HARNESS_PREFIX = "gh:"

# SEC-1: preset-name pattern mirrors graph-harness H1 library check
# (``src/harness/workflows/presets/__init__.py``). Keep in sync if that
# pattern is relaxed upstream; the adapter is intentionally stricter on the
# input side.
_PRESET_NAME_PATTERN = re.compile(r"^[a-z0-9_-]+(/[a-z0-9_-]+)?$")

# SEC-1: default whitelist of presets accessible via ``gh:*`` assistants.
# Override at runtime by setting the ``DEERFLOW_GRAPH_HARNESS_PRESETS``
# environment variable to a comma-separated list (e.g.
# ``"echo/echo,coding/coding_pipeline"``).
_DEFAULT_ALLOWED_PRESETS: frozenset[str] = frozenset(
    {
        "echo/echo",
        "multi_step_llm/multi_step_llm",
        "coding/coding_pipeline",
    }
)


def _allowed_presets() -> frozenset[str]:
    """Return the active whitelist, honouring the ``DEERFLOW_GRAPH_HARNESS_PRESETS`` override.

    An empty or unset environment variable falls back to the built-in default.
    The override accepts a comma-separated list of preset names; whitespace
    around each entry is stripped. An invalid override (no entries after
    parsing) falls back to the default rather than silently locking everyone
    out — this matches the principle of "fail loud, not silent".
    """
    override = os.environ.get("DEERFLOW_GRAPH_HARNESS_PRESETS", "").strip()
    if not override:
        return _DEFAULT_ALLOWED_PRESETS
    parsed = frozenset(entry.strip() for entry in override.split(",") if entry.strip())
    return parsed if parsed else _DEFAULT_ALLOWED_PRESETS


class GraphHarnessPresetAccessError(Exception):
    """Raised when a preset name is rejected by the DeerFlow-side access control.

    The ``code`` attribute maps to an HTTP status: ``400`` (pattern mismatch),
    ``403`` (not in whitelist), ``404`` (preset not found by the engine), or
    ``500`` (unknown). The gateway layer is expected to translate ``code``
    into ``fastapi.HTTPException(code, detail=str(error))`` — this adapter
    intentionally does not import ``fastapi`` so it stays usable from
    non-HTTP contexts (CLI, tests).
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def is_graph_harness_assistant(assistant_id: str | None) -> bool:
    """Return True if ``assistant_id`` designates a graph-harness preset (i.e. ``gh:...``)."""
    return bool(assistant_id) and assistant_id.startswith(_GRAPH_HARNESS_PREFIX)


def _check_preset_access(preset_name: str) -> None:
    """Apply SEC-1 two-layer access control. Raise ``GraphHarnessPresetAccessError`` on failure.

    Order matters:
    1. Pattern check first — cheap, deterministic, and prevents path-traversal
       payloads from reaching the whitelist lookup (where they could match
       if a future operator sets a malformed override).
    2. Whitelist second — explicit authorisation against the configured set.
    3. The library's own validation runs later inside ``load_preset``; that
       failure surfaces as ``404`` via :func:`_wrap_load_preset_errors`.

    MON-1: increments ``preset_load_failure_total{reason}`` on every
    rejection so the gateway can surface the rejection category in metrics.
    """
    if not isinstance(preset_name, str) or not _PRESET_NAME_PATTERN.match(preset_name):
        _METRICS.incr_preset_load_failure("pattern")
        raise GraphHarnessPresetAccessError(
            400,
            f"invalid preset name format: {preset_name!r}",
        )
    if preset_name not in _allowed_presets():
        _METRICS.incr_preset_load_failure("not_allowed")
        raise GraphHarnessPresetAccessError(
            403,
            f"preset not in allow-list: {preset_name!r}",
        )


# API-1: host-API version that this adapter has been tested against. The
# graph-harness library exposes ``harness.host.HOST_API_VERSION`` for hosts
# to lock against; we re-export the expected version here so a mismatch is
# caught at the first call into the engine rather than as a cryptic
# runtime failure later. Bump this in lockstep with the upstream value.
_EXPECTED_HOST_API_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# MON-1: lightweight metrics accumulator
# ---------------------------------------------------------------------------
#
# DeerFlow has no Prometheus client today, so we keep an in-process counter
# / histogram store and expose it via :func:`snapshot_metrics`. A future
# host-side exporter (Prometheus / OpenTelemetry / StatsD) can pull from
# this snapshot without the adapter importing the exporter library —
# preserving the "no new dependency" property of the adapter layer.
#
# Counter keys use Prometheus naming convention (snake_case + ``_total``
# suffix for monotonic counters) so a downstream exporter can map them
# directly without translation.


class _MetricsAccumulator:
    """Thread-safe in-process metrics store.

    Holds four counters (one with a ``reason`` label) and a histogram
    (list of observations + derived count/sum/max). All mutations are
    guarded by ``_lock`` so concurrent runs do not corrupt the counters.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.bridge_overflow_total = 0
        self.sse_frame_missing_end_total = 0
        self.preset_load_failure_total: dict[str, int] = {
            "pattern": 0,
            "not_allowed": 0,
            "not_found": 0,
            "unknown": 0,
        }
        self.run_duration_seconds_count = 0
        self.run_duration_seconds_sum = 0.0
        self.run_duration_seconds_max = 0.0
        self.run_duration_seconds_buckets: dict[float, int] = {
            0.1: 0,
            0.5: 0,
            1.0: 0,
            2.0: 0,
            5.0: 0,
            10.0: 0,
            30.0: 0,
            60.0: 0,
            300.0: 0,
        }

    def incr_bridge_overflow(self) -> None:
        with self._lock:
            self.bridge_overflow_total += 1

    def incr_sse_frame_missing_end(self) -> None:
        with self._lock:
            self.sse_frame_missing_end_total += 1

    def incr_preset_load_failure(self, reason: str) -> None:
        with self._lock:
            self.preset_load_failure_total[reason] = self.preset_load_failure_total.get(reason, 0) + 1

    def observe_run_duration(self, seconds: float) -> None:
        with self._lock:
            self.run_duration_seconds_count += 1
            self.run_duration_seconds_sum += seconds
            if seconds > self.run_duration_seconds_max:
                self.run_duration_seconds_max = seconds
            for upper_bound in sorted(self.run_duration_seconds_buckets):
                if seconds <= upper_bound:
                    self.run_duration_seconds_buckets[upper_bound] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "bridge_overflow_total": self.bridge_overflow_total,
                "sse_frame_missing_end_total": self.sse_frame_missing_end_total,
                "preset_load_failure_total": dict(self.preset_load_failure_total),
                "run_duration_seconds": {
                    "count": self.run_duration_seconds_count,
                    "sum": self.run_duration_seconds_sum,
                    "max": self.run_duration_seconds_max,
                    "buckets": dict(self.run_duration_seconds_buckets),
                },
            }

    def reset(self) -> None:
        with self._lock:
            self.__init__()


_METRICS = _MetricsAccumulator()


def snapshot_metrics() -> dict:
    """Return a point-in-time snapshot of the adapter metrics (MON-1).

    The shape is Prometheus-friendly: counters end in ``_total``, and the
    histogram follows the standard ``count/sum/max/buckets`` layout. A
    future host-side exporter can map this directly to a Prometheus
    scrape without translating field names.
    """
    return _METRICS.snapshot()


def reset_metrics() -> None:
    """Reset all metric counters to zero. Intended for tests."""
    _METRICS.reset()


def _load_graph_harness():
    """Lazy import of ``harness.host`` so this module is importable without the package installed.

    API-1: also asserts that ``harness.host.HOST_API_VERSION`` matches the
    version this adapter was built against. A mismatch raises ImportError so
    the gateway returns 500 with a clear "host API version mismatch" cause
    instead of silently invoking a workflow with an incompatible signature.
    """
    try:
        from harness.host import HOST_API_VERSION, compile_workflow, load_preset  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "graph-harness is required for gh:* assistants but is not installed (missing 'harness.host')"
        ) from exc
    if HOST_API_VERSION != _EXPECTED_HOST_API_VERSION:
        raise ImportError(
            f"graph-harness host API version mismatch: installed={HOST_API_VERSION!r}, "
            f"expected={_EXPECTED_HOST_API_VERSION!r}. Upgrade the adapter or downgrade "
            f"the graph-harness package to a compatible version."
        )
    return compile_workflow, load_preset


def _wrap_load_preset_errors(preset_name: str):
    """Call ``load_preset`` and translate its library exceptions into SEC-1 access errors.

    The graph-harness library raises ``ValueError`` for both "pattern
    violation" (already caught upstream) and "file not found". At this point
    the name has already passed our checks, so a library ``ValueError`` is
    almost certainly a 404 (preset not registered in the engine's preset
    directory). Mapping it explicitly lets the gateway distinguish a missing
    preset (user error, 404) from an unknown engine failure (500).

    MON-1: increments ``preset_load_failure_total{reason="not_found"}`` on
    the ValueError path; unknown errors use ``reason="unknown"``.
    """
    _compile_workflow, load_preset = _load_graph_harness()

    def wrapped():
        try:
            return load_preset(preset_name)
        except ValueError as exc:
            _METRICS.incr_preset_load_failure("not_found")
            raise GraphHarnessPresetAccessError(404, f"preset not found: {preset_name!r}") from exc
        except Exception:
            _METRICS.incr_preset_load_failure("unknown")
            raise

    return wrapped()


class _GraphHarnessCompiledProxy:
    """Thin wrapper around a compiled graph-harness workflow.

    Delegates ``ainvoke`` / ``astream`` straight to the compiled LangGraph
    graph so DeerFlow's upstream runtime (checkpointer, interrupts, SSE) is
    reused unchanged.

    MON-1: ``astream`` wraps the upstream async iterator to observe
    ``BufferError`` (bridge overflow when the upstream queue is full) and
    to detect runs that completed without yielding an end frame. Both
    ``ainvoke`` and ``astream`` feed the ``run_duration_seconds`` histogram.
    """

    # Sentinel keys observed inside an astream chunk that indicate the
    # run has finished. The graph-harness bridge emits one of these as
    # the last frame; if neither appears before the iterator ends, we
    # count a missing-end event. Exposed at class level for tests.
    _STREAM_END_MARKERS = ("end", "__end__")

    def __init__(self, compiled: Any, preset_name: str) -> None:
        self._compiled = compiled
        self._preset = preset_name

    async def ainvoke(self, input: Any, config: Any):
        start = time.perf_counter()
        try:
            return await self._compiled.ainvoke(input, config)
        finally:
            _METRICS.observe_run_duration(time.perf_counter() - start)

    async def astream(self, input: Any, config: Any, stream_mode: Any = None):
        start = time.perf_counter()
        if stream_mode is None:
            stream_mode = ["values"]
        saw_end = False
        try:
            try:
                async for chunk in self._compiled.astream(input, config, stream_mode=stream_mode):
                    if isinstance(chunk, dict):
                        event = chunk.get("event")
                        if event in self._STREAM_END_MARKERS:
                            saw_end = True
                    yield chunk
            except BufferError:
                # asyncio.Queue.put_nowait on the bridge raised because the
                # consumer is too slow. Count and re-raise so the upstream
                # SSE layer can surface the failure to the client.
                _METRICS.incr_bridge_overflow()
                raise
        finally:
            if not saw_end:
                _METRICS.incr_sse_frame_missing_end()
            _METRICS.observe_run_duration(time.perf_counter() - start)


def make_graph_harness_agent(config: Any, app_config: Any = None):
    """Compile a graph-harness preset named by ``config['configurable']['graph_preset']``.

    Returns a proxy whose ``ainvoke`` / ``astream`` methods delegate to the
    underlying compiled workflow.  ``start_run`` is responsible for lifting
    ``body.input['graph_preset']`` into ``config['configurable']['graph_preset']``
    before this factory is called.

    Raises ``GraphHarnessPresetAccessError`` (with ``code`` set to 400/403/404)
    when SEC-1 access control rejects the preset name. The gateway layer is
    expected to translate the ``code`` attribute into the corresponding
    ``fastapi.HTTPException``.
    """
    configurable = (config or {}).get("configurable") or {}
    preset_name = configurable.get("graph_preset")
    if not preset_name:
        raise ValueError(
            "graph-harness assistant requires 'graph_preset' in config['configurable']"
        )
    # SEC-1: pattern + whitelist. Must run before any file system call.
    _check_preset_access(preset_name)
    # SEC-1: 404 mapping for missing presets via the engine's own validation.
    dsl = _wrap_load_preset_errors(preset_name)
    compile_workflow, _ = _load_graph_harness()
    compiled = compile_workflow(dsl)
    return _GraphHarnessCompiledProxy(compiled, preset_name)