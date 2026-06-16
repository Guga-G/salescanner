# Send notification email via Resend (HTML + plain text)

from __future__ import annotations

import requests

from .config import Config
from .parser import ProductSnapshot

RESEND_ENDPOINT = "https://api.resend.com/emails"

# The clean product URL is always what we link to, regardless of any ___store params
# used during fetching.
CLEAN_PRODUCT_URL = (
    "https://www.muscleandstrength.com/store/r1-charged-creatine.html"
)
PRODUCT_NAME = "R1 Charged Creatine"

# ----------------------------------------------------------------------------------
# Editable copy
# ----------------------------------------------------------------------------------
SUBJECT_DEAL = "\U0001F525 Deal on {product} - {headline}"
SUBJECT_ENDED = "Deal ended on {product}"
SUBJECT_HEARTBEAT = "⚠️ Price scanner needs attention"

FOOTER_REASON = "sent because the price scanner found a deal"
BUTTON_LABEL = "View the deal"


class NotifyError(RuntimeError):
    # Raised when Resend rejects the send


def _fmt_price(value: float | None, currency: str) -> str:
    if value is None:
        return ""
    symbol = "$" if currency.upper() == "USD" else f"{currency} "
    return f"{symbol}{value:,.2f}"


def _pct_off(regular: float | None, current: float | None) -> int | None:
    if regular and current and regular > 0 and current < regular:
        return round((regular - current) / regular * 100)
    return None


def build_headline(snapshot: ProductSnapshot) -> str:
    if snapshot.is_bogo:
        return "Buy 1 Get 1 FREE"
    pct = _pct_off(snapshot.regular_price, snapshot.current_price)
    if snapshot.is_discount and pct is not None:
        return f"{pct}% off - now {_fmt_price(snapshot.current_price, snapshot.currency)}"
    if snapshot.promo_labels:
        return snapshot.promo_labels[0]
    return "Deal available"


def _deal_lines(snapshot: ProductSnapshot) -> list[str]:
    lines: list[str] = []
    if snapshot.promo_labels:
        lines.append("Promo: " + "; ".join(snapshot.promo_labels))
    current = _fmt_price(snapshot.current_price, snapshot.currency)
    if current:
        lines.append(f"Current price: {current}")
    pct = _pct_off(snapshot.regular_price, snapshot.current_price)
    if snapshot.regular_price and pct is not None:
        regular = _fmt_price(snapshot.regular_price, snapshot.currency)
        lines.append(f"Regular price: {regular} ({pct}% off)")
    lines.append("In stock: yes")
    return lines


def render_deal_text(snapshot: ProductSnapshot) -> str:
    headline = build_headline(snapshot)
    lines = [f"{PRODUCT_NAME}: {headline}", ""]
    lines.extend(_deal_lines(snapshot))
    lines.extend(
        [
            "",
            f"Product page: {CLEAN_PRODUCT_URL}",
            "",
            f"{snapshot.captured_at} - {FOOTER_REASON}",
        ]
    )
    return "\n".join(lines)


def render_deal_html(snapshot: ProductSnapshot) -> str:
    headline = build_headline(snapshot)
    items = "".join(f"<li>{line}</li>" for line in _deal_lines(snapshot))
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0;text-align:left">
  <h2 style="margin:0 0 4px">{PRODUCT_NAME}</h2>
  <p style="font-size:18px;font-weight:bold;color:#0a7d33;margin:0 0 16px">{headline}</p>
  <ul style="font-size:15px;line-height:1.6;padding-left:20px">{items}</ul>
  <p style="margin:24px 0">
    <a href="{CLEAN_PRODUCT_URL}"
       style="background:#0a7d33;color:#fff;text-decoration:none;padding:12px 22px;
              border-radius:6px;font-weight:bold;display:inline-block">{BUTTON_LABEL}</a>
  </p>
  <hr style="border:none;border-top:1px solid #ddd">
  <p style="font-size:12px;color:#888">{snapshot.captured_at} - {FOOTER_REASON}</p>
</div>"""


def render_ended_text(snapshot: ProductSnapshot) -> str:
    return (
        f"The previously active deal on {PRODUCT_NAME} no longer qualifies.\n\n"
        f"Product page: {CLEAN_PRODUCT_URL}\n\n"
        f"{snapshot.captured_at} - price scanner update"
    )


def render_ended_html(snapshot: ProductSnapshot) -> str:
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0;text-align:left">
  <h2 style="margin:0 0 8px">{PRODUCT_NAME}</h2>
  <p style="font-size:15px">The previously active deal no longer qualifies.</p>
  <p><a href="{CLEAN_PRODUCT_URL}">{CLEAN_PRODUCT_URL}</a></p>
  <hr style="border:none;border-top:1px solid #ddd">
  <p style="font-size:12px;color:#888">{snapshot.captured_at} - price scanner update</p>
</div>"""


def render_heartbeat_text(reason: str, fail_count: int) -> str:
    return (
        "The price scanner has failed "
        f"{fail_count} run(s) in a row and may be broken.\n\n"
        f"Most recent reason: {reason}\n\n"
        "Check debug/last-failure.html and the workflow logs. A real deal could be "
        "going unreported while this is broken."
    )


def render_heartbeat_html(reason: str, fail_count: int) -> str:
    return f"""\
<div style="font-family:Arial,Helvetica,sans-serif;max-width:560px;margin:0;text-align:left">
  <h2 style="margin:0 0 8px">Price scanner needs attention</h2>
  <p style="font-size:15px">The scanner has failed <b>{fail_count}</b> run(s) in a row
     and may be broken.</p>
  <p style="font-size:14px;color:#444">Most recent reason: {reason}</p>
  <p style="font-size:13px;color:#888">Check debug/last-failure.html and the workflow
     logs. A real deal could be going unreported while this is broken.</p>
</div>"""


def _send(cfg: Config, subject: str, html: str, text: str) -> None:
    if not cfg.can_send_email:
        raise NotifyError(
            "email not configured (need RESEND_API_KEY, EMAIL_FROM, EMAIL_TO)"
        )
    payload = {
        "from": cfg.email_from,
        "to": [cfg.email_to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    headers = {
        "Authorization": f"Bearer {cfg.resend_api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(RESEND_ENDPOINT, json=payload, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise NotifyError(f"Resend request failed: {exc}") from exc
    if resp.status_code >= 300:
        raise NotifyError(f"Resend returned HTTP {resp.status_code}: {resp.text[:300]}")


def send_deal(cfg: Config, snapshot: ProductSnapshot) -> None:
    subject = SUBJECT_DEAL.format(product=PRODUCT_NAME, headline=build_headline(snapshot))
    _send(cfg, subject, render_deal_html(snapshot), render_deal_text(snapshot))


def send_deal_ended(cfg: Config, snapshot: ProductSnapshot) -> None:
    subject = SUBJECT_ENDED.format(product=PRODUCT_NAME)
    _send(cfg, subject, render_ended_html(snapshot), render_ended_text(snapshot))


def send_heartbeat(cfg: Config, reason: str, fail_count: int) -> None:
    _send(
        cfg,
        SUBJECT_HEARTBEAT,
        render_heartbeat_html(reason, fail_count),
        render_heartbeat_text(reason, fail_count),
    )
