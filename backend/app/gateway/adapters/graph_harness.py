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

Integration contract (review finding P0-1, SEC-1 contract gap):
    The adapter does *everything* it can on its own side — pattern check,
    whitelist check, and ``load_preset``-failure mapping — but the final
    translation of ``GraphHarnessPresetAccessError.code`` into an HTTP
    status is the **gateway layer's responsibility**, not this adapter's.

    The known gap (as of the v2-integration codebase): if the gateway
    defers ``agent_factory`` invocation into a background task (i.e.
    ``resolve_agent_factory`` in ``app.gateway.services`` only returns the
    callable, and the actual call happens inside
    ``asyncio.create_task(run_agent(...))``), then by the time the access-
    control error raises inside ``make_graph_harness_agent`` the HTTP
    handler has already returned ``200 OK`` plus a ``thread_id``. The
    client therefore observes a successful run-start followed by a
    disconnect / never-arriving stream — not a 4xx.

    Two ways to close the gap (gateway-side, not adapter-side):

    * **Surface via SSE error frame.** Catch the
      ``GraphHarnessPresetAccessError`` raised inside the background task
      and emit an SSE ``error`` frame carrying ``code`` + ``detail`` so the
      client can distinguish a 400/403/404 from a real run error.
      ``GraphHarnessPresetAccessError.code`` is exported as a public
      attribute specifically so this translation is straightforward.
    * **Pre-validate in the HTTP handler.** Call
      ``check_preset_access(preset_name)`` (or
      ``is_graph_harness_assistant`` + an explicit access check) in the
      request handler *before* scheduling ``run_agent``, so a rejected
      preset name raises synchronously and can be translated to a real
      ``fastapi.HTTPException`` with the right status code.

    The adapter cannot fix this without changes to ``services.py`` or
    ``run_agent``, which would violate the "no-invasive DeerFlow
    changes" rule — the contract gap is documented here so future
    DeerFlow integrators know the adapter has done its part.
"""

from __future__ import annotations

import logging
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

# MON-1 + P1-1: closed set of ``reason`` labels for
# ``preset_load_failure_total``. Defining it as a module-level frozenset
# (1) gives :func:`incr_preset_load_failure` a single source of truth to
# validate against — any new label must be added here *and* the
# accumulator's ``__init__`` defaults updated in lockstep, otherwise the
# caller gets a ``ValueError``; and (2) lets :func:`_MetricsAccumulator.snapshot`
# derive its dict literal from the constant instead of hard-coding four
# string keys (DRY). Dashboards expect exactly these four labels; an
# accidental fifth would silently shift the metric schema.
_KNOWN_PRESET_FAILURE_REASONS: frozenset[str] = frozenset({"pattern", "not_allowed", "not_found", "unknown"})

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

    P1-2: each parsed entry is also run through ``_PRESET_NAME_PATTERN``.
    Invalid entries (typos like ``"Echo/Echo"``, or stray values like
    ``"../etc/passwd"``) are dropped with a warning so the misconfiguration
    is visible at startup rather than surfacing as a confusing 400 on every
    request. If *all* entries fail the pattern check, the entire override
    is rejected and the default whitelist is used instead — operators who
    want a tighter trust boundary get an explicit warning instead of
    silent lockout.
    """
    override = os.environ.get("DEERFLOW_GRAPH_HARNESS_PRESETS", "").strip()
    if not override:
        return _DEFAULT_ALLOWED_PRESETS
    parsed = frozenset(entry.strip() for entry in override.split(",") if entry.strip())
    if not parsed:
        return _DEFAULT_ALLOWED_PRESETS
    valid = frozenset(entry for entry in parsed if _PRESET_NAME_PATTERN.match(entry))
    invalid = parsed - valid
    if invalid:
        logger = logging.getLogger(__name__)
        if valid:
            logger.warning(
                "DEERFLOW_GRAPH_HARNESS_PRESETS: dropping invalid entries %s (do not match _PRESET_NAME_PATTERN); keeping %s",
                sorted(invalid),
                sorted(valid),
            )
            return valid
        # All entries invalid: treat the override as wholly untrustworthy
        # and fall back to defaults rather than locking everyone out.
        logger.warning(
            "DEERFLOW_GRAPH_HARNESS_PRESETS: every entry %s failed _PRESET_NAME_PATTERN; falling back to default whitelist",
            sorted(invalid),
        )
        return _DEFAULT_ALLOWED_PRESETS
    return parsed


class GraphHarnessPresetAccessError(Exception):
    """Raised when a preset name is rejected by the DeerFlow-side access control.

    The ``code`` attribute maps to an HTTP status: ``400`` (pattern mismatch),
    ``403`` (not in whitelist), ``404`` (preset not found by the engine), or
    ``500`` (unknown). The gateway layer is expected to translate ``code``
    into ``fastapi.HTTPException(code, detail=str(error))`` — this adapter
    intentionally does not import ``fastapi`` so it stays usable from
    non-HTTP contexts (CLI, tests).

    Observability (review finding P0-1): this exception is *synchronously
    observable* when the gateway calls :func:`check_preset_access` (or
    :func:`make_graph_harness_agent`) on the HTTP request path itself, in
    which case the gateway can translate ``code`` into a real
    ``fastapi.HTTPException`` and the client sees a clean 4xx. It is
    *invisibly raised* when the gateway defers ``agent_factory`` invocation
    into an ``asyncio.create_task(...)`` background task — by the time the
    exception fires, the HTTP handler has already returned ``200 OK`` +
    ``thread_id`` and the error cannot reach the client as a status code.
    See the module-level "Integration contract" section for the two
    gateway-side remedies (SSE error frame, or pre-validate in the
    handler). The ``code`` attribute is exposed publicly specifically so
    the SSE-error-frame path can map it without re-parsing the message.
    """

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def is_graph_harness_assistant(assistant_id: str | None) -> bool:
    """Return True if ``assistant_id`` designates a graph-harness preset (i.e. ``gh:...``)."""
    return bool(assistant_id) and assistant_id.startswith(_GRAPH_HARNESS_PREFIX)


def check_preset_access(preset_name: str) -> None:
    """Apply SEC-1 two-layer access control. Raise ``GraphHarnessPresetAccessError`` on failure.

    Order matters:
    1. Pattern check first — cheap, deterministic, and prevents path-traversal
       payloads from reaching the whitelist lookup (where they could match
       if a future operator sets a malformed override).
    2. Whitelist second — explicit authorisation against the configured set.
    3. The library's own validation runs later inside ``load_preset``; that
       failure surfaces as ``404`` via :func:`wrap_load_preset_errors`.

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


# API-1: minimum host-API MAJOR this adapter has been tested against.
# graph-harness exposes ``harness.host.check_host_api_compatible(expected)``
# which accepts any same-MAJOR semver (1.x.y vs 1.0.0 → OK). When
# upstream bumps to 2.x, this string should bump too — the check then
# forces an explicit, reviewed adapter migration rather than silently
# invoking a workflow with an incompatible signature.
_MIN_HOST_API_MAJOR = "1.0.0"


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
        # P1-1: derive default zero-counters from the closed set of known
        # reasons. Adding a new label requires updating
        # ``_KNOWN_PRESET_FAILURE_REASONS`` *and* confirming the snapshot
        # schema (the keys are exposed verbatim to dashboards).
        self.preset_load_failure_total: dict[str, int] = {reason: 0 for reason in sorted(_KNOWN_PRESET_FAILURE_REASONS)}
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
        # P1-1: reject unknown ``reason`` labels so that adding a new
        # category is a deliberate, two-step change (extend the closed
        # set *and* confirm dashboard consumers handle the new label)
        # rather than a silent schema drift.
        if reason not in _KNOWN_PRESET_FAILURE_REASONS:
            raise ValueError(f"unknown preset_load_failure reason: {reason!r}; known reasons: {sorted(_KNOWN_PRESET_FAILURE_REASONS)}")
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

    API-1: verifies host-API compatibility via
    ``harness.host.check_host_api_compatible(_MIN_HOST_API_MAJOR)`` — any
    same-MAJOR ``HOST_API_VERSION`` (e.g. installed "1.1.0", pinned "1.0.0")
    is accepted; a MAJOR mismatch raises :class:`HostApiVersionMismatch`,
    which is re-raised here as ``ImportError`` so the gateway surfaces 500
    with a clear "host API version mismatch" cause via its existing
    ``except ImportError`` path rather than silently invoking a workflow
    with an incompatible signature.
    """
    try:
        from harness.host import (  # type: ignore[import-not-found]
            HostApiVersionMismatch,
            check_host_api_compatible,
            compile_workflow,
            load_preset,
        )
    except ImportError as exc:
        raise RuntimeError("graph-harness is required for gh:* assistants but is not installed (missing 'harness.host')") from exc
    try:
        check_host_api_compatible(_MIN_HOST_API_MAJOR)
    except HostApiVersionMismatch as exc:
        # Re-raise as ImportError so the gateway surfaces 500 with a
        # version-mismatch message; keep the structured ``.expected`` /
        # ``.actual`` attributes intact on ``exc.__cause__`` for log
        # consumers that want to distinguish a major mismatch from a
        # missing-package failure.
        raise ImportError(f"graph-harness host API major version mismatch: installed={exc.actual!r}, this adapter requires major {_MIN_HOST_API_MAJOR.split('.')[0]!r}; upgrade the adapter or downgrade the graph-harness package.") from exc
    return compile_workflow, load_preset


def wrap_load_preset_errors(preset_name: str):
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
        except Exception as exc:
            _METRICS.incr_preset_load_failure("unknown")
            # P1-5: wrap + `from exc` so the original exception's traceback
            # and type are preserved on ``__cause__`` for log consumers and
            # the gateway's 500 path. The bare ``raise`` that used to live
            # here lost the original frame chain and surfaced the failure
            # as a generic ``None``/unknown in observability.
            raise GraphHarnessPresetAccessError(500, f"preset load failed: {preset_name!r}") from exc

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

    # P1-4: Real LangGraph ``astream(stream_mode="values")`` yields plain state
    # dicts (e.g. ``{"messages": [...], "user_goal": "..."}``) with NO
    # ``"event"`` key — there is no in-band end marker. End-of-run is
    # signalled by a clean ``StopAsyncIteration`` on the underlying async
    # iterator. The graph-harness ``MemoryStreamBridge`` translates that into
    # an ``END_SENTINEL`` (``StreamEvent(event="__end__", ...)``) on the
    # *consumer* side, but the proxy never observes it in-band.
    #
    # Therefore the ``_STREAM_END_MARKERS`` predicate below is **retained as
    # defence-in-depth** for any future LangGraph stream mode that might emit
    # an in-band end marker, but in practice it never matches in the default
    # ``values`` mode the adapter uses. ``sse_frame_missing_end_total`` is
    # therefore gated to never increment on the normal-completion path — see
    # the ``finally`` block below. Exposed at class level for tests.
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
        # Note: ``saw_end`` is kept for defence-in-depth in case a future
        # stream mode emits an in-band end marker (see P1-4 docstring).
        # The current detection predicate never matches in default
        # ``values`` mode, so this variable is intentionally unused in the
        # counter logic below — the F841 suppression is on the assignment.
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
            # P1-4: ``sse_frame_missing_end_total`` is intentionally not
            # incremented on the normal-completion path. Real LangGraph
            # ``values``-mode chunks carry no in-band end marker (see the
            # ``_STREAM_END_MARKERS`` docstring above), so a clean
            # ``StopAsyncIteration`` is the *expected* termination signal.
            # Counting it as "missing" would tick on every successful run.
            #
            # P1-3: BufferError is already counted via ``bridge_overflow_total``,
            # and other exception paths are accounted for by upstream error
            # handling — a "missing end" on the exception path is not
            # meaningful either. The counter is therefore a no-op in practice;
            # it remains in the snapshot shape so a downstream exporter does
            # not need a schema migration if a future stream mode adds an
            # in-band end marker.
            _ = saw_end  # retained for clarity; see P1-4 docstring
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

    Caller-side pre-validation (review finding P0-1): if the gateway
    invokes this factory on a background task (e.g. inside
    ``asyncio.create_task(run_agent(...))``), the
    ``GraphHarnessPresetAccessError`` raised here is *invisible to HTTP
    clients* because the request handler has already returned ``200 OK`` +
    ``thread_id`` by the time the error fires. Callers that want true
    HTTP-error semantics for a rejected preset name should pre-validate
    via :func:`check_preset_access` (or
    :func:`is_graph_harness_assistant` + an explicit access check) on the
    synchronous HTTP request path *before* scheduling ``run_agent`` —
    that way a rejection raises before the response is committed and can
    be translated to a real ``fastapi.HTTPException``. See the
    module-level "Integration contract" section for full context.
    """
    configurable = (config or {}).get("configurable") or {}
    preset_name = configurable.get("graph_preset")
    if not preset_name:
        raise ValueError("graph-harness assistant requires 'graph_preset' in config['configurable']")
    # SEC-1: pattern + whitelist. Must run before any file system call.
    check_preset_access(preset_name)
    # SEC-1: 404 mapping for missing presets via the engine's own validation.
    dsl = wrap_load_preset_errors(preset_name)
    compile_workflow, _ = _load_graph_harness()
    # Pass ``produces_keys`` from the manifest so the validator does not
    # flag the entry node for a missing producer (preset declares keys
    # it pre-seeds on the blackboard at run start; without this the
    # ``compile_workflow`` validator raises DATAFLOW_PATH_INPUT_MISSING
    # for action-level presets like ``echo`` / ``multi_step_llm``).
    produces_keys = set(dsl.get("produces_keys") or ())
    compiled = compile_workflow(dsl, preset_produces_keys=produces_keys)
    return _GraphHarnessCompiledProxy(compiled, preset_name)
