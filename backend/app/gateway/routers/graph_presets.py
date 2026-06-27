"""Router exposing the graph-harness preset catalog to the frontend.

This is the *frontend-facing* counterpart to
:mod:`app.gateway.adapters.graph_harness`, which is the runtime that
actually compiles and runs the presets. The two modules are kept
independent on purpose:

* The **adapter** decides which preset names the runtime will accept
  (SEC-1 whitelist). It runs at request time inside the LangGraph run
  loop.
* This **router** decides which preset names the *frontend selector*
  shows in its dropdown. It runs at page-load time and must return
  the *intersection* of (a) presets the engine actually ships and
  (b) presets the SEC-1 whitelist currently permits.

We never re-implement the whitelist on the frontend — the frontend
trusts the whitelist filtered list verbatim. If the whitelist is later
tightened, the dropdown will shrink without any frontend change.

Deferred import
---------------

``harness.application.preset_catalog`` is imported lazily inside the
endpoint so that this module is always importable, even when
graph-harness is not installed (e.g. for tests of the rest of the
gateway). If graph-harness is missing, the endpoint returns an empty
list and logs at WARNING — the frontend treats an empty list as
"preset path disabled" and hides the selector entirely.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["graph-presets"])


class InputPortSpecOut(BaseModel):
    """Public-facing input port metadata (one row of the form generator).

    Mirrors :class:`harness.composer.preset_manifest.InputPortSpec` —
    fields are flattened so the frontend form builder can read them
    without needing to know the upstream dataclass shape.

    ``default`` is intentionally ``Any``: graph-harness permits JSON-
    serialisable literals here (``str``, ``int``, ``float``, ``bool``,
    ``None``, ``list``, ``dict``). Anything non-JSON-serialisable
    surfaces as ``None`` so the wire contract stays safe.
    """

    key: str = Field(..., description="Port key (e.g. 'user.goal')")
    type: str = Field(..., description="Coarse type tag (e.g. 'text', 'enum', 'number', 'bool')")
    required: bool = Field(default=True, description="Whether the port must be supplied before run")
    description: str = Field(default="", description="Human-readable hint shown next to the input")
    enum_values: list[str] | None = Field(default=None, description="Allowed values when type='enum', else null")
    default: Any | None = Field(default=None, description="JSON-serialisable default value, else null")


class GraphPresetResponse(BaseModel):
    """Public-facing preset metadata (one row of the dropdown).

    The ``id`` field is the canonical preset key the frontend will
    compose into ``assistant_id = "gh:" + id`` when creating a thread.
    It is the same value passed to ``harness.workflows.presets.load_preset``
    on the backend, so the contract is symmetric.

    ``input_ports`` is a passthrough of the preset manifest's
    ``InputPortSpec`` rows — defaults to an empty list so older
    graph-harness releases (0.1.x) that do not yet declare input ports
    degrade gracefully without a schema bump.
    """

    id: str = Field(..., description="Canonical preset key, used in `assistant_id = gh:<id>`")
    display_name: str = Field(..., description="Human-readable preset name")
    description: str = Field(..., description="One-line description shown in the dropdown")
    category: str = Field(..., description="Coarse bucket (e.g. 'utility', 'coding')")
    version: str = Field(..., description="Preset manifest version")
    input_ports: list[InputPortSpecOut] = Field(
        default_factory=list,
        description="Input port specs (Stage 1+) — empty for presets that declare none",
    )


class GraphPresetsListResponse(BaseModel):
    """Response model for the preset list endpoint.

    The frontend never sees raw preset paths, scenario names, or any
    other internal field — those would leak the on-disk preset
    directory layout and have no UI use case.
    """

    presets: list[GraphPresetResponse]


def _load_allowed_presets() -> frozenset[str]:
    """Read the SEC-1 whitelist from the adapter.

    Importing the adapter is safe even when graph-harness is not
    installed: the adapter module itself only imports ``harness.host``
    lazily inside ``make_graph_harness_agent``. The whitelist constant
    is module-level and side-effect free.
    """
    # Local import keeps this router importable in isolation (e.g.
    # when the rest of the gateway is unit-tested without the
    # graph-harness package on PYTHONPATH).
    from app.gateway.adapters.graph_harness import _allowed_presets

    return _allowed_presets()


def _discover_presets() -> list[dict[str, Any]]:
    """Call into graph-harness's preset discovery.

    Returns an empty list (with a logged warning) when the package is
    not installed. Callers MUST treat an empty list as "preset path
    disabled" — never as a 5xx.

    Each row also carries an ``input_ports`` field, a list of dicts
    that mirror the upstream :class:`InputPortSpec` dataclass. We use
    :func:`getattr` with a default so older graph-harness releases
    (0.1.x) that pre-date Stage 1 still produce a valid row — those
    presets simply advertise an empty input-port list.
    """
    try:
        from harness.application.preset_catalog import list_presets  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "graph-harness is not installed; GET /api/graph-presets will return an empty list. "
            "Install graph-harness (>=0.1,<2.0) and restart the gateway to enable the preset selector."
        )
        return []

    entries = list_presets()
    rows: list[dict[str, Any]] = []
    for entry in entries:
        # ``entry.input_ports`` is ``tuple[InputPortSpec, ...]`` on
        # graph-harness >= Stage 1; older releases raise AttributeError,
        # which we swallow to an empty list so the row is still usable.
        raw_ports = getattr(entry, "input_ports", ())
        input_ports: list[dict[str, Any]] = []
        for port in raw_ports:
            input_ports.append(
                {
                    "key": getattr(port, "key", ""),
                    "type": getattr(port, "type", "text"),
                    "required": getattr(port, "required", True),
                    "description": getattr(port, "description", "") or "",
                    "enum_values": getattr(port, "enum_values", None),
                    "default": getattr(port, "default", None),
                }
            )
        rows.append(
            {
                "key": entry.key,
                "display_name": entry.preset_name.replace("_", " ").title() or entry.key,
                "description": entry.description,
                "category": entry.scenario,
                "version": entry.version,
                "input_ports": input_ports,
            }
        )
    return rows


@router.get(
    "/graph-presets",
    response_model=GraphPresetsListResponse,
    summary="List Available Graph-Harness Presets",
    description=(
        "Return the preset manifests that the graph-harness library "
        "currently ships **and** that the SEC-1 whitelist permits. The "
        "frontend uses this list to populate the preset selector; it "
        "must be safe to expose verbatim (no internal paths leak).\n\n"
        "Returns `{ presets: [] }` (HTTP 200) when graph-harness is "
        "not installed — the frontend treats this as 'preset selector "
        "hidden' rather than an error."
    ),
)
async def list_graph_presets() -> GraphPresetsListResponse:
    """Return the intersection of (shipped presets) ∩ (SEC-1 whitelist).

    The whitelist takes precedence: any preset the engine ships that
    is *not* on the whitelist is filtered out here. Conversely, a
    preset that is on the whitelist but missing from the engine is
    also dropped (so the dropdown never offers a non-functional
    option).
    """
    allowed = _load_allowed_presets()
    shipped = _discover_presets()

    presets = [
        GraphPresetResponse(
            id=row["key"],
            display_name=row["display_name"],
            description=row["description"],
            category=row["category"],
            version=row["version"],
            input_ports=[InputPortSpecOut(**port) for port in row.get("input_ports", [])],
        )
        for row in shipped
        if row["key"] in allowed
    ]

    if shipped and not presets:
        # Engine ships presets but the whitelist hides them all.
        # Surface this as a warning so operators notice a misconfigured
        # DEERFLOW_GRAPH_HARNESS_PRESETS override.
        logger.warning(
            "/api/graph-presets: graph-harness shipped %d preset(s) but the SEC-1 whitelist "
            "hides all of them. Check DEERFLOW_GRAPH_HARNESS_PRESETS.",
            len(shipped),
        )

    return GraphPresetsListResponse(presets=presets)
