"""
Windsurf account creator using Playwright + LuckMail for email verification.
"""

import asyncio
import logging
import random
import string
from typing import Optional, Tuple
from urllib.parse import urlparse

import httpx
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


async def _check_ip(proxy: Optional[str] = None) -> str:
    """Returns the public IP seen by the outside world (via proxy if set)."""
    try:
        proxies = None
        if proxy:
            proxies = {"http://": proxy, "https://": proxy}
        async with httpx.AsyncClient(proxies=proxies, timeout=10) as c:
            r = await c.get("https://api.ipify.org")
            return r.text.strip()
    except Exception as e:
        return f"erro: {e}"


async def create_one_account(
    luckmail: LuckMailClient,
    proxy: Optional[str] = None,
    headless: bool = True,
) -> Tuple[Optional[str], Optional[str]]:
    """
    Create one Windsurf account.
    Returns (email, ott_token) on success, or (None, None) on failure.
    """
    # ── 0. Verificar IP real (proxy ou direto) ───────────────────────
    ip = await _check_ip(proxy)
    if proxy:
        logger.info(f"[Creator] Proxy ativo — IP externo: {ip}")
    else:
        logger.warning(f"[Creator] SEM PROXY — IP direto do Railway: {ip}")

    # ── 1. Allocate email via LuckMail ──────────────────────────────────
    order = await luckmail.create_order()
    if not order:
        logger.error("[Creator] Falha ao criar pedido LuckMail")
        return None, None

    email = order["email_address"]
    order_no = order["order_no"]
    password = _strong_password()
    first_name = "User" + _rand_str(4).capitalize()
    last_name = "Acc" + _rand_str(5).capitalize()
    logger.info(f"[Creator] Email alocado: {email} | Pedido: {order_no}")

    playwright = None
    browser = None
    try:
        playwright = await async_playwright().start()
        launch_kwargs: dict = {"headless": headless}
        if proxy:
            parsed = _parse_proxy(proxy)
            launch_kwargs["proxy"] = parsed
            logger.info(f"[Creator] Playwright proxy: {parsed['server']}")

        browser = await playwright.chromium.launch(**launch_kwargs)
        ctx = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await ctx.new_page()

        # ── 2. Abrir página de registro ──────────────────────────────────
        logger.info(f"[Creator] Abrindo {REGISTER_URL}...")
        await page.goto(REGISTER_URL, wait_until="domcontentloaded", timeout=60_000)
        logger.info(f"[Creator] Página carregada — URL: {page.url} | Título: {await page.title()}")

        try:
            await page.wait_for_selector('input[placeholder="Your first name"]', state="visible", timeout=20_000)
        except Exception:
            body = await page.inner_text("body")
            logger.error(f"[Creator] Campo 'First name' não encontrado. Corpo: {body[:300]}")
            await luckmail.cancel_order(order_no)
            return None, None

        logger.info(f"[Creator] Preenchendo: nome={first_name} sobrenome={last_name} email={email}")
        await page.fill('input[placeholder="Your first name"]', first_name)
        await page.fill('input[placeholder="Your last name"]', last_name)
        await page.fill('input[placeholder="you@example.com"]', email)

        tos = page.locator('input[type="checkbox"]').first
        await tos.check(force=True)
        logger.info("[Creator] TOS marcado — clicando Continue...")
        await page.click('button:has-text("Continue")')

        # ── 3. Tela de senha ─────────────────────────────────────────────
        try:
            await page.wait_for_selector('input[type="password"]', timeout=30_000)
            logger.info(f"[Creator] Tela de senha apareceu — URL: {page.url}")
        except Exception:
            body = await page.inner_text("body")
            logger.error(f"[Creator] Tela de senha NÃO apareceu. URL: {page.url} | Corpo: {body[:300]}")
            await luckmail.cancel_order(order_no)
            return None, None

        body_text = await page.inner_text("body")
        if "Welcome back" in body_text or "Enter your password for" in body_text:
            logger.warning(f"[Creator] Email já cadastrado: {email}")
            await luckmail.cancel_order(order_no)
            return None, None

        for inp in await page.query_selector_all('input[type="password"]'):
            await inp.fill(password)
        logger.info("[Creator] Senha preenchida — clicando Continue...")
        await page.click('button:has-text("Continue")')

        # ── 4. Aguardar tela de verificação ──────────────────────────────
        try:
            await page.wait_for_selector("text=Check your inbox", timeout=30_000)
            logger.info(f"[Creator] ✅ 'Check your inbox' encontrado — URL: {page.url}")
            body_text = await page.inner_text("body")
            logger.info(f"[Creator] Corpo da tela de verificação: {body_text[:200]}")
        except Exception:
            body_text = await page.inner_text("body")
            logger.error(f"[Creator] Tela 'Check your inbox' NÃO encontrada — URL: {page.url}")
            logger.error(f"[Creator] Corpo atual: {body_text[:400]}")
            if "too many" in body_text.lower() or "rate" in body_text.lower():
                logger.error("[Creator] ⚠️  Rate limited pelo Windsurf!")
            await luckmail.cancel_order(order_no)
            return None, None

        # ── 5. Poll LuckMail pelo código ─────────────────────────────────
        logger.info(f"[Creator] Aguardando código LuckMail (pedido {order_no}, até 5min)...")
        code = await luckmail.poll_code(order_no, max_attempts=60, interval=5)
        if not code:
            logger.error(f"[Creator] ❌ Código não chegou para {email} após 5min")
            return None, None

        # ── 6. Inserir código ────────────────────────────────────────────
        logger.info(f"[Creator] Código recebido: {code} — inserindo...")

        code_inputs = (
            await page.query_selector_all('input[inputmode="numeric"]')
            or await page.query_selector_all('input[autocomplete="one-time-code"]')
            or await page.query_selector_all('input[type="text"]')
        )
        logger.info(f"[Creator] Inputs de código encontrados: {len(code_inputs)}")

        if len(code_inputs) >= 6:
            for i, digit in enumerate(code[:6]):
                await code_inputs[i].click()
                await code_inputs[i].fill(digit)
                await asyncio.sleep(0.15)
        elif len(code_inputs) == 1:
            await code_inputs[0].fill(code)
        else:
            logger.warning("[Creator] Sem inputs específicos — digitando via teclado")
            for digit in code:
                await page.keyboard.type(digit, delay=80)

        submit = page.locator(
            'button:has-text("Create account"), '
            'button:has-text("Verify"), '
            'button:has-text("Submit")'
        )
        n_submit = await submit.count()
        logger.info(f"[Creator] Botões de submit encontrados: {n_submit}")
        if n_submit > 0:
            await submit.first.click(force=True)
        else:
            await page.keyboard.press("Enter")

        # ── 7. Aguardar redirect de sucesso ──────────────────────────────
        account_ok = False
        for attempt in range(20):
            await asyncio.sleep(2)
            url = page.url
            text = await page.inner_text("body")
            logger.debug(f"[Creator] Aguardando redirect ({attempt+1}/20) — URL: {url}")
            if "/register" not in url and "/login" not in url:
                account_ok = True
                logger.info(f"[Creator] ✅ Redirect para: {url}")
                break
            if any(w in text.lower() for w in ["welcome", "dashboard", "download", "workspace", "getting started"]):
                account_ok = True
                logger.info(f"[Creator] ✅ Texto de sucesso detectado na página")
                break

        if not account_ok:
            body_text = await page.inner_text("body")
            logger.error(f"[Creator] ❌ Conta não confirmada. URL: {page.url}")
            logger.error(f"[Creator] Corpo: {body_text[:300]}")
            return None, None

        # ── 8. Capturar token ott$ ────────────────────────────────────────
        logger.info("[Creator] Navegando para /show-auth-token...")
        await page.goto("https://windsurf.com/show-auth-token", wait_until="networkidle", timeout=20_000)
        logger.info(f"[Creator] Token page URL: {page.url} | Título: {await page.title()}")

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
            logger.error(f"[Creator] ott$ token não encontrado. Corpo: {body_text[:300]}")
            return None, None

        logger.info(f"[Creator] ✅ CONTA CRIADA: {email} | Token: {token[:35]}...")
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
