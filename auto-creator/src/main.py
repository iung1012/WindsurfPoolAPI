"""
Windsurf Auto-Creator — entry point.

Reads config from environment variables, validates them, then starts the
scheduler loop that monitors the WindsurfPoolAPI and auto-creates accounts.

Required env vars:
  LUCKMAIL_API_KEY        — your LuckMail API key
  LUCKMAIL_API_SECRET     — your LuckMail API secret
  LUCKMAIL_PROJECT_CODE   — project code on LuckMail for Windsurf emails
  POOL_URL                — e.g. https://windsurfpoolapi-production.up.railway.app

Optional:
  PROXY                   — e.g. http://user:pass@host:port
  QUOTA_PER_ACCOUNT       — weekly request quota per free Windsurf account (default: 40)
  REQUESTS_PER_HOUR       — initial estimate for request rate (default: 5.0)
  BUFFER_FACTOR           — safety margin, 0.25 = 25% buffer (default: 0.25)
  MIN_ACCOUNTS            — always keep at least N accounts in pool (default: 2)
  MAX_CREATE_PER_RUN      — max accounts to create per scheduler tick (default: 5)
  CREATION_DELAY_SECONDS  — delay between account creations (default: 15)
  CHECK_INTERVAL_SECONDS  — how often to check pool state (default: 1800 = 30min)
"""

import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("main")


async def main():
    from luckmail import LuckMailClient
    from pool import WindsurfPoolClient
    from scheduler import AccountScheduler

    required = [
        "LUCKMAIL_API_KEY",
        "POOL_URL",
    ]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        logger.error(f"Missing required environment variables: {missing}")
        sys.exit(1)

    luckmail = LuckMailClient(
        api_key=os.environ["LUCKMAIL_API_KEY"],
        project_code=os.getenv("LUCKMAIL_PROJECT_CODE", "windsurf"),
    )
    pool = WindsurfPoolClient(
        url=os.environ["POOL_URL"],
        dashboard_password=os.getenv("POOL_DASHBOARD_PASSWORD", ""),
    )

    # Startup checks
    logger.info(f"[Main] Connecting to pool: {os.environ['POOL_URL']}")
    health = await pool.get_health()
    if health.get("status") == "ok":
        accts = health.get("accounts", {})
        logger.info(f"[Main] Pool healthy — accounts: {accts}")
    else:
        logger.warning(f"[Main] Pool health check returned: {health}")

    balance = await luckmail.check_balance()
    if balance is not None:
        logger.info(f"[Main] LuckMail balance: {balance}")
        if balance < 1.0:
            logger.warning("[Main] ⚠️  LuckMail balance is LOW — please top up!")
    else:
        logger.warning("[Main] Could not check LuckMail balance (check API credentials)")

    # List projects to help user confirm the right project_code
    projects = await luckmail.list_projects()
    if projects:
        codes = [p.get("code") or p.get("project_code", "?") for p in projects]
        logger.info(f"[Main] Available LuckMail projects: {codes}")

    scheduler = AccountScheduler(
        pool=pool,
        luckmail=luckmail,
        proxy=os.getenv("PROXY"),
        quota_per_account=int(os.getenv("QUOTA_PER_ACCOUNT", "40")),
        requests_per_hour=float(os.getenv("REQUESTS_PER_HOUR", "5.0")),
        buffer_factor=float(os.getenv("BUFFER_FACTOR", "0.25")),
        min_accounts=int(os.getenv("MIN_ACCOUNTS", "2")),
        max_create_per_run=int(os.getenv("MAX_CREATE_PER_RUN", "5")),
        creation_delay_seconds=int(os.getenv("CREATION_DELAY_SECONDS", "15")),
        check_interval_seconds=int(os.getenv("CHECK_INTERVAL_SECONDS", "1800")),
    )

    await scheduler.run()


if __name__ == "__main__":
    asyncio.run(main())
