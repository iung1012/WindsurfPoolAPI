"""
Windsurf account creator using Playwright + Guerrilla Mail for email verification.
"""

import asyncio
import logging
import random
import re
import string
import time
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
import requests
from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)

REGISTER_URL = "https://windsurf.com/account/register"


# =============================================================================
# Helpers
# =============================================================================

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


async def _check_ip(proxy: Optional[str] = None) -> str:
    try:
        kwargs: dict = {"timeout": 10}
        if proxy:
            kwargs["proxy"] = proxy
        async with httpx.AsyncClient(**kwargs) as c:
            r = await c.get("https://api.ipify.org")
            return r.text.strip()
    except Exception as e:
        return f"erro: {e}"


# =============================================================================
# Guerrilla Mail client (synchronous — run in thread)
# =============================================================================

class GuerrillaMailClient:
    BASE_URL = "https://api.guerrillamail.com/ajax.php"

    def __init__(self):
        self.session_token: Optional[str] = None
        self.email_address: Optional[str] = None

    def get_email_address(self) -> str:
        response = requests.get(self.BASE_URL, params={"f": "get_email_address"}, timeout=10)
        response.raise_for_status()
        data = response.json()
        self.session_token = data.get("sid_token")
        self.email_address = data.get("email_addr")
        logger.info(f"[Guerrilla] Email temporario: {self.email_address}")
        return self.email_address

    def get_verification_code(self, max_attempts: int = 40, poll_interval: int = 5) -> Optional[str]:
        if not self.session_token:
            raise ValueError("Session token nao definido")

        for attempt in range(max_attempts):
            try:
                response = requests.get(
                    self.BASE_URL,
                    params={"f": "check_email", "seq": "0", "sid_token": self.session_token},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()

                count = 0
                try:
                    count = int(data.get("count", 0))
                except (ValueError, TypeError):
                    count = 0

                if count > 0:
                    emails = data.get("list", [])
                    for em in emails:
                        mail_id = em.get("mail_id")
                        mail_from = em.get("mail_from", "").lower()
                        if mail_from and "windsurf" not in mail_from and "codeium" not in mail_from:
                            continue
                        try:
                            fetch_resp = requests.get(
                                self.BASE_URL,
                                params={"f": "fetch_email", "email_id": mail_id, "sid_token": self.session_token},
                                timeout=10,
                            )
                            fetch_resp.raise_for_status()
                            body = fetch_resp.json().get("mail_body", "")
                            match = re.search(r"\b(\d{6})\b", body)
                            if match:
                                code = match.group(1)
                                logger.info(f"[Guerrilla] Codigo encontrado: {code}")
                                return code
                        except Exception as e:
                            logger.warning(f"[Guerrilla] Falha ao ler corpo do email {mail_id}: {e}")

                logger.info(f"[Guerrilla] Aguardando email... ({attempt + 1}/{max_attempts})")
            except Exception as e:
                logger.warning(f"[Guerrilla] Erro tentativa {attempt + 1}: {e}")

            time.sleep(poll_interval)

        logger.error(f"[Guerrilla] Codigo nao encontrado apos {max_attempts} tentativas.")
        return None


# =============================================================================
# Account creator
# =============================================================================

async def create_one_account(
    proxy: Optional[str] = None,
    headless: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create one Windsurf account using Guerrilla Mail.
    Returns (email, ott_token) on success, or (None, None) on failure.
    """
    ip = await _check_ip(proxy)
    if proxy:
        logger.info(f"[Creator] Proxy ativo — IP externo: {ip}")
    else:
        logger.warning(f"[Creator] SEM PROXY — IP direto: {ip}")

    guerrilla = GuerrillaMailClient()
    try:
        email = await asyncio.to_thread(guerrilla.get_email_address)
    except Exception as e:
        logger.error(f"[Creator] Falha ao obter email Guerrilla: {e}")
        return None, None

    password = _strong_password()
    first_name = "User" + _rand_str(4).capitalize()
    last_name = "Acc" + _rand_str(5).capitalize()
    logger.info(f"[Creator] Email alocado: {email}")

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        launch_kwargs: dict = {"headless": headless}
        if proxy:
            launch_kwargs["proxy"] = _parse_proxy(proxy)
            logger.info(f"[Creator] Playwright proxy: {launch_kwargs['proxy']['server']}")

        browser = await playwright.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        # 1. Open register page
        logger.info(f"[Creator] Abrindo {REGISTER_URL}...")
        await page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=60_000)
        logger.info(f"[Creator] Pagina carregada — URL: {page.url} | Titulo: {await page.title()}")

        try:
            await page.wait_for_selector('input[placeholder="Your first name"]', state="visible", timeout=20_000)
        except Exception:
            body = await page.inner_text("body")
            logger.error(f"[Creator] Campo 'First name' nao encontrado. Corpo: {body[:300]}")
            return None, None

        # 2. Fill form
        logger.info(f"[Creator] Preenchendo: nome={first_name} email={email}")
        await page.fill('input[placeholder="Your first name"]', first_name)
        await page.fill('input[placeholder="Your last name"]', last_name)
        await page.fill('input[placeholder="you@example.com"]', email)
        await page.locator('input[type="checkbox"]').first.check(force=True)
        await page.click('button:has-text("Continue")')

        # 3. Password screen
        try:
            await page.wait_for_selector('input[type="password"]', timeout=30_000)
            logger.info(f"[Creator] Tela de senha apareceu — URL: {page.url}")
        except Exception:
            body = await page.inner_text("body")
            logger.error(f"[Creator] Tela de senha NAO apareceu. URL: {page.url} | Corpo: {body[:300]}")
            return None, None

        body_text = await page.inner_text("body")
        if "Welcome back" in body_text or "Enter your password for" in body_text:
            logger.warning(f"[Creator] Email ja cadastrado: {email}")
            return None, None

        for inp in await page.query_selector_all('input[type="password"]'):
            await inp.fill(password)
        logger.info("[Creator] Senha preenchida — clicando Continue...")
        await page.click('button:has-text("Continue")')

        # 4. Wait for "Check your inbox"
        try:
            await page.wait_for_selector("text=Check your inbox", timeout=30_000)
            logger.info(f"[Creator] 'Check your inbox' encontrado — URL: {page.url}")
        except Exception:
            body_text = await page.inner_text("body")
            logger.error(f"[Creator] Tela 'Check your inbox' NAO encontrada — URL: {page.url}")
            logger.error(f"[Creator] Corpo atual: {body_text[:400]}")
            if "too many" in body_text.lower() or "rate" in body_text.lower():
                logger.error("[Creator] Rate limited pelo Windsurf!")
            return None, None

        # 5. Poll Guerrilla Mail for code (runs in thread so it doesn't block event loop)
        logger.info(f"[Creator] Aguardando codigo Guerrilla Mail (ate 3min30s)...")
        code = await asyncio.to_thread(guerrilla.get_verification_code, 40, 5)

        if not code:
            logger.error(f"[Creator] Codigo nao chegou para {email}")
            return None, None

        # 6. Enter code
        logger.info(f"[Creator] Codigo recebido: {code} — inserindo...")
        code_inputs = (
            await page.query_selector_all('input[inputmode="numeric"]')
            or await page.query_selector_all('input[autocomplete="one-time-code"]')
            or await page.query_selector_all('input[type="text"]')
        )
        logger.info(f"[Creator] Inputs de codigo encontrados: {len(code_inputs)}")

        if len(code_inputs) >= 6:
            for i, digit in enumerate(code[:6]):
                await code_inputs[i].click()
                await code_inputs[i].fill(digit)
                await asyncio.sleep(0.15)
        elif len(code_inputs) == 1:
            await code_inputs[0].fill(code)
        else:
            logger.warning("[Creator] Sem inputs especificos — digitando via teclado")
            for digit in code:
                await page.keyboard.type(digit, delay=80)

        submit = page.locator(
            'button:has-text("Create account"), '
            'button:has-text("Verify"), '
            'button:has-text("Submit")'
        )
        if await submit.count() > 0:
            await submit.first.click(force=True)
        else:
            await page.keyboard.press("Enter")

        # 7. Wait for success redirect (URL must leave /register and /login)
        try:
            await page.wait_for_url(
                lambda url: "/register" not in url and "/login" not in url,
                timeout=40_000,
            )
            logger.info(f"[Creator] Redirect confirmado para: {page.url}")
        except Exception:
            body_text = await page.inner_text("body")
            logger.error(f"[Creator] Conta nao confirmada — sem redirect. URL: {page.url}")
            logger.error(f"[Creator] Corpo: {body_text[:300]}")
            return None, None

        # 8. Capture ott$ token
        logger.info("[Creator] Navegando para /show-auth-token...")
        await page.goto("https://windsurf.com/show-auth-token", wait_until="domcontentloaded", timeout=30_000)

        token: Optional[str] = await page.evaluate("""() => new Promise(resolve => {
            const find = () => {
                for (const inp of document.querySelectorAll('input')) {
                    if (inp.value && inp.value.includes('ott$')) {
                        const m = inp.value.match(/ott\\$[A-Za-z0-9_\\-]{20,}/);
                        if (m) return m[0];
                    }
                }
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
            body_text = await page.inner_text("body")
            logger.error(f"[Creator] ott$ token nao encontrado. Corpo: {body_text[:300]}")
            return None, None

        logger.info(f"[Creator] CONTA CRIADA: {email} | Token: {token[:35]}...")
        return email, token

    except Exception as e:
        logger.exception(f"[Creator] Erro inesperado para {email}: {e}")
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
