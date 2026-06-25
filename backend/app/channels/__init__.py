"""IM Channel integration for DeerFlow.

Provides a pluggable channel system that connects external messaging platforms
(Feishu/Lark, Slack, Telegram) to the DeerFlow agent via the ChannelManager,
which uses ``langgraph-sdk`` to communicate with Gateway's LangGraph-compatible API.
"""

import asyncio
from builtins import open as _builtin_open

from app.channels.base import Channel
from app.channels.message_bus import InboundMessage, MessageBus, OutboundMessage


class _AsyncFile:
    """Async-friendly wrapper around a file object opened on a worker thread.

    ``__aenter__`` yields the underlying :class:`io.IOBase` so downstream SDKs
    (``discord.File(fp, ...)``, ``lark-oapi`` builders) can consume it on a
    thread via ``asyncio.to_thread``. ``__aexit__`` and ``.close()`` close the
    file on the thread pool. ``.read()`` is an async shim that dispatches to
    ``asyncio.to_thread(fp.read, ...)`` so callers can ``await wrapper.read()``
    without manually wrapping the call.
    """

    __slots__ = ("_fp",)

    def __init__(self, fp):
        self._fp = fp

    async def __aenter__(self):
        return self._fp

    async def __aexit__(self, exc_type, exc, tb):
        await asyncio.to_thread(self._fp.close)
        return None

    async def read(self, *args, **kwargs):
        return await asyncio.to_thread(self._fp.read, *args, **kwargs)

    async def close(self):
        await asyncio.to_thread(self._fp.close)


async def async_open(path: str, mode: str = "rb") -> _AsyncFile:
    """Asynchronously open ``path`` for reading/writing.

    Wraps :func:`builtins.open` via :func:`asyncio.to_thread` so the blocking
    syscall runs on the event loop's default thread pool, then hands the
    result to an async-friendly wrapper. Use as
    ``async with await async_open(path) as fp:`` -- ``fp`` is the underlying
    :class:`io.IOBase`, so blocking reads stay on the thread pool via
    ``await asyncio.to_thread(fp.read)``. The wrapper itself also exposes
    ``await wrapper.read()`` / ``await wrapper.close()`` for direct use
    without an ``async with`` block.

    Example::

        async with await async_open("/etc/hostname") as fp:
            data = await asyncio.to_thread(fp.read)
    """
    return _AsyncFile(await asyncio.to_thread(_builtin_open, path, mode))


__all__ = [
    "Channel",
    "InboundMessage",
    "MessageBus",
    "OutboundMessage",
    "async_open",
]
