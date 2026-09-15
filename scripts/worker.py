"""Background worker — runs ingestion + eval jobs from a queue."""

from __future__ import annotations

import asyncio
import logging

# TODO: integrate with RQ, ARQ, or Celery
# For now: a simple poller that listens to a Redis queue


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("worker")
    log.info("Worker started. Waiting for jobs...")
    while True:
        # TODO: pop job from Redis, dispatch, repeat
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())
