# Parse a muscleandstrength.com product page into a ProductSnapshot.

from __future__ import annotations

import re
from dataclasses import dataclass, asdict, field

from bs4 import BeautifulSoup


class ParseError(RuntimeError):
    """Raised when the page cannot be parsed into a usable snapshot."""


# Badge text patterns. Each entry: (label_for_signature, compiled_regex)
# Scanned case-insensitively over promo regions of the page.
_BADGE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("buy 1 get 1", re.compile(r"buy\s*1\s*get\s*1", re.I)),
    ("bogo", re.compile(r"\bbogo\b", re.I)),
    ("price cut", re.compile(r"price\s*cut", re.I)),
    ("limited time", re.compile(r"limited\s*time", re.I)),
    ("percent off", re.compile(r"\d+\s*%\s*(?:off|discount)", re.I)),
    ("discount in cart", re.compile(r"discount\s*in\s*cart", re.I)),
    ("buy 2 for", re.compile(r"buy\s*2\s*for", re.I)),
]

_BOGO_RE = re.compile(r"buy\s*1\s*get\s*1|\bbogo\b", re.I)
# Badges that on their own signal a discount even when no strikethrough exists
_SAVINGS_RE = re.compile(
    r"price\s*cut|\d+\s*%\s*(?:off|discount)|discount\s*in\s*cart|\bsave\b", re.I
)

# Elements that when present carry clean human-readable badge text worth keeping
# verbatim in promo_labels
_BADGE_SELECTORS = [
    ".deal-label",
    ".mns-label",
    ".lbl-deal",
    ".deal-desc",
    ".deal-title",
    ".price-cut",
    ".savings-badge",
]

# Wider regions scanned with the regexes so a savings pattern is caught even if it
# lives outside a known badge element
_PROMO_REGION_SELECTORS = [
    ".product-shop",
    ".product-info",
    ".deals-coupons-section",
    ".price-box",
    ".product-title-wrap",
]

# Price selectors, most specific first. The first match that parses to a number wins
_CURRENT_PRICE_SELECTORS = [
    '[data-price-type="finalPrice"] .price',
    ".special-price .price",
    ".regular-price .price",
    ".price-box .price",
]
_OLD_PRICE_SELECTORS = [
    '[data-price-type="oldPrice"] .price',
    ".old-price .price",
    "del .price",
]

_PRICE_RE = re.compile(r"[-+]?\d[\d,]*\.?\d*")


@dataclass
class ProductSnapshot:
    captured_at: str
    url: str
    in_stock: bool
    currency: str
    regular_price: float | None
    current_price: float | None
    promo_labels: list[str] = field(default_factory=list)
    is_bogo: bool = False
    is_discount: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


def _money_to_float(text: str | None) -> float | None:
    if not text:
        return None
    match = _PRICE_RE.search(text.replace(",", ""))
    if not match:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def _first_price(soup: BeautifulSoup, selectors: list[str]) -> float | None:
    for selector in selectors:
        for node in soup.select(selector):
            value = _money_to_float(node.get_text(" ", strip=True))
            if value is not None:
                return value
    return None


def _meta_price(soup: BeautifulSoup) -> float | None:
    node = soup.select_one('meta[itemprop="price"]')
    if node and node.get("content"):
        return _money_to_float(node["content"])
    return None


def _currency(soup: BeautifulSoup) -> str:
    node = soup.select_one('meta[itemprop="priceCurrency"]')
    if node and node.get("content"):
        return node["content"].strip().upper()
    return "USD"


def _in_stock(soup: BeautifulSoup) -> bool:
    # Primary signal: the schema.org availability link in the offer block
    links = soup.select('[itemprop="availability"]')
    if links:
        hrefs = " ".join((n.get("href", "") or n.get("content", "")) for n in links)
        if re.search(r"InStock", hrefs, re.I):
            return True
        if re.search(r"OutOfStock|SoldOut", hrefs, re.I):
            return False
    # An add-to-cart form usually means buyable; an out of stock notice
    # signals otherwise. The back-in-stock modal is always in the DOM, hidden
    # Treat a visible out of stock label as a signal
    if soup.select_one("#product_addtocart_form, .add-to-cart, .btn-cart"):
        return True
    text = soup.get_text(" ", strip=True).lower()
    if "out of stock" in text or "sold out" in text:
        return False
    return True


def _collect_promo_labels(soup: BeautifulSoup) -> list[str]:
    """Keep verbatim text of badge elements that match a promo pattern"""
    labels: list[str] = []
    seen: set[str] = set()
    for selector in _BADGE_SELECTORS:
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if not text:
                continue
            if not any(pat.search(text) for _, pat in _BADGE_PATTERNS):
                continue
            key = text.lower()
            if key not in seen:
                seen.add(key)
                labels.append(text)
    return labels


def _promo_region_text(soup: BeautifulSoup, labels: list[str]) -> str:
    parts = list(labels)
    for selector in _PROMO_REGION_SELECTORS:
        for node in soup.select(selector):
            parts.append(node.get_text(" ", strip=True))
    return " ".join(parts)


def parse(html: str, url: str, captured_at: str) -> ProductSnapshot:
    # Turn page HTML into a ProductSnapshot. Raises ParseError on no price block
    soup = BeautifulSoup(html, "html.parser")

    title = soup.select_one('h1.product-title, [itemprop="name"]')
    current_price = _first_price(soup, _CURRENT_PRICE_SELECTORS)
    if current_price is None:
        current_price = _meta_price(soup)

    # A page with no title & no price is not a product page we understand
    if current_price is None and title is None:
        raise ParseError("no price block and no product title found")
    if current_price is None:
        raise ParseError("no current price selector matched")

    regular_price = _first_price(soup, _OLD_PRICE_SELECTORS)

    promo_labels = _collect_promo_labels(soup)
    region_text = _promo_region_text(soup, promo_labels)

    is_bogo = bool(_BOGO_RE.search(region_text))
    price_drop = (
        regular_price is not None
        and current_price is not None
        and current_price < regular_price
    )
    is_discount = bool(price_drop or _SAVINGS_RE.search(region_text))

    return ProductSnapshot(
        captured_at=captured_at,
        url=url,
        in_stock=_in_stock(soup),
        currency=_currency(soup),
        regular_price=regular_price,
        current_price=current_price,
        promo_labels=promo_labels,
        is_bogo=is_bogo,
        is_discount=is_discount,
    )
