# Decision-logic tests: new deal fires, repeat does not, changed price refires,
# out of stock does not fire. Plus signature stability and state round-trip

import os

from scanner.parser import ProductSnapshot
from scanner.state import (
    DECISION_ENDED,
    DECISION_NONE,
    DECISION_NOTIFY,
    DECISION_UNCHANGED,
    State,
    decide,
    deal_signature,
    load_state,
    qualifies,
    save_state,
)

WHEN = "2026-06-16T05:00:00+00:00"


def _snap(**kw) -> ProductSnapshot:
    base = dict(
        captured_at=WHEN,
        url="https://example.com",
        in_stock=True,
        currency="USD",
        regular_price=None,
        current_price=19.99,
        promo_labels=["Buy 1 Get 1 FREE"],
        is_bogo=True,
        is_discount=False,
    )
    base.update(kw)
    return ProductSnapshot(**base)


def test_new_deal_fires():
    snap = _snap()
    decision, sig = decide(snap, last_signature=None)
    assert decision == DECISION_NOTIFY
    assert sig == deal_signature(snap)


def test_repeat_same_deal_does_not_fire():
    snap = _snap()
    sig = deal_signature(snap)
    decision, new_sig = decide(snap, last_signature=sig)
    assert decision == DECISION_UNCHANGED
    assert new_sig == sig


def test_changed_price_refires():
    first = _snap(current_price=19.99)
    last_sig = deal_signature(first)
    # Same BOGO promo but the price changed -> different signature -> re-fire.
    second = _snap(current_price=14.99)
    decision, sig = decide(second, last_signature=last_sig)
    assert decision == DECISION_NOTIFY
    assert sig != last_sig


def test_changed_promo_set_refires():
    first = _snap(promo_labels=["Buy 1 Get 1 FREE"])
    last_sig = deal_signature(first)
    second = _snap(promo_labels=["Buy 2 for $30"], is_bogo=False, is_discount=True)
    decision, _ = decide(second, last_signature=last_sig)
    assert decision == DECISION_NOTIFY


def test_out_of_stock_does_not_fire():
    snap = _snap(in_stock=False)
    assert qualifies(snap) is False
    decision, sig = decide(snap, last_signature=None)
    assert decision == DECISION_NONE
    assert sig is None


def test_out_of_stock_clears_active_deal():
    active_sig = deal_signature(_snap())
    snap = _snap(in_stock=False)
    decision, sig = decide(snap, last_signature=active_sig)
    assert decision == DECISION_ENDED
    assert sig is None


def test_deal_disappears_clears_when_previously_active():
    active_sig = deal_signature(_snap())
    gone = _snap(promo_labels=[], is_bogo=False, is_discount=False)
    decision, sig = decide(gone, last_signature=active_sig)
    assert decision == DECISION_ENDED
    assert sig is None


def test_no_deal_and_none_active_is_noop():
    gone = _snap(promo_labels=[], is_bogo=False, is_discount=False)
    decision, sig = decide(gone, last_signature=None)
    assert decision == DECISION_NONE
    assert sig is None


def test_state_round_trip(tmp_path):
    path = os.path.join(tmp_path, "state.json")
    st = State(last_notified_signature="bogo||Buy 1 Get 1 FREE|19.99", failure_count=2)
    save_state(st, WHEN, path=path)
    loaded = load_state(path=path)
    assert loaded.last_notified_signature == "bogo||Buy 1 Get 1 FREE|19.99"
    assert loaded.failure_count == 2
    assert loaded.updated_at == WHEN
    assert loaded.deal_active is True


def test_load_missing_state_is_empty(tmp_path):
    loaded = load_state(path=os.path.join(tmp_path, "nope.json"))
    assert loaded.last_notified_signature is None
    assert loaded.failure_count == 0
    assert loaded.deal_active is False
