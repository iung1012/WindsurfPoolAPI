"""
LuckMail API client — Mode A (code receive, pay-per-success).

Flow:
  1. create_order() → allocates an email + order_no
  2. poll_code(order_no) → polls until code arrives or timeout
  3. cancel_order(order_no) → cancels if unused

Auth: single API key used as both identifier and HMAC-SHA256 signing secret.
  X-API-Key: {api_key}
  X-Timestamp: {unix_timestamp}
  X-Signature: HMAC-SHA256(api_key, METHOD + path + timestamp + body)
"""

import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

BASE_URL = "https://mails.luckyous.com"


class LuckMailClient:
    def __init__(self, api_key: str, project_code: str):
        self.api_key = api_key
        self.project_code = project_code

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        ts = int(time.time())
        msg = method.upper() + path + str(ts) + body
        sig = hmac.new(
            self.api_key.encode("utf-8"),
            msg.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-API-Key": self.api_key,
            "X-Timestamp": str(ts),
            "X-Signature": sig,
            "Content-Type": "application/json",
        }

    async def create_order(self, email_type: str = "ms_graph") -> Optional[dict]:
        """Allocate a temporary email and create a code-receive order."""
        path = "/api/v1/openapi/order/create"
        payload = {"project_code": self.project_code, "email_type": email_type}
        body = json.dumps(payload)
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.post(f"{BASE_URL}{path}", content=body, headers=self._headers("POST", path, body))
                data = r.json()
            if data.get("code") == 0:
                d = data["data"]
                logger.info(f"[LuckMail] Order {d['order_no']} → {d['email_address']}")
                return d
            logger.error(f"[LuckMail] create_order failed: code={data.get('code')} msg={data.get('message')}")
            return None
        except Exception as e:
            logger.error(f"[LuckMail] create_order error: {e}")
            return None

    async def poll_code(
        self,
        order_no: str,
        max_attempts: int = 30,
        interval: int = 4,
    ) -> Optional[str]:
        """Poll every `interval` seconds until code received, timeout, or cancelled."""
        path = f"/api/v1/openapi/order/{order_no}/code"
        for attempt in range(max_attempts):
            await asyncio.sleep(interval)
            try:
                async with httpx.AsyncClient(timeout=15) as c:
                    r = await c.get(f"{BASE_URL}{path}", headers=self._headers("GET", path))
                    data = r.json()
                if data.get("code") == 0:
                    od = data["data"]
                    status = od.get("status")
                    if status == "success":
                        code = od.get("verification_code")
                        logger.info(f"[LuckMail] ✅ Code for {order_no}: {code}")
                        return code
                    if status in ("timeout", "cancelled"):
                        logger.warning(f"[LuckMail] Order {order_no} ended: {status}")
                        return None
                    logger.debug(f"[LuckMail] {order_no} pending ({attempt+1}/{max_attempts})")
                else:
                    logger.warning(f"[LuckMail] poll error: {data.get('message')}")
            except Exception as e:
                logger.warning(f"[LuckMail] poll attempt {attempt+1} error: {e}")

        logger.error(f"[LuckMail] No code after {max_attempts} attempts for {order_no}")
        await self.cancel_order(order_no)
        return None

    async def cancel_order(self, order_no: str):
        path = f"/api/v1/openapi/order/{order_no}/cancel"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{BASE_URL}{path}", headers=self._headers("POST", path))
            logger.info(f"[LuckMail] Cancelled {order_no}")
        except Exception as e:
            logger.warning(f"[LuckMail] cancel error: {e}")

    async def check_balance(self) -> Optional[float]:
        path = "/api/v1/openapi/balance"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{BASE_URL}{path}", headers=self._headers("GET", path))
                data = r.json()
            if data.get("code") == 0:
                return float(data["data"].get("balance", 0))
        except Exception as e:
            logger.warning(f"[LuckMail] balance check error: {e}")
        return None

    async def list_projects(self) -> list:
        """List available projects (to find your Windsurf project_code)."""
        path = "/api/v1/openapi/projects"
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.get(f"{BASE_URL}{path}", headers=self._headers("GET", path))
                data = r.json()
            if data.get("code") == 0:
                return data.get("data", {}).get("list", data.get("data", []))
        except Exception as e:
            logger.warning(f"[LuckMail] list_projects error: {e}")
        return []
