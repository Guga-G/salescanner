# Arrange one scan: fetch -> parse -> decide -> notify -> persist

from __future__ import annotations

import datetime as dt
import os
import sys

from . import notifier, state
from .config import Config, ConfigError, load_config
from .fetcher import FetchError, fetch
from .parser import ParseError, parse

DEBUG_DIR = "debug"
FAILURE_DUMP = os.path.join(DEBUG_DIR, "last-failure.html")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _dump_failure(html: str | None) -> None:
    if not html:
        return
    os.makedirs(DEBUG_DIR, exist_ok=True)
    try:
        with open(FAILURE_DUMP, "w", encoding="utf-8") as fh:
            fh.write(html)
        print(f"[scanner] dumped raw HTML to {FAILURE_DUMP}")
    except OSError as exc:
        print(f"[scanner] could not write failure dump: {exc}")


def _handle_failure(cfg: Config, st: state.State, reason: str, html: str | None) -> int:
    # Record a failed attempt, send if the threshold is reached, persist
    print(f"[scanner] FAILURE: {reason}")
    _dump_failure(html)
    st.failure_count += 1
    if (
        cfg.heartbeat_enabled
        and st.failure_count >= cfg.heartbeat_fail_threshold
        and cfg.can_send_email
    ):
        try:
            notifier.send_heartbeat(cfg, reason, st.failure_count)
            print(f"[scanner] heartbeat email sent (failures={st.failure_count})")
        except notifier.NotifyError as exc:
            print(f"[scanner] heartbeat email failed: {exc}")
    state.save_state(st, _now_iso())
    return 1


def run(cfg: Config) -> int:
    st = state.load_state()

    # Fetch
    try:
        html = fetch(cfg)
    except FetchError as exc:
        return _handle_failure(cfg, st, f"fetch: {exc}", getattr(exc, "html", None))

    # Parse
    captured_at = _now_iso()
    try:
        snapshot = parse(html, cfg.product_url, captured_at)
    except ParseError as exc:
        return _handle_failure(cfg, st, f"parse: {exc}", html)

    # Success path: history always records the snapshot, failure resets
    state.append_history(snapshot)
    st.failure_count = 0

    decision, new_signature = state.decide(snapshot, st.last_notified_signature)
    print(
        f"[scanner] in_stock={snapshot.in_stock} bogo={snapshot.is_bogo} "
        f"discount={snapshot.is_discount} promos={snapshot.promo_labels} "
        f"price={snapshot.current_price} decision={decision}"
    )

    # Act on the decision (side effects only)
    if decision == state.DECISION_NOTIFY:
        if cfg.can_send_email:
            try:
                notifier.send_deal(cfg, snapshot)
                print("[scanner] deal email sent")
                st.last_notified_signature = new_signature
            except notifier.NotifyError as exc:
                # Do not advance the signature, so a later run can retry the email
                print(f"[scanner] deal email failed: {exc}")
        else:
            print("[scanner] qualifying deal found but email not configured; skipping")
            st.last_notified_signature = new_signature
    elif decision == state.DECISION_ENDED:
        print("[scanner] previously active deal no longer qualifies; clearing")
        if cfg.notify_deal_ended and cfg.can_send_email:
            try:
                notifier.send_deal_ended(cfg, snapshot)
                print("[scanner] deal-ended email sent")
            except notifier.NotifyError as exc:
                print(f"[scanner] deal-ended email failed: {exc}")
        st.last_notified_signature = None
    elif decision == state.DECISION_UNCHANGED:
        print("[scanner] deal unchanged since last notification; no email")
    else:
        print("[scanner] no qualifying deal")

    state.save_state(st, captured_at)
    return 0


def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"[scanner] config error: {exc}")
        return 2
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
