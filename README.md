# Political & Insider Trades Digest

A **free**, cron-driven daily email digest that surfaces market-moving moves by
high-profile people — Trump/executive-branch disclosed trades, posted *and*
televised endorsements, congressional (STOCK Act) trades, and corporate insider
Form 4 filings — and **flags convergence** when multiple independent actors land
on the same ticker.

Built to run on a single VPS. No paid services required.

## What it actually does

- **Catches what you care about from one backbone:** a Google News RSS layer
  (no key) catches both OGE-disclosed trades ("Trump brokerage bought Dell") and
  endorsements whether posted on Truth Social *or* spoken at the White House —
  because both surface as news within minutes.
- **Convergence detection:** the same ticker hit by 2+ distinct actors (or 2+
  signal types) inside a 45-day window gets floated to the top. One politician
  trading is noise; Pelosi + Trump + an insider on the same name is a cluster.
- **"Did I already miss it?" framing:** every item shows the price now vs. the
  price when the event fired. Items already up >5% are tagged *already ran* — so
  the tool discourages chasing tops instead of encouraging it.
- **Your own backtest:** every event's price is logged and re-checked at +1/+7/
  +30 days. After a few months you get a private table of how these signals
  *actually* performed — not a vendor's marketing claim.
- **Dedup + WHY tags:** the Dell story from 15 outlets becomes one line tagged
  "15 sources"; every line is labeled by signal type.

## The honest caveat (read this)

These signals are **lagged** — OGE filings come quarterly and months late,
congressional trades ~45 days late, and even endorsement pops are usually
already in the price by the time you read them. Peer-reviewed research finds the
move from a Trump post averages ~0.8–1.2%, is captured by algos in seconds, and
**tends to mean-revert over the following days**. This tool is for *awareness and
pattern-recognition*, not a buy list. The backtest table exists specifically so
you can see — from your own data — whether acting on these would have paid off
(it probably wouldn't, on its own). Treat a green "since event" number as a
reason for caution, not excitement.

## Setup (5 minutes, $0)

```bash
git clone <your-repo>  # or scp the folder to /opt/political-trades-digest
cd political-trades-digest
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env    # optional — edit to add keys, or leave empty
```

**Zero-config run** (writes the digest to `./output/`, uses yfinance for prices):

```bash
python3 run.py
cat output/digest-$(date +%F).txt
```

That's the fully free path — no accounts, no keys. You just read the file.

## Unlock more (all free tiers)

Edit `.env`:

| Variable | What it adds | Free tier |
|---|---|---|
| `RESEND_API_KEY` + `DIGEST_EMAIL_TO` | Email delivery | 3,000 emails/mo |
| `FINNHUB_API_KEY` | Congressional trades + better prices | 60 calls/min |
| `FMP_API_KEY` | Alt congressional source | 250 calls/day |
| `TELNYX_*` | SMS nudge on important days | ~$0.004/msg |
| `EDGAR_UA` | Required by SEC for Form 4 | free |

Load the env before running:

```bash
set -a; source .env; set +a; python3 run.py
```

## Schedule it (cron)

Run once each morning at 7:00 (server time):

```bash
crontab -e
```
```
0 7 * * *  cd /opt/political-trades-digest && set -a && . ./.env && set +a && /opt/political-trades-digest/venv/bin/python run.py >> /opt/political-trades-digest/cron.log 2>&1
```

The script is idempotent: dedup means a missed run + catch-up won't double-send,
and `notified` flags ensure each event appears in exactly one digest.

## n8n alternative (if you'd rather not cron)

You can run the same logic from n8n with a single **Execute Command** node on a
**Schedule Trigger** (daily 7am):

1. Schedule Trigger → cron `0 7 * * *`
2. Execute Command node:
   `cd /opt/political-trades-digest && set -a && . ./.env && set +a && venv/bin/python run.py`
3. (Optional) Read Binary File node → `output/digest-{{ $today.format('yyyy-MM-dd') }}.html`
   → email/Telegram node, if you'd rather n8n handle delivery than Resend.

Keeping delivery inside `run.py` (Resend) is simpler; use n8n only if you want
its retry/monitoring UI.

## Tuning

Everything lives in `config.py`:
- `WATCHLIST` — your tickers
- `SHOW_FIREHOSE` — `False` = quiet (watchlist + convergence only), `True` = everything
- `CONVERGENCE_WINDOW_DAYS` — default 45 (matches congressional lag)
- `NEWS_QUERIES` — add/remove Google News searches
- `CONGRESS_ACTORS` / `EXECUTIVE_ACTORS` — who to track
- Add company-name → ticker aliases in `core/tickers.py` as you notice misses.

## Maintenance reality

Free scrapers (yfinance, Google News RSS, EDGAR) break or rate-limit
occasionally. Every source is wrapped so one failure degrades gracefully — the
digest still ships from whatever's working. If a feed goes dark, check
`cron.log`, and fix it on a weekend. Nobody's life depends on this; it's a
coffee read.

## Roadmap (only if the backtest says it's worth it)

- USAspending.gov contract-award tracking (the *setup* signal before endorsements)
- Deeper Form 4 XML parse to separate buys from sells
- Quarterly 13F note when a tracked fund appears in a watchlist name
