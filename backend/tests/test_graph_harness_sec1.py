"""SEC-1 contract-gap regression tests for ``app.gateway.services.start_run``.

Background (review P0-1): ``make_graph_harness_agent`` raises
:class:`GraphHarnessPresetAccessError` with ``code`` set to 400 / 403 / 404
when the requested preset name fails pattern / whitelist / load checks.  When
the gateway defers that factory call into ``asyncio.create_task(...)`` the
HTTP handler has already returned ``200 OK`` + ``thread_id`` by the time the
error fires, so the client never observes a 4xx.  The fix runs the access
checks on the synchronous request path through
:func:`app.gateway.services._pre_check_graph_harness_preset` so a rejection
surfaces as a real :class:`fastapi.HTTPException` before ``create_task``
commits the run.

These tests exercise ``_pre_check_graph_harness_preset`` directly with
synthetic request bodies — the helper is the one synchronous seam that
``start_run`` calls before scheduling the background agent task.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.gateway.adapters.graph_harness import GraphHarnessPresetAccessError
from app.gateway.services import _pre_check_graph_harness_preset

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _body(assistant_id: str | None, graph_preset: str | None = None) -> SimpleNamespace:
    """Build a minimal stand-in for ``RunCreateRequest`` with the fields the
    pre-check actually reads (``assistant_id`` and ``input.graph_preset``).

    ``on_disconnect`` defaults to ``None`` so ``start_run`` takes the
    ``DisconnectMode.continue_`` branch (its ``else``).
    """
    input_payload = {"graph_preset": graph_preset} if graph_preset is not None else {}
    return SimpleNamespace(
        assistant_id=assistant_id,
        input=input_payload,
        on_disconnect=None,
    )


# ---------------------------------------------------------------------------
# Pattern violation (SEC-1 layer 1) -> 400
# ---------------------------------------------------------------------------


def test_preset_pattern_violation_returns_4xx_sync() -> None:
    """A ``graph_preset`` with a path-traversal / uppercase / whitespace shape
    is rejected synchronously with HTTP 400 — BEFORE ``start_run`` schedules
    the background agent task.  Mirrors the failure that
    ``make_graph_harness_agent`` would otherwise raise invisibly inside the
    asyncio task."""
    body = _body(assistant_id="gh:echo", graph_preset="../../etc/passwd")

    with pytest.raises(HTTPException) as exc_info:
        _pre_check_graph_harness_preset(body)

    assert exc_info.value.status_code == 400
    assert "invalid preset name format" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Whitelist miss (SEC-1 layer 2) -> 403
# ---------------------------------------------------------------------------


def test_preset_not_whitelisted_returns_4xx_sync() -> None:
    """A well-formed preset name that is not on the whitelist is rejected
    synchronously with HTTP 403.  The pre-check runs the whitelist lookup
    exactly like ``make_graph_harness_agent`` does."""
    body = _body(assistant_id="gh:echo", graph_preset="unlisted/preset")

    with pytest.raises(HTTPException) as exc_info:
        _pre_check_graph_harness_preset(body)

    assert exc_info.value.status_code == 403
    assert "allow-list" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Preset-not-found (SEC-1 layer 3) -> 404
# ---------------------------------------------------------------------------


def test_preset_not_found_returns_404_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """A whitelisted preset name that does not exist on disk in the
    graph-harness preset directory is rejected synchronously with HTTP 404.

    The pre-check calls ``wrap_load_preset_errors`` exactly like
    ``make_graph_harness_agent`` does, so the 404 mapping from the adapter's
    ``ValueError`` -> ``GraphHarnessPresetAccessError(code=404)`` translation
    runs on the sync path instead of vanishing into the background task.

    Uses a well-formed preset name that is on the default whitelist
    (``echo/echo`` is in :data:`_DEFAULT_ALLOWED_PRESETS`) but is not present
    on disk in this test environment — the underlying ``load_preset`` raises
    ``ValueError`` and the adapter wraps it as ``code=404``.
    """
    # ``echo/echo`` is on the default whitelist so ``check_preset_access`` passes
    # pattern + whitelist.  ``wrap_load_preset_errors`` would invoke ``load_preset``
    # which depends on the graph-harness library — not installed in the unit-test
    # venv.  Patch the wrapper to simulate the 404 path the adapter would emit when
    # ``load_preset`` raises ``ValueError``.
    body = _body(assistant_id="gh:echo", graph_preset="echo/echo")

    def fake_wrap(name: str) -> None:  # noqa: ARG001
        raise GraphHarnessPresetAccessError(404, f"preset not found: {name!r}")

    monkeypatch.setattr("app.gateway.services.wrap_load_preset_errors", fake_wrap)

    with pytest.raises(HTTPException) as exc_info:
        _pre_check_graph_harness_preset(body)

    assert exc_info.value.status_code == 404
    assert "preset not found" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Happy path — pre-check is a no-op for non-graph-harness or empty presets
# ---------------------------------------------------------------------------


def test_happy_path_still_works_for_non_graph_harness_assistant() -> None:
    """When ``assistant_id`` is not a ``gh:*`` preset, the pre-check is a
    no-op so the lead-agent happy path is untouched."""
    body = _body(assistant_id="lead_agent", graph_preset="echo/echo")
    # Must not raise — the lead-agent path does not even read graph_preset.
    _pre_check_graph_harness_preset(body)


def test_happy_path_still_works_when_no_preset_supplied() -> None:
    """When the caller omits ``graph_preset`` from ``input``, the pre-check
    is a no-op.  ``make_graph_harness_agent`` will still raise ``ValueError``
    inside the background task — that is a different error class and is
    left alone (MON-1 metrics + existing contract)."""
    body = _body(assistant_id="gh:echo", graph_preset=None)
    _pre_check_graph_harness_preset(body)


def test_happy_path_still_works_for_assistant_id_none() -> None:
    """``assistant_id=None`` (the default for the LangGraph-compatible
    runtime) routes through the lead-agent factory and never reaches the
    pre-check."""
    body = _body(assistant_id=None)
    _pre_check_graph_harness_preset(body)


# ---------------------------------------------------------------------------
# MON-1: pre-check re-uses the adapter's metric counters
# ---------------------------------------------------------------------------


def test_pre_check_increments_pattern_metric_for_pattern_violation() -> None:
    """A pattern violation must increment ``preset_load_failure_total{reason="pattern"}``
    — the same MON-1 metric that the in-factory path increments, so the
    rejection category is observable whether the pre-check or the factory
    raises first."""
    from app.gateway.adapters.graph_harness import reset_metrics, snapshot_metrics

    reset_metrics()
    body = _body(assistant_id="gh:echo", graph_preset="../../etc/passwd")

    with pytest.raises(HTTPException):
        _pre_check_graph_harness_preset(body)

    snap = snapshot_metrics()
    assert snap["preset_load_failure_total"]["pattern"] >= 1


def test_pre_check_increments_not_allowed_metric_for_whitelist_miss() -> None:
    """A whitelist miss must increment ``preset_load_failure_total{reason="not_allowed"}``."""
    from app.gateway.adapters.graph_harness import reset_metrics, snapshot_metrics

    reset_metrics()
    body = _body(assistant_id="gh:echo", graph_preset="unlisted/preset")

    with pytest.raises(HTTPException):
        _pre_check_graph_harness_preset(body)

    snap = snapshot_metrics()
    assert snap["preset_load_failure_total"]["not_allowed"] >= 1


# ---------------------------------------------------------------------------
# Wiring: start_run actually calls the pre-check before create_task
# ---------------------------------------------------------------------------


def test_start_run_invokes_pre_check_before_create_task() -> None:
    """Regression anchor for the contract-gap fix: ``start_run`` must call
    ``_pre_check_graph_harness_preset`` BEFORE it calls ``asyncio.create_task``.

    If the pre-check raises, the HTTP handler returns a 4xx and never
    schedules the background run.

    We assert this by inspecting ``start_run``'s source rather than driving
    the function end-to-end — ``start_run`` reads ~10 body fields and depends
    on the FastAPI ``Request`` lifecycle (run_manager / thread_store / checkpointer),
    so a full end-to-end test would be a fixture swamp with no additional
    coverage beyond the 8 isolated ``_pre_check_graph_harness_preset`` tests above.
    """
    import inspect

    from app.gateway import services

    source = inspect.getsource(services.start_run)
    pre_check_idx = source.find("_pre_check_graph_harness_preset(body)")
    create_task_idx = source.find("asyncio.create_task(")

    assert pre_check_idx != -1, "start_run no longer calls _pre_check_graph_harness_preset"
    assert create_task_idx != -1, "start_run no longer calls asyncio.create_task"
    assert pre_check_idx < create_task_idx, (
        "SEC-1 contract gap regressed: _pre_check_graph_harness_preset must run "
        "BEFORE asyncio.create_task so a rejected preset returns 4xx to the client"
    )