"""
Smart account scheduler.

Every CHECK_INTERVAL_SECONDS it:
  1. Reads current pool state (active accounts, total use counts)
  2. Estimates the request rate (reqs/hour) from observed delta
  3. Calculates how many accounts are needed until the next Sunday reset
  4. Creates and injects the missing accounts

Formula:
  expected_requests = req_per_hour x hours_until_sunday x (1 + buffer_factor)
  needed_accounts   = max(MIN_ACCOUNTS, ceil(expected_requests / QUOTA_PER_ACCOUNT))
  to_create         = max(0, needed_accounts - active_count)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from math import ceil
from typing import Optional

from creator import create_one_account
from pool import WindsurfPoolClient

logger = logging.getLogger(__name__)


def hours_until_sunday_reset() -> float:
    """Hours until next Sunday midnight UTC."""
    now = datetime.now(timezone.utc)
    days_ahead = (6 - now.weekday()) % 7  # Mon=0 .. Sun=6
    if days_ahead == 0:
        days_ahead = 7  # already Sunday -> next Sunday
    secs = days_ahead * 86_400 - (now.hour * 3600 + now.minute * 60 + now.second)
    return secs / 3600


class AccountScheduler:
    def __init__(
        self,
        pool: WindsurfPoolClient,
        proxy: Optional[str] = None,
        quota_per_account: int = 40,
        requests_per_hour: float = 5.0,
        buffer_factor: float = 0.25,
        min_accounts: int = 2,
        max_create_per_run: int = 5,
        creation_delay_seconds: int = 15,
        check_interval_seconds: int = 1800,
    ):
        self.pool = pool
        self.proxy = proxy
        self.quota_per_account = quota_per_account
        self.requests_per_hour = requests_per_hour
        self.buffer_factor = buffer_factor
        self.min_accounts = min_accounts
        self.max_create_per_run = max_create_per_run
        self.creation_delay = creation_delay_seconds
        self.check_interval = check_interval_seconds

        self._last_uses: int = 0
        self._last_ts: Optional[float] = None

    async def run(self):
        logger.info(
            f"[Scheduler] Started — interval={self.check_interval}s "
            f"quota/acct={self.quota_per_account} min={self.min_accounts} "
            f"max_create={self.max_create_per_run}"
        )
        while True:
            try:
                await self._tick()
            except Exception as e:
                logger.exception(f"[Scheduler] Tick error: {e}")
            logger.info(f"[Scheduler] Sleeping {self.check_interval // 60}m until next check...")
            await asyncio.sleep(self.check_interval)

    async def _tick(self):
        accounts = await self.pool.get_accounts()
        active_count = sum(
            1 for a in accounts
            if a.get("status") in ("active", "ready", "ok", "authenticated")
        )
        total_uses = sum(
            a.get("useCount", a.get("use_count", 0)) for a in accounts
        )

        now = asyncio.get_event_loop().time()
        if self._last_ts is not None:
            elapsed_h = (now - self._last_ts) / 3600
            if elapsed_h > 0:
                delta = max(0, total_uses - self._last_uses)
                measured_rate = delta / elapsed_h
                self.requests_per_hour = 0.3 * self.requests_per_hour + 0.7 * measured_rate
                logger.info(
                    f"[Scheduler] Rate update: {measured_rate:.1f} req/h measured "
                    f"-> smoothed={self.requests_per_hour:.1f} req/h"
                )
        self._last_uses = total_uses
        self._last_ts = now

        h_left = hours_until_sunday_reset()
        expected_reqs = self.requests_per_hour * h_left * (1 + self.buffer_factor)
        needed = max(self.min_accounts, ceil(expected_reqs / self.quota_per_account))
        to_create = min(max(0, needed - active_count), self.max_create_per_run)

        avg_use = (total_uses / active_count) if active_count > 0 else 0
        remaining_quota = active_count * max(0, self.quota_per_account - avg_use)

        logger.info(
            f"[Scheduler] Active={active_count} AvgUse={avg_use:.1f} "
            f"RemainingQuota~{remaining_quota:.0f} HoursLeft={h_left:.1f}h "
            f"ExpectedReqs={expected_reqs:.0f} Needed={needed} ToCreate={to_create}"
        )

        if to_create > 0:
            await self._create_accounts(to_create)
        else:
            logger.info("[Scheduler] Pool adequately stocked")

    async def _create_accounts(self, count: int):
        if not self.proxy:
            logger.error("[Scheduler] PROXY nao configurado — criacao de contas abortada!")
            return
        logger.info(f"[Scheduler] Creating {count} account(s)...")
        success = 0
        for i in range(count):
            logger.info(f"[Scheduler] Account {i+1}/{count}...")
            email, token = await create_one_account(
                proxy=self.proxy,
                headless=True,
            )
            if email and token:
                ok = await self.pool.inject_token(token, label=email)
                if ok:
                    success += 1
                else:
                    logger.warning(f"[Scheduler] Created {email} but pool injection failed")
            else:
                logger.warning(f"[Scheduler] Account {i+1}/{count} creation failed")

            if i < count - 1:
                logger.info(f"[Scheduler] Waiting {self.creation_delay}s before next account...")
                await asyncio.sleep(self.creation_delay)

        logger.info(f"[Scheduler] Done: {success}/{count} accounts added to pool")
