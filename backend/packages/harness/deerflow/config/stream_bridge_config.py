"""Configuration for stream bridge."""

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

# Runtime-supported stream bridge backends.
#
# The ``"redis"`` backend is *planned* for Phase 2 but has not been implemented
# yet — see :func:`deerflow.runtime.stream_bridge.async_provider.make_stream_bridge`,
# which raises ``NotImplementedError`` if the redis branch is reached.  Keeping
# the Literal narrow so misconfiguration fails at Pydantic validation time
# (immediately on ``AppConfig.from_file()``) rather than only when the bridge
# is first used at runtime.
StreamBridgeType = Literal["memory"]


class StreamBridgeConfig(BaseModel):
    """Configuration for the stream bridge that connects agent workers to SSE endpoints."""

    type: StreamBridgeType = Field(
        default="memory",
        description=(
            "Stream bridge backend type. 'memory' uses in-process asyncio.Queue "
            "(single-process only). The 'redis' backend is planned for Phase 2 "
            "and is not yet implemented."
        ),
    )
    redis_url: str | None = Field(
        default=None,
        description="Reserved for the planned Redis Streams backend (Phase 2, not yet implemented).",
    )
    queue_maxsize: int = Field(
        default=256,
        description="Maximum number of events buffered per run in the memory bridge.",
    )

    @model_validator(mode="before")
    @classmethod
    def _reject_planned_backends(cls, data: Any) -> Any:
        """Reject ``type`` values reserved for planned-but-unimplemented backends.

        Without this hook, configuring ``type: redis`` would surface as the
        generic Pydantic error ``Input should be 'memory'`` from the narrowed
        ``StreamBridgeType`` Literal — accurate but unhelpful, since users have
        historically hit this late (only when the bridge is actually used at
        runtime) and have no idea why ``redis`` is no longer accepted.  Fail
        fast with a clear, actionable message at config-load time.
        """
        if isinstance(data, dict):
            requested = data.get("type")
            # ``None`` and the only currently-supported value are accepted
            # without commentary; everything else is reserved for a backend
            # that is not yet implemented.
            if requested is not None and requested != "memory":
                raise ValueError(
                    f"stream_bridge.type={requested!r} is not implemented; only 'memory' "
                    f"is currently supported. The 'redis' backend is planned for Phase 2 — "
                    "see runtime/stream_bridge/async_provider.py."
                )
        return data


# Global configuration instance — None means no stream bridge is configured
# (falls back to memory with defaults).
_stream_bridge_config: StreamBridgeConfig | None = None


def get_stream_bridge_config() -> StreamBridgeConfig | None:
    """Get the current stream bridge configuration, or None if not configured."""
    return _stream_bridge_config


def set_stream_bridge_config(config: StreamBridgeConfig | None) -> None:
    """Set the stream bridge configuration."""
    global _stream_bridge_config
    _stream_bridge_config = config


def load_stream_bridge_config_from_dict(config_dict: dict | None) -> None:
    """Load stream bridge configuration from a dictionary."""
    global _stream_bridge_config
    if config_dict is None:
        _stream_bridge_config = None
        return
    _stream_bridge_config = StreamBridgeConfig(**config_dict)
