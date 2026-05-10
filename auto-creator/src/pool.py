"""
Client for the deployed WindsurfPoolAPI.

Relevant endpoints (no dashboard password needed for /auth/login):
  POST /auth/login    — add account via token/api_key/email+password
  GET  /auth/accounts — list all accounts
  GET  /health        — status including account counts
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class WindsurfPoolClient:
    def __init__(self, url: str, dashboard_password: str = ""):
        self.url = url.rstrip("/")
        self.password = dashboard_password

    async def get_accounts(self) -> list:
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(f"{self.url}/auth/accounts")
                return r.json().get("accounts", [])
        except Exception as e:
            logger.error(f"[Pool] get_accounts error: {e}")
            return []

    async def get_health(self) -> dict:
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{self.url}/health")
                return r.json()
        except Exception as e:
            logger.error(f"[Pool] health error: {e}")
            return {}

    async def inject_token(self, token: str, label: str = "") -> bool:
        """Inject an ott$ token. WindsurfPoolAPI exchanges it internally."""
        try:
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(
                    f"{self.url}/auth/login",
                    json={"token": token, "label": label},
                    headers={"Content-Type": "application/json"},
                )
            if r.status_code == 200:
                data = r.json()
                acct = data.get("account", {})
                logger.info(f"[Pool] ✅ Injected {label}: id={acct.get('id')} status={acct.get('status')}")
                return True
            logger.warning(f"[Pool] inject failed {r.status_code}: {r.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"[Pool] inject_token error: {e}")
            return False

    async def active_count(self) -> int:
        accounts = await self.get_accounts()
        return sum(
            1 for a in accounts
            if a.get("status") in ("active", "ready", "ok", "authenticated")
        )

    async def total_use_count(self) -> int:
        accounts = await self.get_accounts()
        return sum(
            a.get("useCount", a.get("use_count", 0))
            for a in accounts
        )
