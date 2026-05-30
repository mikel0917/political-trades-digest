"""
Price + valuation enrichment. Free by default (yfinance). Finnhub used only
if a key is present.

Two jobs:
  1. current_price(ticker) -> latest price (for event logging + "did I miss it")
  2. snapshot(ticker) -> dict with price, day change %, P/E, 52wk range, etc.
  3. price_on_or_after(ticker, date) -> historical close (for outcome backtest)

yfinance scrapes Yahoo and occasionally breaks/rate-limits. Everything here is
wrapped so a failure degrades gracefully (returns None) rather than crashing the
whole digest.
"""

import datetime as dt
import config

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    import requests
except ImportError:
    requests = None


def _yf_snapshot(ticker: str):
    if yf is None:
        return None
    try:
        t = yf.Ticker(ticker)
        fast = getattr(t, "fast_info", {}) or {}
        price = fast.get("last_price") or fast.get("lastPrice")
        prev = fast.get("previous_close") or fast.get("previousClose")
        info = {}
        try:
            info = t.info or {}
        except Exception:
            info = {}
        if price is None:
            price = info.get("currentPrice") or info.get("regularMarketPrice")
        if prev is None:
            prev = info.get("previousClose")
        day_pct = None
        if price and prev:
            day_pct = (price - prev) / prev * 100
        return {
            "price": price,
            "day_pct": day_pct,
            "pe": info.get("trailingPE"),
            "fwd_pe": info.get("forwardPE"),
            "low52": info.get("fiftyTwoWeekLow"),
            "high52": info.get("fiftyTwoWeekHigh"),
            "target": info.get("targetMeanPrice"),
            "name": info.get("shortName"),
        }
    except Exception:
        return None


def _finnhub_snapshot(ticker: str):
    if not config.FINNHUB_API_KEY or requests is None:
        return None
    try:
        base = "https://finnhub.io/api/v1"
        key = config.FINNHUB_API_KEY
        q = requests.get(f"{base}/quote", params={"symbol": ticker, "token": key}, timeout=10).json()
        m = requests.get(f"{base}/stock/metric",
                         params={"symbol": ticker, "metric": "all", "token": key},
                         timeout=10).json().get("metric", {})
        price = q.get("c")
        prev = q.get("pc")
        day_pct = (q.get("dp") if q.get("dp") is not None
                   else ((price - prev) / prev * 100 if price and prev else None))
        return {
            "price": price,
            "day_pct": day_pct,
            "pe": m.get("peTTM"),
            "fwd_pe": m.get("peForward"),
            "low52": m.get("52WeekLow"),
            "high52": m.get("52WeekHigh"),
            "target": None,
            "name": None,
        }
    except Exception:
        return None


def snapshot(ticker: str):
    """Full enrichment dict, or None. Tries Finnhub first if configured."""
    if not ticker:
        return None
    return _finnhub_snapshot(ticker) or _yf_snapshot(ticker)


def current_price(ticker: str):
    s = snapshot(ticker)
    return s["price"] if s and s.get("price") else None


def price_on_or_after(ticker: str, date_iso: str):
    """
    Historical close on the given date (or the next trading day). Used to fill
    in event_price retroactively and for outcome checks. yfinance only.
    """
    if yf is None or not ticker:
        return None
    try:
        start = dt.date.fromisoformat(date_iso)
        end = start + dt.timedelta(days=6)
        hist = yf.Ticker(ticker).history(start=start.isoformat(), end=end.isoformat())
        if hist is None or hist.empty:
            return None
        return float(hist["Close"].iloc[0])
    except Exception:
        return None


def format_snapshot(s: dict) -> str:
    """One-line human summary for the digest."""
    if not s or not s.get("price"):
        return "price unavailable"
    parts = [f"${s['price']:.2f}"]
    if s.get("day_pct") is not None:
        sign = "+" if s["day_pct"] >= 0 else ""
        parts.append(f"{sign}{s['day_pct']:.1f}% today")
    pe = s.get("pe") or s.get("fwd_pe")
    if pe:
        parts.append(f"P/E ~{pe:.0f}")
    if s.get("low52") and s.get("high52"):
        parts.append(f"52wk ${s['low52']:.0f}-${s['high52']:.0f}")
    return " · ".join(parts)
