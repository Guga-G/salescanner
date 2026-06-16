# Persist scanner state and history

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from .parser import ProductSnapshot

STATE_FILE = "state.json"
HISTORY_FILE = "history.jsonl"


@dataclass
class State:
    last_notified_signature: str | None = None
    failure_count: int = 0
    updated_at: str | None = None

    @property
    def deal_active(self) -> bool:
        return bool(self.last_notified_signature)


def load_state(path: str = STATE_FILE) -> State:
    if not os.path.exists(path):
        return State()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return State()
    return State(
        last_notified_signature=data.get("last_notified_signature"),
        failure_count=int(data.get("failure_count", 0)),
        updated_at=data.get("updated_at"),
    )


def save_state(state: State, updated_at: str, path: str = STATE_FILE) -> None:
    state.updated_at = updated_at
    payload = {
        "last_notified_signature": state.last_notified_signature,
        "failure_count": state.failure_count,
        "updated_at": state.updated_at,
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
        fh.write("\n")


def append_history(snapshot: ProductSnapshot, path: str = HISTORY_FILE) -> None:
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot.to_dict(), ensure_ascii=False) + "\n")


def deal_signature(snapshot: ProductSnapshot) -> str:
    # A stable fingerprint of the current deal state
    # Same deal -> same signature, no email spam. A changed price or changed promo
    # set -> different signature (refire)
    bogo = "bogo" if snapshot.is_bogo else ""
    cut = "cut" if snapshot.is_discount else ""
    promos = ",".join(sorted(snapshot.promo_labels))
    price = snapshot.current_price if snapshot.current_price is not None else ""
    return f"{bogo}|{cut}|{promos}|{price}"


def qualifies(snapshot: ProductSnapshot) -> bool:
    # A snapshot qualifies for notification when in stock and showing any promo
    return snapshot.in_stock and (
        snapshot.is_bogo or snapshot.is_discount or len(snapshot.promo_labels) > 0
    )


# Decision outcomes (pure, side effect free; main.py performs the side effects).
DECISION_NOTIFY = "notify"      # qualifying deal that is new or changed
DECISION_UNCHANGED = "unchanged"  # qualifying deal, same as last notified -> no email
DECISION_ENDED = "ended"        # previously active deal no longer qualifies -> clear
DECISION_NONE = "none"          # no deal and none was active


def decide(snapshot: ProductSnapshot, last_signature: str | None) -> tuple[str, str | None]:
    signature = deal_signature(snapshot)
    if qualifies(snapshot):
        if signature != last_signature:
            return DECISION_NOTIFY, signature
        return DECISION_UNCHANGED, signature
    if last_signature:
        return DECISION_ENDED, None
    return DECISION_NONE, None
