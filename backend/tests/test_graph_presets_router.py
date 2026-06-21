"""Tests for the ``GET /api/graph-presets`` frontend-facing router.

The router has three layers of behaviour worth pinning down:

1. **Degraded mode**: graph-harness is not installed on PYTHONPATH.
   The endpoint must return HTTP 200 with ``{presets: []}`` — *not*
   5xx — so the frontend can render an empty selector instead of an
   error page.

2. **Whitelist filtering**: the SEC-1 whitelist in
   :mod:`app.gateway.adapters.graph_harness` is the source of truth for
   which preset ids the runtime accepts. The router must apply the
   same whitelist on top of the engine's ``list_presets`` output, so
   the frontend never offers a preset the backend will reject.

3. **Schema**: the response shape matches the TypeScript contract in
   ``frontend/src/core/graph-presets/types.ts``. A field rename here
   silently breaks the frontend dropdown — these tests act as the
   schema contract.

The router is tested by patching ``_discover_presets`` and
``_load_allowed_presets`` directly. The router's job is to (a) call
the engine's preset catalog (lazily, so the gateway stays
importable without graph-harness installed), (b) intersect with the
SEC-1 whitelist, and (c) shape the response. Both inputs are
patched here so the tests do not depend on the optional
``graph-harness`` package.

Auth note: the production gateway runs ``AuthMiddleware`` +
``@require_permission`` ahead of every router. This test builds a
bare :class:`FastAPI` app via :func:`_router_auth_helpers.make_authed_test_app`
so the auth chain never blocks the route under test.
"""

from __future__ import annotations

from typing import Any

import pytest
from _router_auth_helpers import make_authed_test_app
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.gateway.routers import graph_presets as router_module


@pytest.fixture
def app() -> FastAPI:
    app = make_authed_test_app()
    app.include_router(router_module.router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@pytest.fixture
def shipped_presets() -> list[dict[str, Any]]:
    """Shape returned by :func:`_discover_presets` in production.

    Each dict mirrors the keys the router constructs from
    ``harness.application.preset_catalog.PresetEntry``. The
    ``input_ports`` list mirrors the upstream
    :class:`InputPortSpec` dataclass; ``coding/coding_pipeline``
    advertises a single ``user.goal`` text port so the passthrough is
    exercised end-to-end, while the others stay empty (the most common
    preset shape today).
    """
    return [
        {
            "key": "echo/echo",
            "display_name": "Echo",
            "description": "Echoes the input back as the output.",
            "category": "utility",
            "version": "1.0.0",
            "input_ports": [],
        },
        {
            "key": "multi_step_llm/multi_step_llm",
            "display_name": "Multi Step Llm",
            "description": "Two-step LLM pipeline.",
            "category": "utility",
            "version": "1.0.0",
            "input_ports": [],
        },
        {
            "key": "coding/coding_pipeline",
            "display_name": "Coding Pipeline",
            "description": "End-to-end coding workflow.",
            "category": "coding",
            "version": "0.2.0",
            "input_ports": [
                {
                    "key": "user.goal",
                    "type": "text",
                    "required": True,
                    "description": "What the user wants the pipeline to build.",
                    "enum_values": None,
                    "default": None,
                },
            ],
        },
        {
            "key": "secret/internal_only",
            "display_name": "Internal Only",
            "description": "Not on the SEC-1 whitelist — must be filtered out.",
            "category": "internal",
            "version": "1.0.0",
            "input_ports": [],
        },
    ]


@pytest.fixture
def default_whitelist() -> frozenset[str]:
    return frozenset(
        {
            "echo/echo",
            "multi_step_llm/multi_step_llm",
            "coding/coding_pipeline",
        }
    )


@pytest.fixture
def stubbed_engine(
    monkeypatch: pytest.MonkeyPatch,
    shipped_presets: list[dict[str, Any]],
    default_whitelist: frozenset[str],
) -> None:
    """Wire up both of the router's two collaborators."""
    monkeypatch.setattr(router_module, "_discover_presets", lambda: shipped_presets)
    monkeypatch.setattr(router_module, "_load_allowed_presets", lambda: default_whitelist)


def test_returns_200_with_empty_list_when_engine_missing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """graph-harness uninstalled → empty list, NOT 5xx.

    Reproduces the production scenario where the operator has not yet
    installed the optional ``graph-harness`` package. The frontend
    treats ``presets: []`` as "hide the selector entirely" rather
    than an error.
    """
    monkeypatch.setattr(router_module, "_discover_presets", lambda: [])
    monkeypatch.setattr(router_module, "_load_allowed_presets", lambda: frozenset())
    response = client.get("/api/graph-presets")
    assert response.status_code == 200
    assert response.json() == {"presets": []}


def test_response_shape_matches_frontend_contract(client: TestClient, stubbed_engine: None) -> None:
    """Schema must match ``GraphPresetsListResponse`` in the frontend.

    Field renames here are a silent frontend break — pin the shape.
    """
    response = client.get("/api/graph-presets")
    assert response.status_code == 200
    body = response.json()

    # Top-level wrapper.
    assert set(body.keys()) == {"presets"}
    assert isinstance(body["presets"], list)

    # Each row has exactly the six fields the frontend renders:
    # the original five + ``input_ports`` (Stage 1+ passthrough).
    assert body["presets"], "fixture should expose at least one preset"
    sample = body["presets"][0]
    assert set(sample.keys()) == {
        "id",
        "display_name",
        "description",
        "category",
        "version",
        "input_ports",
    }
    # ``input_ports`` is always a list (possibly empty).
    assert isinstance(sample["input_ports"], list)


def test_input_ports_passthrough_for_coding_pipeline(client: TestClient, stubbed_engine: None) -> None:
    """``coding/coding_pipeline`` advertises a single ``user.goal`` text port.

    Pins the Stage 1 passthrough: a preset that declares input ports
    surfaces them verbatim on the wire, with every
    :class:`InputPortSpecOut` field intact (key, type, required,
    description, enum_values, default).
    """
    response = client.get("/api/graph-presets")
    assert response.status_code == 200

    by_id = {p["id"]: p for p in response.json()["presets"]}
    assert "coding/coding_pipeline" in by_id
    ports = by_id["coding/coding_pipeline"]["input_ports"]
    assert len(ports) == 1
    port = ports[0]
    # Every declared field is preserved end-to-end.
    assert set(port.keys()) == {"key", "type", "required", "description", "enum_values", "default"}
    assert port["key"] == "user.goal"
    assert port["type"] == "text"
    assert port["required"] is True


def test_input_ports_empty_for_presets_without_ports(client: TestClient, stubbed_engine: None) -> None:
    """Presets that declare no input ports surface an empty ``input_ports`` list.

    Confirms the fallback path (no ports on the upstream entry) renders
    as ``[]`` rather than ``null`` or a missing field — the frontend
    form builder iterates this field unconditionally.
    """
    response = client.get("/api/graph-presets")
    assert response.status_code == 200

    by_id = {p["id"]: p for p in response.json()["presets"]}
    for pid in ("echo/echo", "multi_step_llm/multi_step_llm"):
        assert pid in by_id
        assert by_id[pid]["input_ports"] == []


def test_whitelist_filters_out_off_whitelist_presets(client: TestClient, stubbed_engine: None) -> None:
    """SEC-1 whitelist takes precedence: a preset the engine ships but the adapter rejects must not appear.

    The fixture includes ``secret/internal_only`` which is not in the
    default whitelist. The endpoint must drop it.
    """
    response = client.get("/api/graph-presets")
    assert response.status_code == 200

    ids = {p["id"] for p in response.json()["presets"]}
    assert "secret/internal_only" not in ids
    # Sanity: at least one whitelisted preset is exposed so we know the
    # test is not asserting an always-true condition.
    assert ids  # non-empty intersection


def test_engine_shipping_zero_presets_returns_empty_list(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Edge case: engine ships nothing (e.g. presets_dir missing). Should not 5xx."""
    monkeypatch.setattr(router_module, "_discover_presets", lambda: [])
    monkeypatch.setattr(router_module, "_load_allowed_presets", lambda: frozenset())
    response = client.get("/api/graph-presets")
    assert response.status_code == 200
    assert response.json() == {"presets": []}


def test_engine_ships_presets_but_whitelist_hides_all_logs_warning(
    client: TestClient,
    shipped_presets: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the operator tightens DEERFLOW_GRAPH_HARNESS_PRESETS to a non-existent preset,
    the endpoint must log a WARNING so the misconfiguration is visible.
    """
    monkeypatch.setattr(router_module, "_discover_presets", lambda: shipped_presets)
    # Empty whitelist = hide everything.
    monkeypatch.setattr(router_module, "_load_allowed_presets", lambda: frozenset())

    with caplog.at_level("WARNING", logger="app.gateway.routers.graph_presets"):
        response = client.get("/api/graph-presets")

    assert response.status_code == 200
    assert response.json() == {"presets": []}
    assert any("whitelist hides all" in rec.message for rec in caplog.records)