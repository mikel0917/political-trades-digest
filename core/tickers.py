"""
Ticker resolution: turn free text ("Trump told everyone to buy a Dell") into a
ticker symbol (DELL).

Strategy, cheapest-first:
  1. Explicit cashtag/paren ticker:  $PLTR  or  (PLTR)
  2. Company-name dictionary (watchlist names + common big names)
  3. Give up -> return None (item still shown as unmatched news if relevant)

No paid NER. This is deliberately simple and free. The name dictionary is the
main lever — add aliases as you notice misses.
"""

import re
import config

# Company name -> ticker. Built from the watchlist plus common aliases and a
# handful of frequently-Trump-mentioned names. Extend as needed.
NAME_TO_TICKER = {
    "rocket lab": "RKLB",
    "micron": "MU",
    "destiny tech100": "DXYZ", "destiny tech": "DXYZ",
    "palantir": "PLTR",
    "adobe": "ADBE",
    "intel": "INTC",
    "dell": "DELL", "dell technologies": "DELL",
    "broadcom": "AVGO",
    "synopsys": "SNPS",
    "cadence": "CDNS", "cadence design": "CDNS",
    "texas instruments": "TXN",
    "nvidia": "NVDA",
    "robinhood": "HOOD",
    # common extras worth catching even if not on the watchlist
    "apple": "AAPL", "tesla": "TSLA", "boeing": "BA",
    "lockheed": "LMT", "lockheed martin": "LMT",
    "amazon": "AMZN", "microsoft": "MSFT", "meta": "META",
    "trump media": "DJT", "truth social": "DJT",
    "coinbase": "COIN", "amd": "AMD",
    # NOTE: "meta" intentionally excluded — too many false positives
    # ("meta-analysis", "meta-narrative"). Use $META or (META) to match.
}

# Sort name keys longest-first so "cadence design" matches before "cadence".
_SORTED_NAMES = sorted(NAME_TO_TICKER.keys(), key=len, reverse=True)

# Explicit ticker patterns: $PLTR or (PLTR). 1-5 uppercase letters.
_CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")
_PAREN = re.compile(r"\(([A-Z]{2,5})\)")

# Known tickers set (for validating cashtag/paren hits aren't random caps)
_KNOWN = set(NAME_TO_TICKER.values()) | set(config.WATCHLIST.keys())


def resolve(text: str):
    """
    Return the first ticker found in `text`, or None.
    Prefers explicit tickers, then company names.
    """
    if not text:
        return None

    # 1. explicit $TICKER
    for m in _CASHTAG.finditer(text):
        if m.group(1) in _KNOWN:
            return m.group(1)

    # 2. explicit (TICKER)
    for m in _PAREN.finditer(text):
        if m.group(1) in _KNOWN:
            return m.group(1)

    # 3. company name
    low = text.lower()
    for name in _SORTED_NAMES:
        # word-boundary-ish match to avoid 'intel' inside 'intelligence'
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return NAME_TO_TICKER[name]

    return None


def resolve_all(text: str):
    """Return all distinct tickers mentioned in text (order preserved)."""
    found = []
    if not text:
        return found
    for m in list(_CASHTAG.finditer(text)) + list(_PAREN.finditer(text)):
        if m.group(1) in _KNOWN and m.group(1) not in found:
            found.append(m.group(1))
    low = text.lower()
    for name in _SORTED_NAMES:
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            t = NAME_TO_TICKER[name]
            if t not in found:
                found.append(t)
    return found
