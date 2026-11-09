"""Scheduler and serialized probe execution; notification failures never lose check results."""

import asyncio
import logging

import httpx

from .config import Settings
from .db import Repository
from .probe import probe_target

log = logging.getLogger("pulseforge")


class MonitoringService:
    def __init__(self, repo: Repository, settings: Settings):
        self.repo = repo
        self.settings = settings
        self._locks: dict[int, asyncio.Lock] = {}
        self._concurrency = asyncio.Semaphore(10)
        self._delivery_lock = asyncio.Lock()

    async def check(self, monitor_id: int) -> dict | None:
        lock = self._locks.setdefault(monitor_id, asyncio.Lock())
        async with lock:
            monitor = self.repo.get_monitor(monitor_id)
            if monitor is None:
                return None
            if not monitor["enabled"]:
                raise ValueError("Monitor is paused")
            async with self._concurrency:
                result = await probe_target(
                    url=monitor["url"],
                    method=monitor["method"],
                    expected_status=monitor["expected_status"],
                    timeout_seconds=monitor["timeout_seconds"],
                    allow_private_targets=self.settings.allow_private_targets,
                )
            updated, notification = self.repo.record_probe(
                monitor_id, result, queue_notifications=bool(self.settings.alert_webhook_url)
            )
            if notification:
                if self.settings.alert_webhook_url:
                    await self.flush_notifications()
                else:
                    await self.send_notification(notification)
            return {
                "monitor": updated,
                "result": {
                    "ok": result.ok,
                    "status_code": result.status_code,
                    "latency_ms": result.latency_ms,
                    "error": result.error,
                },
                "event": notification["event"] if notification else None,
            }

    async def send_notification(self, payload: dict) -> None:
        """Deliver one event. Errors are handled by the durable outbox dispatcher."""
        if not self.settings.alert_webhook_url:
            return
        async with httpx.AsyncClient(timeout=5, follow_redirects=False, trust_env=False) as client:
            response = await client.post(self.settings.alert_webhook_url, json=payload)
            response.raise_for_status()

    async def flush_notifications(self) -> None:
        """Dispatch persisted events; a failure is retried with exponential backoff."""
        if not self.settings.alert_webhook_url:
            return
        async with self._delivery_lock:
            for item in self.repo.pending_notifications(limit=20):
                try:
                    await self.send_notification(item["payload"])
                except Exception as exc:
                    self.repo.mark_notification_failed(item["id"], item["attempts"], type(exc).__name__)
                    log.warning("Notification %s scheduled for retry (%s)", item["id"], type(exc).__name__)
                else:
                    self.repo.mark_notification_delivered(item["id"])

    async def run_scheduler(self) -> None:
        log.info("Monitor scheduler started (tick=%ss)", self.settings.scheduler_tick_seconds)
        ticks = 0
        while True:
            try:
                ids = self.repo.due_monitor_ids()
                if ids:
                    await asyncio.gather(*(self._safe_check(mid) for mid in ids))
                await self.flush_notifications()
                ticks += 1
                if ticks % max(1, 3600 // self.settings.scheduler_tick_seconds) == 0:
                    self.repo.purge_history(self.settings.history_retention_days)
            except Exception:
                log.exception("Unexpected scheduler error; continuing")
            await asyncio.sleep(self.settings.scheduler_tick_seconds)

    async def _safe_check(self, monitor_id: int) -> None:
        try:
            await self.check(monitor_id)
        except Exception:
            log.exception("Probe failed unexpectedly for monitor %s", monitor_id)
