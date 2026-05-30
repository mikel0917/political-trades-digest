"""
Configuration for the Political & Insider Trades Digest.

Everything you'd want to tune lives here. No code changes needed for
day-to-day adjustments — edit this file, not the modules.

All sources used are FREE. No API keys required for the default setup.
Optional keys (Finnhub, Quiver) are read from environment variables if
present and silently skipped if not.
"""

import os

# ---------------------------------------------------------------------------
# WATCHLIST
# ---------------------------------------------------------------------------
# Tickers you actively care about. Items touching these get prioritized.
# The digest still surfaces convergence hits on OTHER tickers (see below),
# but watchlist names are always pulled to the top.
WATCHLIST = {
    "RKLB": "Rocket Lab",
    "MU": "Micron",
    "DXYZ": "Destiny Tech100",
    "PLTR": "Palantir",
    "ADBE": "Adobe",
    "INTC": "Intel",
    "DELL": "Dell",
    "AVGO": "Broadcom",
    "SNPS": "Synopsys",
    "CDNS": "Cadence",
    "TXN": "Texas Instruments",
    "NVDA": "Nvidia",
    "HOOD": "Robinhood",
}

# If True, the digest shows ALL tracked events (firehose) with watchlist +
# convergence items floated to the top. If False, ONLY watchlist tickers and
# convergence hits are shown (quieter coffee read). Start with False.
SHOW_FIREHOSE = False

# Sector tags used by the briefing for context paragraphs (e.g. "this is the
# third semis name to surface this week"). Add tickers here as you extend
# WATCHLIST. Unknown tickers just don't get a sector callout.
TICKER_SECTOR = {
    "RKLB": "space/defense",
    "MU":   "semis",
    "DXYZ": "private-tech basket",
    "PLTR": "defense-software",
    "ADBE": "software",
    "INTC": "semis",
    "DELL": "hardware/AI infra",
    "AVGO": "semis",
    "SNPS": "semis-EDA",
    "CDNS": "semis-EDA",
    "TXN":  "semis",
    "NVDA": "semis",
    "HOOD": "fintech/brokerage",
    # common extras the resolver might surface
    "AAPL": "consumer-tech",
    "TSLA": "auto/energy",
    "BA":   "aerospace/defense",
    "LMT":  "defense",
    "AMZN": "consumer-tech",
    "MSFT": "software",
    "DJT":  "media",
    "COIN": "crypto/fintech",
    "AMD":  "semis",
}

# Short qualitative notes per actor — used by the briefing to add a sentence
# of context (their committee, role, or known position). Keep it factual and
# brief; the digest is not a profile page.
ACTOR_NOTES = {
    "trump":      "sitting president; his disclosed trades and verbal endorsements both move tape, but research shows the move is captured by algos within seconds",
    "bessent":    "Treasury Secretary; cabinet officials typically divest individual stocks on taking office, so direct trades are rare — watch for policy signals instead",
    "pelosi":     "House member; her family's trading record is the most-studied in the STOCK Act dataset and outperforms the index, but the disclosures arrive ~45 days late",
    "tuberville": "Senate Armed Services; activity tends to cluster around defense names",
    "crenshaw":   "House Energy & Commerce; trades tend to be small-dollar relative to other tracked names",
    "khanna":     "House Oversight; one of the louder voices for a congressional trading ban while still actively filing",
    "greene":     "House Oversight; high-volume filer with a broad-spectrum portfolio",
    "mccaul":     "House Foreign Affairs; defense and aerospace overweight",
    "gottheimer": "House Financial Services; finance/insurance overweight",
}

# ---------------------------------------------------------------------------
# CONVERGENCE DETECTION
# ---------------------------------------------------------------------------
# A "convergence" = the same ticker touched by 2+ distinct actors within the
# window below. This is the headline signal of the whole tool.
# 45 days matches the congressional STOCK Act disclosure lag — shorter windows
# miss matches because congressional data arrives ~45 days late anyway.
CONVERGENCE_WINDOW_DAYS = 45
CONVERGENCE_MIN_ACTORS = 2  # how many distinct actors before it's flagged

# ---------------------------------------------------------------------------
# ACTORS WE TRACK
# ---------------------------------------------------------------------------
# Congressional names (tracked via free congressional feeds). Add/remove freely.
# These are the cleanly-trackable STOCK Act filers.
CONGRESS_ACTORS = [
    "Nancy Pelosi",
    "Tommy Tuberville",
    "Dan Crenshaw",
    "Ro Khanna",
    "Marjorie Taylor Greene",
    "Michael McCaul",
    "Josh Gottheimer",
]

# Executive-branch / high-profile names tracked via NEWS (OGE filings + remarks).
# These do NOT appear in congressional feeds — they surface as news stories.
# NOTE: Cabinet officials (e.g. Treasury Secretary) often divest individual
# stocks on taking office, so their "trades" may simply not exist as a feed.
# We watch the news for them regardless; empty is a valid result.
EXECUTIVE_ACTORS = [
    "Trump",
    "Bessent",
]

# ---------------------------------------------------------------------------
# NEWS KEYWORD QUERIES (Google News RSS — free, no key)
# ---------------------------------------------------------------------------
# Each entry becomes a Google News RSS search. These catch:
#   - OGE / ethics-filing disclosed trades ("Trump ethics filing")
#   - endorsements, both posted AND televised ("Trump praise stock")
#   - setup events (contracts, government stakes, donations)
# Keep queries specific — broad ones flood the digest with junk.
NEWS_QUERIES = [
    '"Trump" "ethics filing" stock',
    '"Trump" brokerage stock disclosure',
    'Trump praises stock surges',
    'Trump endorsement stock jumps',
    '"Bessent" stock disclosure',
    'OGE Form 278 Trump stock',
    'president stock pick market reaction',
]

# Setup-signal keywords — these flag a NEWS item as a potential "leading"
# indicator (a company tying itself to the administration) vs. a reaction.
# Used only to TAG items, not to filter them.
SETUP_KEYWORDS = [
    "federal contract", "government stake", "tariff exemption",
    "tariff carve", "trump account", "white house", "defense contract",
    "pentagon", "chips act", "government contract", "donation", "pledged",
]

# ---------------------------------------------------------------------------
# OUTCOME TRACKING
# ---------------------------------------------------------------------------
# After an event fires, we record the price and re-check it later to build
# YOUR OWN backtest of whether acting on these signals would've paid off.
# Horizons in calendar days.
OUTCOME_HORIZONS_DAYS = [1, 7, 30]

# ---------------------------------------------------------------------------
# DELIVERY
# ---------------------------------------------------------------------------
# Email via Resend (free tier: 3,000 emails/month). Set these env vars:
#   RESEND_API_KEY, DIGEST_EMAIL_FROM, DIGEST_EMAIL_TO
# If RESEND_API_KEY is missing, the digest is written to disk + printed instead.
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
EMAIL_FROM = os.environ.get("DIGEST_EMAIL_FROM", "digest@yourdomain.com")
EMAIL_TO = os.environ.get("DIGEST_EMAIL_TO", "")

# Optional SMS nudge via Telnyx (you already have this). Fires ONLY when there's
# a convergence hit or a watchlist event — i.e. "open the email, it matters."
# Set: TELNYX_API_KEY, TELNYX_FROM_NUMBER, TELNYX_TO_NUMBER
# Costs ~$0.004/msg. Leave blank to disable SMS entirely (stays 100% free).
TELNYX_API_KEY = os.environ.get("TELNYX_API_KEY", "")
TELNYX_FROM = os.environ.get("TELNYX_FROM_NUMBER", "")
TELNYX_TO = os.environ.get("TELNYX_TO_NUMBER", "")
SMS_ONLY_FOR_PRIORITY = True  # don't text on boring days

# Telegram push for INTRADAY alerts (separate from the daily 7am email).
# When run.py is invoked with env var DIGEST_MODE=intraday, it skips the
# email entirely and only pushes a Telegram message IF a new watchlist or
# convergence event was ingested this run. Cost: free.
# Setup:
#   1. On Telegram, message @BotFather → /newbot → get bot token
#   2. Message your new bot something so it has a conversation
#   3. Message @userinfobot to get your numeric Telegram chat ID
#   4. Set both as GH secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Optional Finnhub key (free tier). If absent, we fall back to yfinance for
# all price data, which is free but flakier. Either works.
FINNHUB_API_KEY = os.environ.get("FINNHUB_API_KEY", "")

# ---------------------------------------------------------------------------
# PATHS
# ---------------------------------------------------------------------------
import pathlib
BASE_DIR = pathlib.Path(__file__).parent
DB_PATH = BASE_DIR / "digest.db"
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# Lookback for "new" items each run. Run daily; 2-day lookback covers weekends
# and any missed run without duplicating (dedup handles overlap).
LOOKBACK_DAYS = 2
