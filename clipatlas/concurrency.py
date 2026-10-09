"""Bounded indexing work that drains active operations before returning."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Iterable

logger = logging.getLogger(__name__)


async def bounded_map[T, R](
    items: Iterable[T], operation: Callable[[T], Awaitable[R]], *, concurrency: int,
    label: str = "index",
) -> list[R]:
    if concurrency < 1:
        raise ValueError("concurrency must be positive")
    pending = iter(enumerate(items))
    results: dict[int, R] = {}
    errors: list[Exception] = []
    stopping = False

    async def worker() -> None:
        nonlocal stopping
        while not stopping:
            entry = next(pending, None)
            if entry is None:
                return
            index, item = entry
            started = time.monotonic()
            try:
                results[index] = await operation(item)
            except Exception as exc:  # noqa: BLE001 - drain siblings, then re-raise below
                stopping = True
                errors.append(exc)
            finally:
                logger.info("%s part=%s elapsed=%.3fs", label, index, time.monotonic() - started)

    group = asyncio.gather(*(worker() for _ in range(concurrency)), return_exceptions=True)
    try:
        settled = await asyncio.shield(group)
    except asyncio.CancelledError:
        # Finish accepted cloud calls and checkpoint writes; do not detach SDK threads.
        stopping = True
        await group
        raise
    for result in settled:
        if isinstance(result, BaseException):
            raise result
    if errors:
        raise errors[0]
    return [results[index] for index in sorted(results)]


async def drain_on_cancel[T](operation: Awaitable[T]) -> T:
    task = asyncio.ensure_future(operation)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise
