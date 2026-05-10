"""
Windsurf Auto-Creator — entry point.

Required env vars:
  POOL_URL   — e.g. https://windsurfpoolapi-production.up.railway.app

Optional:
  PROXY                   — e.g. http://user:pass@host:port
  POOL_DASHBOARD_PASSWORD — dashboard password for pool API
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
    from pool import WindsurfPoolClient
    from scheduler import AccountScheduler

    if not os.getenv("POOL_URL"):
        logger.error("Missing required environment variable: POOL_URL")
        sys.exit(1)

    pool = WindsurfPoolClient(
        url=os.environ["POOL_URL"],
        dashboard_password=os.getenv("POOL_DASHBOARD_PASSWORD", ""),
    )

    logger.info(f"[Main] Connecting to pool: {os.environ['POOL_URL']}")
    health = await pool.get_health()
    if health.get("status") == "ok":
        accts = health.get("accounts", {})
        logger.info(f"[Main] Pool healthy — accounts: {accts}")
    else:
        logger.warning(f"[Main] Pool health check returned: {health}")

    proxy = os.getenv("PROXY")
    if proxy:
        logger.info(f"[Main] Proxy configurado: {proxy[:40]}...")
    else:
        logger.warning("[Main] PROXY nao configurado — criacao de contas sera bloqueada!")

    scheduler = AccountScheduler(
        pool=pool,
        proxy=proxy,
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
