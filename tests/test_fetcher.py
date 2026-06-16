# Block-detection tests

import os

from scanner.fetcher import block_reason, looks_blocked

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return fh.read()


def test_real_page_with_recaptcha_is_not_blocked():
    html = _load("bogo.html")
    # Sanity: the good page really does contain these otherwise-suspicious words.
    assert "captcha" in html.lower()
    assert "cf-" in html.lower()
    assert block_reason(html) is None
    assert looks_blocked(html) is False


def test_normal_and_pricecut_fixtures_not_blocked():
    assert looks_blocked(_load("normal.html")) is False
    assert looks_blocked(_load("pricecut.html")) is False


def test_cloudflare_interstitial_is_blocked():
    html = (
        "<!DOCTYPE html><html><head><title>Just a moment...</title></head>"
        "<body>Checking your browser before accessing. "
        "<div class='cf-browser-verification'></div>" + ("x" * 600) + "</body></html>"
    )
    reason = block_reason(html)
    assert reason is not None
    assert "just a moment" in reason or "checking your browser" in reason


def test_empty_and_short_responses_are_blocked():
    assert block_reason("") == "empty response"
    assert "too short" in (block_reason("<html></html>") or "")


def test_missing_price_but_has_title_is_blocked():
    html = '<html><body><h1 class="product-title">X</h1>' + ("y" * 600) + "</body></html>"
    assert block_reason(html) == "price block missing in response"
