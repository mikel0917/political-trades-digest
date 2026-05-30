#!/usr/bin/env python3
"""
Main orchestrator. Run daily from cron:

    cd /opt/political-trades-digest && python3 run.py

Flow:
  1. Collect events from all sources (news, congress, insiders).
  2. Upsert into the store (dedup happens here; repeats bump source_count).
  3. For each NEW event with a ticker, record the event_price (for backtest).
  4. Update outcomes for events that hit +1/+7/+30 day horizons.
  5. Detect convergences over the rolling window.
  6. Build + deliver the digest. Mark events notified.

Every source is wrapped so one failure can't kill the run.
"""

import datetime as dt
import sys
import traceback

import config
from core.store import Store
from core import convergence, digest, enrich, tickers
from delivery import send

# sources
from sources import news, congress, insiders


def safe_fetch(name, fn):
    try:
        evs = fn()
        print(f"  [{name}] {len(evs)} events")
        return evs
    except Exception as e:
        print(f"  [{name}] ERROR: {e}")
        traceback.print_exc()
        return []


def main():
    print("=== Political & Insider Trades Digest ===")
    store = Store()

    # 1. collect
    print("Collecting sources...")
    all_events = []
    all_events += safe_fetch("news", news.fetch)
    all_events += safe_fetch("congress", congress.fetch)
    all_events += safe_fetch("insiders", insiders.fetch)

    # 2. store + dedup
    new_keys = []
    for ev in all_events:
        if store.upsert_event(ev):
            new_keys.append(ev.dedup_key())
    print(f"{len(new_keys)} new unique events after dedup")

    # 3. record event_price for new ticker'd events — at the EVENT date, not today.
    # Most congressional/OGE trades arrive 30-45 days late; pricing them at "now"
    # would make every backtest column 0%.
    for ev in all_events:
        if ev.ticker and ev.dedup_key() in new_keys:
            price = enrich.price_on_or_after(ev.ticker, ev.event_date)
            if not price:
                price = enrich.current_price(ev.ticker)
            if price:
                store.set_event_price(ev.dedup_key(), price)

    # 4. update outcomes — only at horizons that have actually elapsed since
    # event_date. Without this, a freshly-seen 45-day-old event fires +1d,
    # +7d, +30d all in one run against today's price (= meaningless 0% rows).
    for horizon in config.OUTCOME_HORIZONS_DAYS:
        due = store.events_needing_outcome(horizon)
        for ev in due:
            # price the outcome at event_date + horizon, not today
            target_date = (dt.date.fromisoformat(ev["event_date"])
                           + dt.timedelta(days=horizon)).isoformat()
            price = enrich.price_on_or_after(ev["ticker"], target_date)
            if price and ev.get("event_price"):
                store.record_outcome(ev["dedup_key"], horizon, price, ev["event_price"])
        if due:
            print(f"  [outcomes] updated {len(due)} at +{horizon}d")

    # 5. convergence
    convergences = convergence.detect(store)
    print(f"{len(convergences)} convergence(s) detected")

    # 6. build digest from unnotified events
    new_events = store.unnotified_events()

    # price snapshot cache (one lookup per ticker)
    snap_cache = {}
    tickers_needed = {e["ticker"] for e in new_events if e.get("ticker")}
    tickers_needed |= set(convergences.keys())
    for t in tickers_needed:
        snap_cache[t] = enrich.snapshot(t)

    backtest = store.backtest_summary()

    # FRESH (last 24h) — pulled by event_date, NOT by notified status, so the
    # user keeps seeing today/yesterday's items at the top even if they were
    # in yesterday's digest. Recency-by-date, not recency-by-first-seen.
    from core import briefing as _briefing_mod
    fresh_24h = store.recent_events(_briefing_mod.FRESH_DAYS)
    # also include the prices for fresh tickers
    for e in fresh_24h:
        if e.get("ticker") and e["ticker"] not in snap_cache:
            snap_cache[e["ticker"]] = enrich.snapshot(e["ticker"])

    text_body = digest.build_text(new_events, convergences, backtest, snap_cache, fresh_24h)
    html_body = digest.build_html(new_events, convergences, backtest, snap_cache, fresh_24h)

    # priority = anything worth an SMS: a convergence, or a watchlist event
    priority = bool(convergences) or any(
        e.get("ticker") in config.WATCHLIST for e in new_events
    )

    delivered = send.deliver(text_body, html_body, priority)

    # Only mark events as notified if delivery actually succeeded — otherwise a
    # Resend outage would silently drop them from tomorrow's digest forever.
    # When no delivery is configured (e.g. zero-config local run that just writes
    # the file), we still mark them so the file output isn't repeated daily.
    if delivered:
        store.mark_notified([e["dedup_key"] for e in new_events])
    else:
        print("  [notify] delivery failed — leaving events unnotified for retry next run")
    store.close()
    print("Done.")


if __name__ == "__main__":
    sys.exit(main())
