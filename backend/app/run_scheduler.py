"""Standalone scheduler entry point for supervisord.

Starts APScheduler + event checker inside a proper asyncio event loop.
"""

import asyncio
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    from app.pipeline.orchestrator import get_scheduler, run_event_checker

    scheduler = get_scheduler()
    scheduler.start()
    logger.info("Scheduler started with %d jobs", len(scheduler.get_jobs()))

    # Run event checker as a background task
    event_task = asyncio.create_task(run_event_checker())
    logger.info("Event checker started")

    # Keep running forever
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        pass
    finally:
        scheduler.shutdown(wait=False)
        event_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
