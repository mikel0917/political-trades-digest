"""
Delivery: Resend email (primary) + optional Telnyx SMS nudge.

Always writes the digest to disk too, so you have a record and so the tool
"works" even with zero keys configured (100% free / no-account path: just read
the file the cron writes).
"""

import datetime as dt

import requests

import config


def deliver(text_body: str, html_body: str, priority: bool) -> bool:
    """
    Returns True if the digest was delivered (or the file-only fallback was
    intentionally used because no email is configured). Returns False if a
    configured delivery channel failed — caller should NOT mark events notified
    in that case, so they retry on the next run.
    """
    # 1. Always write to disk.
    stamp = dt.date.today().isoformat()
    txt_path = config.OUTPUT_DIR / f"digest-{stamp}.txt"
    html_path = config.OUTPUT_DIR / f"digest-{stamp}.html"
    txt_path.write_text(text_body, encoding="utf-8")
    html_path.write_text(html_body, encoding="utf-8")
    print(f"  [deliver] wrote {txt_path}")

    # 2. Email via Resend if configured.
    email_ok = True  # stays True if email isn't configured (file-only mode)
    if config.RESEND_API_KEY and config.EMAIL_TO:
        email_ok = False
        try:
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {config.RESEND_API_KEY}",
                         "Content-Type": "application/json"},
                json={
                    "from": config.EMAIL_FROM,
                    "to": [config.EMAIL_TO],
                    "subject": f"📈 Trades Digest — {dt.date.today().strftime('%b %d')}"
                               + (" ⚡" if priority else ""),
                    "html": html_body,
                    "text": text_body,
                },
                timeout=15,
            )
            print(f"  [deliver] Resend status {r.status_code}")
            email_ok = 200 <= r.status_code < 300
            if not email_ok:
                print(f"  [deliver] Resend body: {r.text[:300]}")
        except Exception as e:
            print(f"  [deliver] Resend failed: {e}")
    else:
        print("  [deliver] no RESEND_API_KEY/EMAIL_TO — email skipped "
              "(read the file instead).")

    # 3. SMS nudge via Telnyx, only when it matters.
    if config.TELNYX_API_KEY and config.TELNYX_TO and (priority or not config.SMS_ONLY_FOR_PRIORITY):
        try:
            msg = "📈 Trades digest ready"
            if priority:
                msg += " — convergence/watchlist hit today. Check email."
            r = requests.post(
                "https://api.telnyx.com/v2/messages",
                headers={"Authorization": f"Bearer {config.TELNYX_API_KEY}",
                         "Content-Type": "application/json"},
                json={"from": config.TELNYX_FROM, "to": config.TELNYX_TO, "text": msg},
                timeout=15,
            )
            print(f"  [deliver] Telnyx status {r.status_code}")
        except Exception as e:
            print(f"  [deliver] Telnyx failed: {e}")

    return email_ok
