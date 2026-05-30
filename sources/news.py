"""
News source — the keyless backbone.

Pulls Google News RSS for each configured query. This single source catches the
majority of what you actually care about, because BOTH of these surface as news
articles within minutes:
  - OGE / ethics-filing disclosed trades  ("Trump brokerage bought Dell")
  - endorsements, posted AND televised     ("Trump tells Americans to buy Dell")
  - setup events                           ("Dell family pledges $6.25B")

Each RSS item is run through the ticker resolver. Items that resolve to a ticker
become structured Events; unmatched-but-relevant items are kept as generic news
only if SHOW_FIREHOSE is on (otherwise dropped to keep the coffee read clean).
"""

import urllib.parse
import datetime as dt

import feedparser

import config
from core.store import Event, KIND_ENDORSEMENT, KIND_EXEC_TRADE, KIND_SETUP, KIND_NEWS
from core import tickers


def _google_news_url(query: str) -> str:
    q = urllib.parse.quote(query)
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def _classify(title: str, summary: str) -> tuple[str, bool]:
    """
    Decide the event KIND and whether it's a setup signal, from the text.
    Returns (kind, is_setup).
    """
    text = f"{title} {summary}".lower()

    is_setup = any(kw in text for kw in config.SETUP_KEYWORDS)

    # disclosed trade language
    if any(p in text for p in ["ethics filing", "oge ", "form 278", "brokerage",
                                "disclosed", "disclosure shows", "bought", "purchased"]):
        # distinguish exec trade vs generic — exec actors named?
        if any(a.lower() in text for a in config.EXECUTIVE_ACTORS):
            return KIND_EXEC_TRADE, is_setup

    # endorsement language
    if any(p in text for p in ["praise", "praised", "told americans", "buy a",
                                "endorse", "congratulat", "great job", "shoutout",
                                "shout-out", "urged"]):
        return KIND_ENDORSEMENT, is_setup

    if is_setup:
        return KIND_SETUP, True

    return KIND_NEWS, False


def _entry_date(entry) -> str:
    try:
        tm = entry.get("published_parsed") or entry.get("updated_parsed")
        if tm:
            return dt.date(tm.tm_year, tm.tm_mon, tm.tm_mday).isoformat()
    except Exception:
        pass
    return dt.date.today().isoformat()


def _actor_from_text(text: str) -> str:
    """
    Attribute a news item to a known actor. Checks congressional names
    first (more specific — full names like 'Nancy Pelosi'), then executive
    actors (typically single tokens like 'Trump' which would otherwise
    catch unrelated mentions). Returns 'News' if nothing matches.
    """
    low = text.lower()
    for a in config.CONGRESS_ACTORS:
        # match on last-name token to handle 'Pelosi' alone or 'Nancy Pelosi'
        last = a.lower().split()[-1]
        if last and last in low:
            return a
    for a in config.EXECUTIVE_ACTORS:
        if a.lower() in low:
            return a
    return "News"


def fetch() -> list[Event]:
    cutoff = dt.date.today() - dt.timedelta(days=config.LOOKBACK_DAYS)
    events: list[Event] = []

    for query in config.NEWS_QUERIES:
        try:
            feed = feedparser.parse(_google_news_url(query))
        except Exception as e:
            print(f"  [news] query failed: {query!r}: {e}")
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")
            edate = _entry_date(entry)
            try:
                if dt.date.fromisoformat(edate) < cutoff:
                    continue
            except Exception:
                pass

            ticker = tickers.resolve(f"{title} {summary}")
            kind, is_setup = _classify(title, summary)

            # Drop policy: keep the event if it's a politically-tagged signal
            # (endorsement / exec trade / setup) even when the resolver can't
            # find a ticker, because the WHO + WHAT still matters and the
            # intraday push uses signal-kind, not ticker, as the trigger.
            # Generic news without a ticker stays dropped unless SHOW_FIREHOSE
            # is on — otherwise the digest would flood with unrelated stories.
            important_kinds = {KIND_ENDORSEMENT, KIND_EXEC_TRADE, KIND_SETUP}
            if ticker is None and kind not in important_kinds and not config.SHOW_FIREHOSE:
                continue

            events.append(Event(
                kind=kind,
                actor=_actor_from_text(f"{title} {summary}"),
                ticker=ticker,
                headline=title.split(" - ")[0].strip(),  # strip outlet suffix
                source=entry.get("source", {}).get("title", "Google News")
                       if isinstance(entry.get("source"), dict) else "Google News",
                url=entry.get("link", ""),
                event_date=edate,
                detail=("setup signal" if is_setup else ""),
                is_setup=is_setup,
            ))

    return events
