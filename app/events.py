from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

EventSink = Callable[[str, dict[str, Any]], Awaitable[None]]


async def emit(sink: EventSink | None, kind: str, **data: Any) -> None:
    if sink is not None:
        await sink(kind, data)
