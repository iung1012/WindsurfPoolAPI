"""
Windsurf account creator using Playwright + LuckMail for email verification.

Flow:
  1. create_order() on LuckMail → get allocated email address
  2. Open windsurf.com/account/register and fill the form
  3. Poll LuckMail for the 6-digit code (concurrent with browser waiting)
  4. Insert code → account confirmed
  5. Navigate to /show-auth-token and extract the ott$ token
  6. Return (email, ott_token) ready to inject into the pool
"""

import asyncio
import logging
import random
import string
from typing import Optional, Tuple
from urllib.parse import urlparse

from playwright.async_api import async_playwright

from luckmail import LuckMailClient

logger = logging.getLogger(__name__)

REGISTER_URL = "https://windsurf.com/account/register"


def _rand_str(n: int, chars: str = string.ascii_lowercase) -> str:
    return "".join(random.choices(chars, k=n))


def _strong_password() -> str:
    chars = [
        random.choice(string.ascii_uppercase),
        random.choice(string.ascii_lowercase),
        random.choice(string.digits),
        random.choice("!@#$%"),
    ]
    chars += random.choices(string.ascii_letters + string.digits, k=8)
    random.shuffle(chars)
    return "".join(chars)


def _parse_proxy(proxy_str: str) -> dict:
    protocol = "socks5" if "socks5" in proxy_str.lower() else "http"
    clean = proxy_str
    for prefix in ("socks5://", "http://", "https://"):
        clean = clean.replace(prefix, "")
    if "@" in clean:
        parsed = urlparse(f"{protocol}://{clean}")
        return {
            "server": f"{protocol}://{parsed.hostname}:{parsed.port}",
            "username": parsed.username,
            "password": parsed.password,
        }
    parts = clean.split(":")
    if len(parts) == 4:
        ip, port, user, pwd = parts
        return {"server": f"{protocol}://{ip}:{port}", "username": user, "password": pwd}
    return {"server": f"{protocol}://{clean}"}


async def create_one_account(
    luckmail: LuckMailClient,
    proxy: Optional[str] = None,
    headless: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create one Windsurf account.
    Returns (email, ott_token) on success, or (None, None) on failure.
    """
    # ── 1. Allocate email via LuckMail ──────────────────────────────────
    order = await luckmail.create_order()
    if not order:
        logger.error("[Creator] LuckMail order creation failed")
        return None, None

    email = order["email_address"]
    order_no = order["order_no"]
    password = _strong_password()
    first_name = "User" + _rand_str(4).capitalize()
    last_name = "Acc" + _rand_str(5).capitalize()

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        launch_kwargs: dict = {"headless": headless}
        if proxy:
            parsed = _parse_proxy(proxy)
            launch_kwargs["proxy"] = parsed
            logger.info(f"[Creator] Usando proxy: {parsed['server']}")
        else:
            logger.warning("[Creator] Sem proxy — IP do Railway será usado!")

        browser = await playwright.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        # ── 2. Open registration page ────────────────────────────────────
        logger.info(f"[Creator] Registering with {email}...")
        await page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_selector(
            'input[placeholder="Your first name"]', state="visible", timeout=20_000
        )

        await page.fill('input[placeholder="Your first name"]', first_name)
        await page.fill('input[placeholder="Your last name"]', last_name)
        await page.fill('input[placeholder="you@example.com"]', email)

        tos = page.locator('input[type="checkbox"]').first
        await tos.check(force=True)
        await page.click('button:has-text("Continue")')

        # ── 3. Password screen ───────────────────────────────────────────
        try:
            await page.wait_for_selector('input[type="password"]', timeout=30_000)
        except Exception:
            body = await page.inner_text("body")
            logger.error(f"[Creator] Password screen not found: {body[:200]}")
            await luckmail.cancel_order(order_no)
            return None, None

        body_text = await page.inner_text("body")
        if "Welcome back" in body_text or "Enter your password for" in body_text:
            logger.warning(f"[Creator] Account already exists: {email}")
            await luckmail.cancel_order(order_no)
            return None, None

        for inp in await page.query_selector_all('input[type="password"]'):
            await inp.fill(password)
        await page.click('button:has-text("Continue")')

        # ── 4. Wait for verification code screen ─────────────────────────
        try:
            await page.wait_for_selector("text=Check your inbox", timeout=30_000)
        except Exception:
            body_text = await page.inner_text("body")
            if "too many" in body_text.lower() or "rate" in body_text.lower():
                logger.error("[Creator] Rate limited by Windsurf!")
            else:
                logger.error(f"[Creator] Code screen not found: {body_text[:200]}")
            await luckmail.cancel_order(order_no)
            return None, None

        # ── 5. Poll LuckMail for code (while browser waits) ──────────────
        logger.info(f"[Creator] Waiting for code from LuckMail (order {order_no})...")
        code = await luckmail.poll_code(order_no, max_attempts=30, interval=4)
        if not code:
            logger.error(f"[Creator] No verification code received for {email}")
            return None, None

        # ── 6. Insert code ───────────────────────────────────────────────
        logger.info(f"[Creator] Inserting code: {code}")

        # Try multiple selectors for the OTP inputs
        code_inputs = (
            await page.query_selector_all('input[inputmode="numeric"]')
            or await page.query_selector_all('input[autocomplete="one-time-code"]')
            or await page.query_selector_all('input[type="text"]')
        )

        if len(code_inputs) >= 6:
            for i, digit in enumerate(code[:6]):
                await code_inputs[i].click()
                await code_inputs[i].fill(digit)
                await asyncio.sleep(0.15)
        elif len(code_inputs) == 1:
            await code_inputs[0].fill(code)
        else:
            # Fallback: type via keyboard
            for digit in code:
                await page.keyboard.type(digit, delay=80)

        # Submit
        submit = page.locator(
            'button:has-text("Create account"), '
            'button:has-text("Verify"), '
            'button:has-text("Submit")'
        )
        if await submit.count() > 0:
            await submit.first.click(force=True)
        else:
            await page.keyboard.press("Enter")

        # ── 7. Wait for successful redirect ──────────────────────────────
        account_ok = False
        for _ in range(20):
            await asyncio.sleep(2)
            url = page.url
            text = await page.inner_text("body")
            if "/register" not in url and "/login" not in url:
                account_ok = True
                logger.info(f"[Creator] Redirected to: {url}")
                break
            if any(w in text.lower() for w in ["welcome", "dashboard", "download", "workspace", "getting started"]):
                account_ok = True
                break

        if not account_ok:
            body_text = await page.inner_text("body")
            logger.error(f"[Creator] Account creation not confirmed. Body: {body_text[:200]}")
            return None, None

        # ── 8. Capture ott$ token ─────────────────────────────────────────
        logger.info("[Creator] Capturing auth token from /show-auth-token...")
        await page.goto(
            "https://windsurf.com/show-auth-token",
            wait_until="networkidle",
            timeout=20_000,
        )

        token: Optional[str] = await page.evaluate("""() => new Promise(resolve => {
            const find = () => {
                // Check input values
                for (const inp of document.querySelectorAll('input')) {
                    if (inp.value && inp.value.includes('ott$')) {
                        const m = inp.value.match(/ott\\$[A-Za-z0-9_\\-]{20,}/);
                        if (m) return m[0];
                    }
                }
                // Check page text
                const m = (document.body.innerText || document.body.textContent || '')
                    .match(/ott\\$[A-Za-z0-9_\\-]{20,}/);
                return m ? m[0] : null;
            };
            let t = find();
            if (t) { resolve(t); return; }
            let n = 0;
            const iv = setInterval(() => {
                n++;
                t = find();
                if (t || n >= 30) { clearInterval(iv); resolve(t || null); }
            }, 500);
        })""")

        if not token:
            logger.error(f"[Creator] ott$ token not found for {email}")
            return None, None

        logger.info(f"[Creator] ✅ {email} | Token: {token[:35]}...")
        return email, token

    except Exception as e:
        logger.exception(f"[Creator] Unexpected error for {email}: {e}")
        return None, None
    finally:
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if playwright:
            try:
                await playwright.stop()
            except Exception:
                pass
