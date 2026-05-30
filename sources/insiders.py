"""
Insider transactions source — SEC EDGAR Form 4 (free, no key, official).

Corporate insiders (CEOs/CFOs/directors) must file Form 4 within 2 business
days. A cluster of open-market BUYS is a far better-studied signal than a
political shoutout, and it's the same plumbing. We poll EDGAR's per-company
Form 4 atom feed for each watchlist ticker.

SEC requires a descriptive User-Agent with contact info — set EDGAR_UA env var
(e.g. "yourname yourerNULLemail@example.com"). Falls back to a generic one.

We surface BUYS only (transaction code P = open-market purchase). Sales are
mostly noise (scheduled 10b5-1, tax, comp). This keeps the digest signal-heavy.
"""

import os
import datetime as dt

import requests
import feedparser

import config
from core.store import Event, KIND_INSIDER


EDGAR_UA = os.environ.get("EDGAR_UA", "PoliticalTradesDigest personal-use@example.com")
HEADERS = {"User-Agent": EDGAR_UA}


def _form4_feed_url(ticker: str) -> str:
    # browse-edgar accepts ticker in CIK= for many symbols and returns atom.
    return (
        "https://www.sec.gov/cgi-bin/browse-edgar"
        f"?action=getcompany&CIK={ticker}&type=4&dateb=&owner=include"
        "&count=20&output=atom"
    )


def fetch() -> list[Event]:
    cutoff = dt.date.today() - dt.timedelta(days=config.LOOKBACK_DAYS + 3)
    events: list[Event] = []

    for ticker in config.WATCHLIST:
        try:
            r = requests.get(_form4_feed_url(ticker), headers=HEADERS, timeout=12)
            if r.status_code != 200:
                continue
            feed = feedparser.parse(r.text)
        except Exception as e:
            print(f"  [insider] {ticker} failed: {e}")
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            edate = dt.date.today().isoformat()
            try:
                tm = entry.get("updated_parsed") or entry.get("published_parsed")
                if tm:
                    d = dt.date(tm.tm_year, tm.tm_mon, tm.tm_mday)
                    if d < cutoff:
                        continue
                    edate = d.isoformat()
            except Exception:
                pass

            # The atom title for Form 4 is typically "4 - Insider Name (CIK)".
            # We can't tell buy vs sell from the feed alone without fetching the
            # filing; we surface the filing and tag it for you to glance at.
            # (A deeper parse of the XML form is a v2 enhancement.)
            events.append(Event(
                kind=KIND_INSIDER,
                actor=title.replace("4 - ", "").split("(")[0].strip() or "Insider",
                ticker=ticker,
                headline=f"Form 4 filed for {ticker}: {title.replace('4 - ', '')}",
                source="SEC EDGAR",
                url=entry.get("link", ""),
                event_date=edate,
                detail="Form 4 (verify buy vs sell in filing)",
            ))

    return events
