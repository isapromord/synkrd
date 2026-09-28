"""
SynkDR Engine — Background Scheduler

Handles periodic tasks:
- Catalog sync from Shopify (every 2 hours)
- Analytics flush to Supabase (every 15 minutes)
- Daily summary notification
- Stale conversation cleanup
"""

import asyncio
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("synkdr.scheduler")


class Scheduler:
    """
    Lightweight async scheduler using asyncio tasks.
    No external dependencies (no APScheduler needed).
    """

    def __init__(self):
        self._tasks: list = []
        self._running = False

    async def start(
        self,
        sync_products_fn=None,
        flush_analytics_fn=None,
        send_daily_summary_fn=None,
        cleanup_stale_fn=None,
        abandoned_cart_fn=None,
        reengagement_fn=None,
        cod_lifecycle_fn=None,
    ):
        """Start all scheduled background tasks."""
        self._running = True
        logger.info("⏰ Scheduler started")

        if sync_products_fn:
            self._tasks.append(
                asyncio.create_task(
                    self._run_periodic("catalog_sync", sync_products_fn, interval_seconds=86400)
                )
            )

        if flush_analytics_fn:
            self._tasks.append(
                asyncio.create_task(
                    self._run_periodic("analytics_flush", flush_analytics_fn, interval_seconds=900)
                )
            )

        if cleanup_stale_fn:
            self._tasks.append(
                asyncio.create_task(
                    self._run_periodic("stale_cleanup", cleanup_stale_fn, interval_seconds=3600)
                )
            )

        if abandoned_cart_fn:
            self._tasks.append(
                asyncio.create_task(
                    self._run_periodic("abandoned_cart_recovery", abandoned_cart_fn, interval_seconds=900)
                )
            )

        if reengagement_fn:
            self._tasks.append(
                asyncio.create_task(
                    self._run_periodic("reengagement", reengagement_fn, interval_seconds=86400)
                )
            )

        if cod_lifecycle_fn:
            self._tasks.append(
                asyncio.create_task(
                    self._run_periodic("cod_lifecycle", cod_lifecycle_fn, interval_seconds=3600)
                )
            )

        if send_daily_summary_fn:
            self._tasks.append(
                asyncio.create_task(self._run_daily_at("daily_summary", send_daily_summary_fn, hour=22))
            )

    async def stop(self):
        """Cancel all scheduled tasks."""
        self._running = False
        for task in self._tasks:
            task.cancel()
        logger.info("⏰ Scheduler stopped")

    async def _run_periodic(self, name: str, fn, interval_seconds: int):
        """Run a function periodically with error recovery."""
        # Wait initial delay to avoid running everything at startup
        await asyncio.sleep(60)

        while self._running:
            try:
                logger.info(f"⏰ Running scheduled task: {name}")
                await fn()
                logger.info(f"✅ Scheduled task completed: {name}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Scheduled task {name} failed: {e}")

            try:
                await asyncio.sleep(interval_seconds)
            except asyncio.CancelledError:
                break

    async def _run_daily_at(self, name: str, fn, hour: int = 22):
        """Run a function once daily at a specific hour (UTC)."""
        while self._running:
            now = datetime.now(timezone.utc)
            target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if now >= target:
                target += timedelta(days=1)
            
            wait_seconds = (target - now).total_seconds()
            try:
                await asyncio.sleep(wait_seconds)
            except asyncio.CancelledError:
                break

            if not self._running:
                break

            try:
                logger.info(f"⏰ Running daily task: {name}")
                await fn()
                logger.info(f"✅ Daily task completed: {name}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"❌ Daily task {name} failed: {e}")


scheduler = Scheduler()
