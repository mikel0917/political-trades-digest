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


# ---------------------------------------------------------------------------
# intraday Telegram push (separate from the daily email digest)
# ---------------------------------------------------------------------------

def send_telegram_alert(events, snap_cache, store=None):
    """
    Push a compact alert to Telegram listing the given events. Designed for
    INTRADAY use — called from run.py when DIGEST_MODE=intraday.

    `events` is a list of core.store.Event objects (or dicts with the same
    keys) that just landed and meet the priority bar (watchlist hit or
    convergence trigger). `snap_cache` provides current price snapshots.

    Returns True on success, False otherwise.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("  [telegram] no TELEGRAM_BOT_TOKEN/CHAT_ID — push skipped")
        return False
    if not events:
        return True

    # Build a short HTML-formatted message. Telegram allows <b>, <i>, <code>,
    # <a href=...>, but not <br> — use \n for newlines.
    lines = [f"⚡ <b>Intraday alert — {len(events)} new "
             f"event{'s' if len(events) != 1 else ''}</b>"]
    lines.append("")

    for ev in events[:10]:
        ticker = _get(ev, "ticker") or "—"
        kind = _kind_tag(_get(ev, "kind"))
        actor = _get(ev, "actor") or ""
        headline = (_get(ev, "headline") or "")[:140]
        snap = snap_cache.get(ticker) if ticker != "—" else None

        head = f"<b>{ticker}</b>"
        if ticker in config.WATCHLIST:
            head = f"⭐ {head} <i>({config.WATCHLIST[ticker]})</i>"
        lines.append(f"{head}  —  {kind}")

        if actor and actor not in ("News", "Insider", "Congress"):
            lines.append(f"by <i>{actor}</i>")

        lines.append(headline)

        if snap and snap.get("price"):
            day_bit = ""
            if snap.get("day_pct") is not None:
                arrow = "▲" if snap["day_pct"] >= 0 else "▼"
                day_bit = f" {arrow}{abs(snap['day_pct']):.1f}% today"
            lines.append(f"now ${snap['price']:.2f}{day_bit}")

        url = _get(ev, "url")
        if url:
            lines.append(f'<a href="{url}">source</a>')

        lines.append("")  # blank line between events

    body = "\n".join(lines).strip()

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                "chat_id": config.TELEGRAM_CHAT_ID,
                "text": body[:4000],  # Telegram limit is 4096
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=10,
        )
        print(f"  [telegram] status {r.status_code}")
        ok = 200 <= r.status_code < 300
        if not ok:
            print(f"  [telegram] body: {r.text[:300]}")
        return ok
    except Exception as e:
        print(f"  [telegram] failed: {e}")
        return False


def _get(ev, key):
    """Read a field from either an Event dataclass or a dict."""
    if isinstance(ev, dict):
        return ev.get(key)
    return getattr(ev, key, None)


def send_telegram_digest(text_body):
    """
    Push the FULL daily digest to Telegram, split into chunks at section
    boundaries so each message stays under Telegram's 4096-char limit.
    Plain text (no HTML parsing) — preserves the ASCII tables / cards.

    Independent of email delivery: even if Resend fails, the user still
    gets the digest on Telegram.
    """
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("  [telegram] no token/chat — daily push skipped")
        return False

    chunks = _split_for_telegram(text_body, max_chunk=3800)
    print(f"  [telegram] daily digest split into {len(chunks)} message(s)")

    all_ok = True
    for i, chunk in enumerate(chunks, 1):
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage",
                json={
                    "chat_id": config.TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            ok = 200 <= r.status_code < 300
            print(f"  [telegram] part {i}/{len(chunks)} status {r.status_code}")
            if not ok:
                print(f"  [telegram] body: {r.text[:200]}")
                all_ok = False
        except Exception as e:
            print(f"  [telegram] part {i} failed: {e}")
            all_ok = False
    return all_ok


def _split_for_telegram(text, max_chunk=3800):
    """
    Split text into chunks of at most `max_chunk` chars, preferring to break
    at blank lines / section separators rather than mid-paragraph. Returns
    list of chunks (always at least 1, never empty).
    """
    lines = text.split("\n")
    chunks = []
    current = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_chunk and current:
            # finalize current chunk
            chunks.append("\n".join(current).rstrip())
            current = [line]
            current_len = line_len
        else:
            current.append(line)
            current_len += line_len
    if current:
        chunks.append("\n".join(current).rstrip())
    # if any single line was somehow longer than max_chunk, hard-truncate
    return [c[:max_chunk] for c in chunks if c.strip()]


def _kind_tag(kind):
    return {
        "endorsement":    "📣 ENDORSEMENT",
        "exec_trade":     "🏛️  EXEC TRADE",
        "congress_trade": "🏦 CONGRESS",
        "insider_buy":    "👔 INSIDER BUY",
        "setup":          "🔧 SETUP",
        "news":           "📰 NEWS",
    }.get(kind, (kind or "EVENT").upper())
