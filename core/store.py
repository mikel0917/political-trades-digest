"""
Core: the Event data model and the SQLite store.

An Event is the normalized unit every source produces. The store handles:
  - dedup (so the Dell story from 15 outlets becomes one entry)
  - persistence (so we know what's "new" each run)
  - outcome logging (price at event time + later re-checks = your own backtest)
"""

import sqlite3
import hashlib
import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Optional

import config


# Event "kinds" — the WHY tag on each digest line.
KIND_ENDORSEMENT = "endorsement"      # posted or televised praise / "buy X"
KIND_EXEC_TRADE = "exec_trade"        # OGE-disclosed brokerage trade (Trump etc.)
KIND_CONGRESS_TRADE = "congress_trade"  # STOCK Act disclosure
KIND_INSIDER = "insider_buy"          # SEC Form 4 corporate insider
KIND_SETUP = "setup"                  # contract / stake / donation (leading signal)
KIND_NEWS = "news"                    # generic relevant news

KIND_LABELS = {
    KIND_ENDORSEMENT: "📣 ENDORSEMENT",
    KIND_EXEC_TRADE: "🏛️ EXEC TRADE",
    KIND_CONGRESS_TRADE: "🏦 CONGRESS",
    KIND_INSIDER: "👔 INSIDER BUY",
    KIND_SETUP: "🔧 SETUP",
    KIND_NEWS: "📰 NEWS",
}


@dataclass
class Event:
    kind: str                 # one of the KIND_* constants
    actor: str                # who (e.g. "Trump", "Nancy Pelosi", "CEO")
    ticker: Optional[str]     # resolved ticker, may be None for unmatched news
    headline: str             # human-readable summary line
    source: str               # source name (e.g. "Google News", "EDGAR")
    url: str                  # link
    event_date: str           # ISO date (YYYY-MM-DD) the event/trade happened
    detail: str = ""          # extra context (amount band, transaction type...)
    is_setup: bool = False    # tagged as a leading/setup signal

    def dedup_key(self) -> str:
        """
        Collapse near-duplicates. Same ticker + same kind + same day = one event,
        regardless of which outlet reported it. For unmatched news (no ticker),
        fall back to a hash of the headline.
        """
        if self.ticker:
            basis = f"{self.kind}|{self.ticker}|{self.event_date}"
        else:
            basis = f"{self.kind}|{self.headline.lower()[:80]}|{self.event_date}"
        return hashlib.sha1(basis.encode()).hexdigest()[:16]


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    dedup_key   TEXT PRIMARY KEY,
    kind        TEXT,
    actor       TEXT,
    ticker      TEXT,
    headline    TEXT,
    source      TEXT,
    url         TEXT,
    event_date  TEXT,
    detail      TEXT,
    is_setup    INTEGER,
    first_seen  TEXT,          -- when WE first recorded it
    source_count INTEGER DEFAULT 1,  -- how many outlets/sources reported it
    event_price REAL,          -- price at first_seen (for outcome tracking)
    notified    INTEGER DEFAULT 0  -- has this gone out in a digest yet
);

CREATE TABLE IF NOT EXISTS outcomes (
    dedup_key   TEXT,
    horizon_days INTEGER,
    check_date  TEXT,
    price       REAL,
    pct_change  REAL,           -- vs event_price
    PRIMARY KEY (dedup_key, horizon_days)
);
"""


class Store:
    def __init__(self, path=config.DB_PATH):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def upsert_event(self, ev: Event) -> bool:
        """
        Insert an event. If it already exists (same dedup_key), bump its
        source_count instead. Returns True if this was NEW.
        """
        key = ev.dedup_key()
        now = dt.datetime.utcnow().isoformat()
        cur = self.conn.execute("SELECT source_count FROM events WHERE dedup_key=?", (key,))
        row = cur.fetchone()
        if row:
            self.conn.execute(
                "UPDATE events SET source_count = source_count + 1 WHERE dedup_key=?",
                (key,),
            )
            self.conn.commit()
            return False
        self.conn.execute(
            """INSERT INTO events
               (dedup_key, kind, actor, ticker, headline, source, url,
                event_date, detail, is_setup, first_seen, source_count, notified)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,1,0)""",
            (key, ev.kind, ev.actor, ev.ticker, ev.headline, ev.source, ev.url,
             ev.event_date, ev.detail, int(ev.is_setup), now),
        )
        self.conn.commit()
        return True

    def set_event_price(self, dedup_key: str, price: float):
        self.conn.execute(
            "UPDATE events SET event_price=? WHERE dedup_key=? AND event_price IS NULL",
            (price, dedup_key),
        )
        self.conn.commit()

    def unnotified_events(self):
        cur = self.conn.execute("SELECT * FROM events WHERE notified=0 ORDER BY event_date DESC")
        return [dict(r) for r in cur.fetchall()]

    def mark_notified(self, keys):
        self.conn.executemany("UPDATE events SET notified=1 WHERE dedup_key=?",
                              [(k,) for k in keys])
        self.conn.commit()

    def recent_events(self, days: int):
        """All events with event_date within `days` of today — for convergence."""
        cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
        cur = self.conn.execute(
            "SELECT * FROM events WHERE event_date >= ? AND ticker IS NOT NULL",
            (cutoff,),
        )
        return [dict(r) for r in cur.fetchall()]

    def events_needing_outcome(self, horizon_days: int):
        """
        Events whose event_date is exactly `horizon_days` ago (or older) and
        which don't yet have an outcome recorded for that horizon.
        """
        target = (dt.date.today() - dt.timedelta(days=horizon_days)).isoformat()
        cur = self.conn.execute(
            """SELECT e.* FROM events e
               LEFT JOIN outcomes o
                 ON e.dedup_key = o.dedup_key AND o.horizon_days = ?
               WHERE e.ticker IS NOT NULL
                 AND e.event_price IS NOT NULL
                 AND e.event_date <= ?
                 AND o.dedup_key IS NULL""",
            (horizon_days, target),
        )
        return [dict(r) for r in cur.fetchall()]

    def record_outcome(self, dedup_key, horizon_days, price, event_price):
        pct = ((price - event_price) / event_price * 100) if event_price else None
        self.conn.execute(
            """INSERT OR REPLACE INTO outcomes
               (dedup_key, horizon_days, check_date, price, pct_change)
               VALUES (?,?,?,?,?)""",
            (dedup_key, horizon_days, dt.date.today().isoformat(), price, pct),
        )
        self.conn.commit()

    def backtest_summary(self):
        """
        Aggregate outcome stats by event kind — YOUR private backtest.
        Returns rows of (kind, horizon, n, avg_pct, win_rate).
        """
        cur = self.conn.execute(
            """SELECT e.kind, o.horizon_days,
                      COUNT(*) as n,
                      AVG(o.pct_change) as avg_pct,
                      AVG(CASE WHEN o.pct_change > 0 THEN 1.0 ELSE 0.0 END) as win_rate
               FROM outcomes o JOIN events e ON e.dedup_key = o.dedup_key
               GROUP BY e.kind, o.horizon_days
               ORDER BY e.kind, o.horizon_days"""
        )
        return [dict(r) for r in cur.fetchall()]

    def close(self):
        self.conn.close()
