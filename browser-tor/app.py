import os, re, time, asyncio, socket, ipaddress
from urllib.parse import urlparse
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.async_api import async_playwright
from stem import Signal
from stem.control import Controller
from readability import Document
import html2text

app = FastAPI()


class BrowseRequest(BaseModel):
    url: str
    wait_selector: str | None = None
    extract_text: bool = True
    block_media: bool = True
    js_enabled: bool = True


TOR_PROXY = {"server": "socks5://tor-proxy:9150"}
CONTROL_PASSWORD = os.environ.get("TOR_CONTROL_PASSWORD")
if not CONTROL_PASSWORD:
    raise RuntimeError(
        "TOR_CONTROL_PASSWORD is required. "
        "Set it in the environment before starting this container."
    )


FIREFOX_PREFS = {
    "media.peerconnection.enabled": False,
    "network.dns.disablePrefetch": True,
    "network.prefetch-next": False,
    "geo.enabled": False,
    "privacy.resistFingerprinting": True,
    "privacy.resistFingerprinting.letterboxing": True,
    "privacy.spoof_english": 2,
    "webgl.disabled": True,
    "dom.battery.enabled": False,
    "device.sensors.enabled": False,
    "media.navigator.enabled": False,
    "network.proxy.socks_remote_dns": True,
}


# Extended cookie killer (aligned with browser-clear)
COOKIE_KILLER_JS = """
async () => {
    const CMP_SELECTORS = [
        '#onetrust-banner-sdk', '#onetrust-consent-sdk',
        '#cookiebot', '#CybotCookiebotDialog',
        '.qc-cmp2-container', '#qc-cmp2-container',
        '#truste-consent-track', '.truste_box_overlay',
        '.cc-window', '.fc-consent-root', '#cookie-notice',
        '.paywall', '[class*="cookie-banner"]', '[id*="cookie-consent"]',
        '#iubenda-cs-banner', '.iubenda-cs-container', '.iubenda-cs-visible',
        '[class*="iubenda"]', 'iframe[src*="iubenda"]',
        '#didomi-host', '#didomi-notice', '.didomi-popup-backdrop',
        '[class*="didomi"]',
        '.cmplz-cookiebanner', '.cmplz-manage-consent',
        '.cky-consent-container', '.cky-modal',
        '.cli-modal-backdrop', '#cookie-law-info-bar',
        '.termly-cookie-policy',
        '.klaro .cookie-modal', '.klaro .cookie-notice',
        '#ccpa-banner',
        '.fc-dialog-overlay',
        '#gdpr-banner', '.gdpr-banner',
    ];
    CMP_SELECTORS.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            el.style.setProperty('display', 'none', 'important');
            el.style.setProperty('visibility', 'hidden', 'important');
        });
    });
    document.documentElement.style.setProperty('overflow', 'auto', 'important');
    if (document.body) {
        document.body.style.setProperty('overflow', 'auto', 'important');
    }
    return 'cookie-killer: done';
}
"""


NUMERIC_HOST = re.compile(r"(0x[0-9a-f]+|\d+)(\.(0x[0-9a-f]+|\d+))*")


def validate_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("schema non consentito")
    host = (u.hostname or "").lower()
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        raise ValueError("host non consentito")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not ip.is_global:
            raise ValueError("IP non pubblico")
    elif NUMERIC_HOST.fullmatch(host):
        raise ValueError("host numerico ambiguo")
    elif "." not in host:
        raise ValueError("host senza dominio (rete interna?)")


def _newnym_sync() -> None:
    ip = socket.gethostbyname("tor-proxy")
    with Controller.from_port(address=ip, port=9151) as c:
        c.authenticate(password=CONTROL_PASSWORD)
        wait = c.get_newnym_wait()
        if wait > 0:
            time.sleep(min(wait, 12))
        c.signal(Signal.NEWNYM)


async def renew_circuit() -> bool:
    try:
        await asyncio.to_thread(_newnym_sync)
        await asyncio.sleep(1)
        return True
    except Exception as e:
        print(f"[warn] NEWNYM failed: {e}")
        return False


def pulisci_testo(html_content: str) -> str:
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.ignore_images = True
    h.body_width = 0

    try:
        doc = Document(html_content)
        testo_pulito = h.handle(doc.summary()).strip()
        if testo_pulito:
            return testo_pulito
    except Exception:
        pass

    try:
        return h.handle(html_content).strip()
    except Exception as e:
        return f"Extraction error: {e}"


@app.post("/browse")
async def browse(req: BrowseRequest):
    try:
        validate_url(req.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    renewed = await renew_circuit()
    if not renewed and os.environ.get("TOR_REQUIRE_NEWNYM") == "1":
        return {"error": "circuit renewal failed", "circuit_renewed": False,
                "title": "", "final_url": req.url, "text": ""}

    async with async_playwright() as p:
        browser = await p.firefox.launch(
            headless=True, proxy=TOR_PROXY, firefox_user_prefs=FIREFOX_PREFS)
        try:
            context = await browser.new_context(
                viewport={"width": 1000, "height": 900},
                timezone_id="UTC", locale="en-US",
                java_script_enabled=req.js_enabled)
            page = await context.new_page()
            if req.block_media:
                await page.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,mp4,webm}",
                                 lambda route: route.abort())
            try:
                await page.goto(req.url, wait_until="domcontentloaded", timeout=45000)
                if req.wait_selector:
                    try:
                        await page.wait_for_selector(req.wait_selector, timeout=10000)
                    except Exception as e:
                        print(f"[warn] wait_selector '{req.wait_selector}' not found: {e}")
                await page.wait_for_timeout(2500)
            except Exception as e:
                return {"error": f"Navigation failed: {e}", "circuit_renewed": renewed,
                        "title": "", "final_url": req.url, "text": ""}
            if req.js_enabled:
                try:
                    await page.evaluate(COOKIE_KILLER_JS)
                except Exception as e:
                    print(f"[warn] Cookie killer failed: {e}")
            result = {"title": await page.title(), "final_url": page.url,
                      "circuit_renewed": renewed}
            if req.extract_text:
                result["text"] = pulisci_testo(await page.content())
            return result
        finally:
            await browser.close()


@app.get("/health")
async def health():
    return {"status": "ok"}
