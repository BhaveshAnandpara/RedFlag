"""One scan at a time, across the demo bots and real-bot runs."""

import asyncio
from collections.abc import Coroutine
from typing import Any


class ScanGate:
    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        # Keeps a reference so a running task is not collected before it finishes.
        self._background: set[asyncio.Task[None]] = set()

    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self, work: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
        task = asyncio.create_task(work)
        self._task = task
        self._background.add(task)
        task.add_done_callback(self._background.discard)
        return task
