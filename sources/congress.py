"""
Congressional trades source.

Tries free providers in order; skips silently if no key is configured.
  1. Finnhub  /stock/congressional-trading   (free tier, needs FINNHUB_API_KEY)
  2. FMP      /api/v4/senate-trading + house  (free tier 250/day, needs FMP_API_KEY)

If neither key exists, this source returns [] and the digest still runs on news
+ insider data. The community S3 buckets (House/Senate Stock Watcher) are dead
as of 2026 (HTTP 403), so they're intentionally not used.

We only keep trades by the actors in config.CONGRESS_ACTORS, within LOOKBACK,
on tickers we can use. Amount is the disclosed band (a wide range — not sizing).
"""

import os
import datetime as dt

import requests

import config
from core.store import Event, KIND_CONGRESS_TRADE


FMP_API_KEY = os.environ.get("FMP_API_KEY", "")


def _name_match(name: str) -> bool:
    """True if `name` matches any tracked congressional actor (loose)."""
    low = (name or "").lower()
    return any(actor.lower().split()[-1] in low for actor in config.CONGRESS_ACTORS)


def _from_finnhub() -> list[Event]:
    if not config.FINNHUB_API_KEY:
        return []
    events = []
    cutoff = dt.date.today() - dt.timedelta(days=max(config.CONVERGENCE_WINDOW_DAYS, 30))
    # Finnhub endpoint is per-symbol; query each watchlist ticker.
    for ticker in config.WATCHLIST:
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/stock/congressional-trading",
                params={"symbol": ticker, "token": config.FINNHUB_API_KEY},
                timeout=12,
            )
            data = r.json().get("data", [])
        except Exception as e:
            print(f"  [congress/finnhub] {ticker} failed: {e}")
            continue
        for row in data:
            name = row.get("name", "")
            tdate = row.get("transactionDate", "")[:10]
            try:
                if not tdate or dt.date.fromisoformat(tdate) < cutoff:
                    continue
            except Exception:
                continue
            if config.CONGRESS_ACTORS and not _name_match(name):
                continue
            action = (row.get("transactionType") or "").lower()
            events.append(Event(
                kind=KIND_CONGRESS_TRADE,
                actor=name or "Congress",
                ticker=ticker,
                headline=f"{name} {action} {ticker}",
                source="Finnhub / STOCK Act",
                url="https://www.capitoltrades.com/",
                event_date=tdate,
                detail=f"{row.get('amountFrom','?')}–{row.get('amountTo','?')}",
            ))
    return events


def _from_fmp() -> list[Event]:
    if not FMP_API_KEY:
        return []
    events = []
    cutoff = dt.date.today() - dt.timedelta(days=max(config.CONVERGENCE_WINDOW_DAYS, 30))
    endpoints = [
        ("https://financialmodelingprep.com/api/v4/senate-trading-rss-feed", "Senate"),
        ("https://financialmodelingprep.com/api/v4/senate-disclosure-rss-feed", "House"),
    ]
    for url, chamber in endpoints:
        try:
            r = requests.get(url, params={"page": 0, "apikey": FMP_API_KEY}, timeout=12)
            rows = r.json()
        except Exception as e:
            print(f"  [congress/fmp] {chamber} failed: {e}")
            continue
        if not isinstance(rows, list):
            continue
        for row in rows:
            name = row.get("representative") or row.get("office") or ""
            ticker = (row.get("symbol") or "").upper()
            tdate = (row.get("transactionDate") or row.get("dateRecieved") or "")[:10]
            if not ticker:
                continue
            try:
                if not tdate or dt.date.fromisoformat(tdate) < cutoff:
                    continue
            except Exception:
                continue
            if config.CONGRESS_ACTORS and not _name_match(name):
                continue
            events.append(Event(
                kind=KIND_CONGRESS_TRADE,
                actor=name or f"{chamber} member",
                ticker=ticker,
                headline=f"{name} {row.get('type','traded')} {ticker}",
                source=f"FMP / {chamber}",
                url=row.get("link", "https://www.capitoltrades.com/"),
                event_date=tdate,
                detail=row.get("amount", ""),
            ))
    return events


def fetch() -> list[Event]:
    events = _from_finnhub()
    if not events:
        events = _from_fmp()
    if not (config.FINNHUB_API_KEY or FMP_API_KEY):
        print("  [congress] no FINNHUB_API_KEY or FMP_API_KEY set — skipping "
              "congressional source (digest still runs on news + insiders).")
    return events
