# Fetch the product page HTML through a configurable backend

from __future__ import annotations

from urllib.parse import quote, urlencode

import requests

from .config import Config

SCRAPERAPI_ENDPOINT = "https://api.scraperapi.com/"

_CHALLENGE_MARKERS = [
    "just a moment",
    "attention required",
    "checking your browser",
    "verify you are human",
    "enable javascript and cookies to continue",
    "cf-browser-verification",
    "cf-challenge",
    "cf-mitigated",
    "/cdn-cgi/challenge-platform",
    "px-captcha",
    "datadome",
    "access denied",
]


class FetchError(RuntimeError):
    # Raised when the page cannot be fetched or comes back blocked

    def __init__(self, message: str, html: str | None = None):
        super().__init__(message)
        self.html = html


def block_reason(html: str) -> str | None:
    # Return a short reason if the HTML looks blocked/unusable, else = None
    if not html:
        return "empty response"
    if len(html) < 500:
        return f"response too short ({len(html)} bytes)"
    lowered = html.lower()
    has_title = 'class="product-title"' in lowered or 'itemprop="name"' in lowered
    has_price = 'class="price"' in lowered or 'itemprop="price"' in lowered
    if has_title and has_price:
        return None
    for marker in _CHALLENGE_MARKERS:
        if marker in lowered:
            return f"challenge marker found: {marker!r}"
    if not has_title and not has_price:
        return "no product title and no price block in response"
    if not has_title:
        return "product title block missing in response"
    return "price block missing in response"


def looks_blocked(html: str) -> bool:
    return block_reason(html) is not None


def _product_url(cfg: Config) -> str:
    url = cfg.product_url
    if cfg.store_view and "___store=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}___store={cfg.store_view}"
    return url


def _fetch_api(cfg: Config) -> str:
    target = _product_url(cfg)
    params = {
        "api_key": cfg.scraper_api_key,
        "country_code": cfg.store_view or "us",
        "url": target,
    }

    if cfg.scraper_render:
        params["render"] = "true"
    if cfg.scraper_ultra_premium:
        params["ultra_premium"] = "true"

    # Build the query manually so the target URL is properly percent-encoded.
    query = urlencode(params, quote_via=quote)
    endpoint = f"{SCRAPERAPI_ENDPOINT}?{query}"
    try:
        resp = requests.get(endpoint, timeout=120)
    except requests.RequestException as exc:
        raise FetchError(f"ScraperAPI request failed: {exc}") from exc
    if resp.status_code != 200:
        # ScraperAPI puts the upstream/error detail in the body
        raise FetchError(
            f"ScraperAPI returned HTTP {resp.status_code}: {resp.text[:300]}",
            html=resp.text,
        )
    return resp.text


def _fetch_browser(cfg: Config) -> str:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise FetchError(
            "FETCH_MODE=browser needs Playwright. Install with: "
            "pip install playwright && python -m playwright install chromium"
        ) from exc

    url = _product_url(cfg)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1366, "height": 900},
                locale="en-US",
            )
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(1500)
            return page.content()
        finally:
            browser.close()


API_MAX_ATTEMPTS = 3


def _snippet(html: str | None, limit: int = 600) -> str:
    if not html:
        return "<empty>"
    return " ".join(html[:limit].split())


def _fetch_api_with_retries(cfg: Config) -> str:
    # Fetch via ScraperAPI, retrying the block-prone basic proxy a few times
    last_html: str | None = None
    for attempt in range(1, API_MAX_ATTEMPTS + 1):
        last_html = _fetch_api(cfg)
        reason = block_reason(last_html)
        if reason is None:
            return last_html
        print(
            f"[scanner] api fetch attempt {attempt}/{API_MAX_ATTEMPTS} blocked "
            f"({reason}); body starts: {_snippet(last_html, 300)}"
        )
    raise FetchError(
        f"api fetch blocked after {API_MAX_ATTEMPTS} attempts: {block_reason(last_html)}",
        html=last_html,
    )


def fetch(cfg: Config) -> str:
    # Fetch and return page HTML, raising FetchError if blocked or unavailable
    if cfg.fetch_mode == "api":
        return _fetch_api_with_retries(cfg)

    # browser mode
    html = _fetch_browser(cfg)
    if looks_blocked(html):
        if cfg.scraper_api_key:
            return _fetch_api_with_retries(cfg)
        raise FetchError(
            "browser fetch blocked and no SCRAPER_API_KEY to fall back to", html=html
        )
    return html
