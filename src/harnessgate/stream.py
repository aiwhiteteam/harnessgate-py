from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from .provider import Provider, ProviderEvent

logger = logging.getLogger("harnessgate.stream")


class StreamManager:
    def __init__(self, *, max_retries: int = 10) -> None:
        self._max_retries = max_retries
        self._active: dict[str, asyncio.Task[None]] = {}

    def ensure_stream(
        self,
        session_id: str,
        provider: Provider,
        on_event: Callable[[ProviderEvent], None],
    ) -> None:
        if session_id in self._active:
            return

        task = asyncio.create_task(
            self._run_stream(session_id, provider, on_event)
        )
        self._active[session_id] = task
        task.add_done_callback(lambda _: self._active.pop(session_id, None))

    async def _run_stream(
        self,
        session_id: str,
        provider: Provider,
        on_event: Callable[[ProviderEvent], None],
    ) -> None:
        seen_events: set[str] = set()
        retry_count = 0

        while retry_count < self._max_retries:
            try:
                logger.debug("Opening stream for session %s", session_id)
                async for event in provider.stream(session_id):
                    retry_count = 0

                    event_id = getattr(event, "event_id", None)
                    if event_id:
                        if event_id in seen_events:
                            continue
                        seen_events.add(event_id)
                        if len(seen_events) > 10000:
                            to_remove = list(seen_events)[:5000]
                            for k in to_remove:
                                seen_events.discard(k)

                    on_event(event)

                break
            except asyncio.CancelledError:
                break
            except Exception as err:
                retry_count += 1
                delay = min(1000 * 2**retry_count, 30_000) / 1000
                logger.warning(
                    "Stream error for %s, retry %d/%d in %.1fs: %s",
                    session_id, retry_count, self._max_retries, delay, err,
                )
                await asyncio.sleep(delay)

        logger.debug("Stream ended for session %s", session_id)

    def stop_stream(self, session_id: str) -> None:
        task = self._active.pop(session_id, None)
        if task:
            task.cancel()

    def stop_all(self) -> None:
        for task in self._active.values():
            task.cancel()
        self._active.clear()
        logger.info("All streams stopped")

    def is_active(self, session_id: str) -> bool:
        return session_id in self._active

    @property
    def active_count(self) -> int:
        return len(self._active)
