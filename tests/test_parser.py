# Parser tests against real (bogo) and hand-crafted (normal, pricecut) fixtures

import os

import pytest

from scanner.parser import ParseError, parse

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
URL = "https://www.muscleandstrength.com/store/r1-charged-creatine.html"
WHEN = "2026-06-16T05:00:00+00:00"


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as fh:
        return fh.read()


def _parse(name: str):
    return parse(_load(name), URL, WHEN)


def test_bogo_fixture_real_markup():
    snap = _parse("bogo.html")
    assert snap.in_stock is True
    assert snap.currency == "USD"
    assert snap.current_price == 19.99
    # BOGO leaves the listed price unchanged: no strikethrough/old price.
    assert snap.regular_price is None
    assert snap.is_bogo is True
    # A BOGO is NOT a price discount.
    assert snap.is_discount is False
    # Promo text was read from badge elements, not derived from price.
    assert snap.promo_labels
    assert any("buy 1 get 1" in label.lower() for label in snap.promo_labels)


def test_normal_fixture_no_promo():
    snap = _parse("normal.html")
    assert snap.in_stock is True
    assert snap.currency == "USD"
    assert snap.current_price == 24.99
    assert snap.regular_price is None
    assert snap.is_bogo is False
    assert snap.is_discount is False
    assert snap.promo_labels == []


def test_pricecut_fixture_strikethrough_and_badge():
    snap = _parse("pricecut.html")
    assert snap.in_stock is True
    assert snap.current_price == 29.99
    assert snap.regular_price == 39.99
    assert snap.is_bogo is False
    # Discount via both the price drop and a savings badge.
    assert snap.is_discount is True
    assert snap.promo_labels
    assert any("%" in label or "price cut" in label.lower() for label in snap.promo_labels)


def test_missing_price_raises_parse_error():
    with pytest.raises(ParseError):
        parse("<html><body><p>nothing here</p></body></html>", URL, WHEN)
