from __future__ import annotations

import pytest

from deerflow.config.stream_bridge_config import (
    StreamBridgeConfig,
    load_stream_bridge_config_from_dict,
    set_stream_bridge_config,
)


@pytest.fixture(autouse=True)
def _reset_stream_bridge_config() -> None:
    """Each test must start from a clean global config (default ``None``)."""
    set_stream_bridge_config(None)
    load_stream_bridge_config_from_dict(None)
    yield
    set_stream_bridge_config(None)
    load_stream_bridge_config_from_dict(None)


class TestStreamBridgeConfig:
    """The redis backend is *planned* for Phase 2 but not implemented; the
    config layer must reject ``type: redis`` at load time rather than letting
    it pass through and only blow up later at runtime."""

    def test_default_type_is_memory(self) -> None:
        cfg = StreamBridgeConfig()
        assert cfg.type == "memory"

    def test_explicit_memory_type_is_accepted(self) -> None:
        cfg = StreamBridgeConfig(type="memory", queue_maxsize=64)
        assert cfg.type == "memory"
        assert cfg.queue_maxsize == 64

    def test_redis_type_is_rejected_at_load_time(self) -> None:
        """``type: redis`` must fail immediately via the ``model_validator``
        so the user sees a clear "not implemented / Phase 2" message instead
        of the generic Pydantic ``Input should be 'memory'`` Literal error."""
        with pytest.raises(ValueError) as exc_info:
            StreamBridgeConfig(type="redis")
        message = str(exc_info.value)
        assert "redis" in message
        assert "Phase 2" in message
        assert "not implemented" in message

    def test_unknown_type_is_rejected_at_load_time(self) -> None:
        """Arbitrary backend names should be rejected too — anything other
        than ``"memory"`` is reserved for planned-but-unimplemented work."""
        with pytest.raises(ValueError) as exc_info:
            StreamBridgeConfig(type="kafka")
        assert "kafka" in str(exc_info.value)
        assert "not implemented" in str(exc_info.value)

    def test_load_stream_bridge_config_from_dict_rejects_redis(self) -> None:
        """The ``load_stream_bridge_config_from_dict`` helper used by the
        ``AppConfig`` reload boundary must surface the same error — this is
        the path that fires when ``config.yaml`` is parsed at startup."""
        with pytest.raises(ValueError) as exc_info:
            load_stream_bridge_config_from_dict({"type": "redis", "redis_url": "redis://localhost:6379/0"})
        assert "redis" in str(exc_info.value)
        assert "Phase 2" in str(exc_info.value)

    def test_redis_url_field_is_still_reserved(self) -> None:
        """The ``redis_url`` field stays accepted so users can stage config
        for the future backend without it being flagged as a Pydantic
        ValidationError; it just becomes a no-op until the backend ships."""
        cfg = StreamBridgeConfig(redis_url="redis://localhost:6379/0")
        assert cfg.redis_url == "redis://localhost:6379/0"
        assert cfg.type == "memory"  # default

    def test_empty_dict_loads_defaults(self) -> None:
        """Empty config (or missing ``stream_bridge`` section) should yield a
        memory bridge with defaults — no validator interference."""
        load_stream_bridge_config_from_dict({})
        from deerflow.config.stream_bridge_config import get_stream_bridge_config

        cfg = get_stream_bridge_config()
        assert cfg is not None
        assert cfg.type == "memory"
        assert cfg.queue_maxsize == 256


def test_pydantic_literal_narrows_to_memory_only() -> None:
    """Defense in depth: even if the ``model_validator`` were ever bypassed,
    the narrowed ``StreamBridgeType = Literal['memory']`` still rejects
    ``type: redis`` via the standard Pydantic ValidationError.  This is a
    structural property of the type alias and not something the runtime
    path can ever weaken."""
    import typing

    args = typing.get_args(StreamBridgeConfig.model_fields["type"].annotation)
    assert args == ("memory",)
