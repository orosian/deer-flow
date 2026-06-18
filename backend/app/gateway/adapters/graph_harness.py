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
"""

from __future__ import annotations

from typing import Any

_GRAPH_HARNESS_PREFIX = "gh:"


def is_graph_harness_assistant(assistant_id: str | None) -> bool:
    """Return True if ``assistant_id`` designates a graph-harness preset (i.e. ``gh:...``)."""
    return bool(assistant_id) and assistant_id.startswith(_GRAPH_HARNESS_PREFIX)


def _load_graph_harness():
    """Lazy import of ``harness.host`` so this module is importable without the package installed."""
    try:
        from harness.host import compile_workflow, load_preset  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError(
            "graph-harness is required for gh:* assistants but is not installed (missing 'harness.host')"
        ) from exc
    return compile_workflow, load_preset


class _GraphHarnessCompiledProxy:
    """Thin wrapper around a compiled graph-harness workflow.

    Delegates ``ainvoke`` / ``astream`` straight to the compiled LangGraph
    graph so DeerFlow's upstream runtime (checkpointer, interrupts, SSE) is
    reused unchanged.
    """

    def __init__(self, compiled: Any, preset_name: str) -> None:
        self._compiled = compiled
        self._preset = preset_name

    async def ainvoke(self, input: Any, config: Any):
        return await self._compiled.ainvoke(input, config)

    async def astream(self, input: Any, config: Any, stream_mode: Any = None):
        if stream_mode is None:
            stream_mode = ["values"]
        async for chunk in self._compiled.astream(input, config, stream_mode=stream_mode):
            yield chunk


def make_graph_harness_agent(config: Any, app_config: Any = None):
    """Compile a graph-harness preset named by ``config['configurable']['graph_preset']``.

    Returns a proxy whose ``ainvoke`` / ``astream`` methods delegate to the
    underlying compiled workflow.  ``start_run`` is responsible for lifting
    ``body.input['graph_preset']`` into ``config['configurable']['graph_preset']``
    before this factory is called.
    """
    configurable = (config or {}).get("configurable") or {}
    preset_name = configurable.get("graph_preset")
    if not preset_name:
        raise ValueError(
            "graph-harness assistant requires 'graph_preset' in config['configurable']"
        )
    compile_workflow, load_preset = _load_graph_harness()
    dsl = load_preset(preset_name)
    compiled = compile_workflow(dsl)
    return _GraphHarnessCompiledProxy(compiled, preset_name)