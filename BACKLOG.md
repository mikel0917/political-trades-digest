# Backlog

Things worth adding to this project, ranked by signal-added-per-hour-of-work.
Curated 2026-05-30. Re-rank as the backtest table fills in and tells you which
signal classes actually pay off — don't build new sources for ones that don't.

---

## P0 — High value, low effort (next-week additions)

### 1. USAspending.gov contract-award scraper
**Why:** This is the actual *leading* indicator. Companies that win a DoD / HHS /
DOE contract often see the endorsement post or stock pop days later. Right now
we catch the *reaction* (endorsement, news) but not the *setup*. The README
explicitly flags this as Roadmap-1.
**How:** USAspending has a free public REST API (`api.usaspending.gov`). Filter
by recent awards over $1M, intersect with watchlist names + the ticker-name
resolver, emit `KIND_SETUP` events.
**Cost:** Free, no key. ~1 hour of work.

### 2. EDGAR filing-type filter (known bug)
**Why:** `sources/insiders.py` queries EDGAR with `type=4` but the atom feed
returns related filings (424B5 prospectuses, S-1, etc.) which then get stored
as `👔 INSIDER BUY` — wrong kind, wrong signal class.
**How:** Inspect each atom entry's `<category>` field; only keep entries whose
type is literally `4` (Form 4) or `4/A` (amendment).
**Cost:** ~15 min.

### 3. Sentiment gate on endorsements
**Why:** Trump *trashing* a stock and Trump *praising* a stock are the OPPOSITE
signal. The current classifier keys on words like "praised" / "told americans
to" but doesn't check for "slammed" / "frauds" / "delisted" / "disaster." A
Trump attack would currently fire `📣 ENDORSEMENT`.
**How:** Add a negative-keyword list to `sources/news.py:_classify()`. If any
negative keyword + actor name appears together, downgrade to `KIND_NEWS` (or
add a new `KIND_ATTACK`).
**Cost:** ~30 min. No ML needed.

### 4. Source-count confirmation gate (anti-noise)
**Why:** First-ingest fires the intraday push, so a thinly-sourced small-blog
"Trump might endorse X" speculation piece pings you the same way a 30-outlet
confirmed story does.
**How:** In intraday mode only — instead of firing on the first ingest,
require `source_count >= 2`. The check happens on the next cron after first
seeing the event; latency goes from ~15 min to ~30-45 min in exchange for far
fewer false positives.
**Cost:** ~30 min. Trade-off: slight latency hit.

### 5. Source-health canary
**Why:** Feeds rot silently. If EDGAR starts 403'ing all watchlist tickers, or
Google News RSS shifts its endpoint, you get "quiet day" emails forever and
never know.
**How:** Track per-source counts in a small `feed_health` table. If a source
returns 0 events for N consecutive runs (3 for news, 5 for insiders, 7 for
congress), push a `⚠️ feed appears dead` Telegram message and skip until
healthy again.
**Cost:** ~45 min.

### 6. Expand `EXECUTIVE_ACTORS`
**Why:** Currently only `Trump` and `Bessent`. The Secretary of Defense, HHS,
Commerce, Energy, FTC Chair, FCC Chair — all move tape when they speak.
**How:** Add their last names (and maybe full names) to `config.py:EXECUTIVE_ACTORS`.
Add `ACTOR_NOTES` entries so the briefing has a one-line context for each.
**Cost:** ~20 min. Pure config.

---

## P1 — Medium value, worth doing soon

### 7. Per-actor backtest breakdown
**Why:** Right now `backtest` aggregates all endorsements together. Does Trump's
endorsement at +7d actually look different from Bessent's OGE filings? Almost
certainly. Pelosi vs. Tuberville vs. Crenshaw — same. Aggregating hides this.
**How:** Add `actor` to the `GROUP BY` in `store.backtest_summary()`. Render a
second table in the daily digest broken down by actor × kind × horizon.
**Cost:** ~1 hour including layout.

### 8. Quiet hours on Telegram intraday
**Why:** If a big story breaks at 4am ET, you don't want to be woken up. Save
the alert for the 8am digest.
**How:** In `delivery/send.py:send_telegram_alert()`, check local time
(America/New_York). Between 10pm-7am ET, queue the alert into a `pending_quiet`
table; the 8am daily run flushes anything queued.
**Cost:** ~1 hour. Requires `zoneinfo` import and a small state column.

### 9. Liquidity warning on cards
**Why:** Small caps with thin volume can pop 30% on a few thousand shares; the
bid-ask spread alone would eat any "edge." A 33% pop in a $500K daily volume
name isn't actionable.
**How:** yfinance returns `averageVolume`. Multiply by current price to get
$-volume. If `< $5M/day`, add a `⚠️ thin liquidity` tag to the card and dampen
the convergence narrative ("don't chase this one even if it triggered").
**Cost:** ~30 min.

### 10. Sector ETF benchmarking in backtest
**Why:** "NVDA +2% on Trump endorsement" is meaningless if SOXX (semis ETF) was
+3% the same day. The backtest table claims "endorsements +1.4% at +7d" but
some of that is just sector beta. We're potentially flattering the signal.
**How:** Map each watchlist ticker to a sector ETF (XLK, XLE, XLY, XLV, XLF,
XLI, ITA, SOXX). On outcome computation, also fetch the ETF's pct change for
the same horizon. Show both columns: absolute and alpha-vs-sector.
**Cost:** ~2 hours including mapping.

### 11. Cabinet meeting / White House schedule scraper
**Why:** When the day's POTUS schedule includes a CEO meeting, the CEO's
company often pops the next session. This is leading.
**How:** whitehouse.gov publishes a daily schedule in HTML. Scrape, extract
named-entity participants, intersect with ticker resolver.
**Cost:** ~2 hours. Brittle (scraping HTML changes). Worth it if Trump 2nd
term keeps the format consistent.

### 12. 13D/13G filings (>5% activist stakes)
**Why:** When a tracked fund family (Berkshire, Renaissance, certain
politically-aligned vehicles) takes a >5% stake in a name, it's a multi-week
heads-up before public attention catches up.
**How:** EDGAR feed type `SC 13D` and `SC 13G`. Already free, same EDGAR
infrastructure as Form 4.
**Cost:** ~1 hour.

---

## P2 — Lower value but interesting

### 13. Truth Social direct polling
**Why:** Google News RSS is 5-30 min behind original publication. Direct
polling cuts that to ~1 min.
**How:** No official API; community scrapers exist (`truthsocial_py`, etc.).
Adds dependency and breakage risk.
**Cost:** ~3 hours including failure-mode handling.
**Caveat:** May violate Truth Social TOS. Read carefully before deploying.

### 14. DB size management / rotation
**Why:** `digest.db` grows unbounded. At current rate, ~100 MB in 12 months
(committed to repo each run). Eventually GH push will slow.
**How:** Prune events older than 90 days. Keep their outcome rows in a
separate aggregated `outcomes_archive` table so the backtest doesn't reset.
**Cost:** ~1 hour. Not urgent.

### 15. Web dashboard (GH Pages)
**Why:** No way to see history without scrolling git commits / old emails.
A dashboard with searchable events would help long-term review.
**How:** GH Pages reading `digest.db` (or a JSON export) and rendering with
vanilla JS or Svelte. Static site, free hosting.
**Cost:** ~6 hours.
**Caveat:** Repo is private; dashboard would need authentication or be private
too (GH Pages on private repo requires Enterprise/Pro).

### 16. Telegram bot interactive commands
**Why:** `/add TICKER`, `/mute TICKER 24h`, `/list`, `/pause`, `/status`.
Avoids editing `config.py` and pushing for every watchlist change.
**How:** Telegram bot webhook → small handler script (could run in GH Actions
or a free serverless tier like Vercel).
**Cost:** ~4 hours including persistent state for mutes.

### 17. Multi-source NLP similarity dedup
**Why:** Current dedup key is `kind|ticker|date`. Same ticker + same kind on
the same day collapses correctly. But if a story breaks across days (e.g.,
Trump posts at 11:55pm; first article 11:58pm dated today; follow-ups dated
tomorrow), the same story produces two events.
**How:** TF-IDF or embedding-based headline similarity. Group similar
headlines across ±1 day window.
**Cost:** ~3 hours. Marginal gain.

### 18. Volume confirmation column
**Why:** Backtest only tracks price change. A 2% pop on normal volume is
different from 2% on a volume spike. Distinguishes "real news" from "drift."
**How:** Store `event_volume` (current day) and `avg_volume_30d`. Backtest
table gets a `volume_z` column.
**Cost:** ~1 hour.

### 19. 8-K filing scraper
**Why:** Material corporate events (bankruptcies, large contracts, CEO
departures) often precede the political reaction. EDGAR feed.
**How:** Same plumbing as insider. Filter type `8-K`. Per-watchlist-ticker
polling.
**Cost:** ~1 hour.

### 20. 13F quarterly filings
**Why:** Large institutional holdings disclosures. If a tracked fund (e.g.,
politically-aligned family office) appears in or exits a name, that's a real
signal albeit 45 days lagged.
**How:** EDGAR `13F-HR`. Polled monthly, not daily.
**Cost:** ~2 hours.

---

## P3 — Probably don't bother

| Idea | Why skip |
|---|---|
| Reddit / Twitter sentiment | Too noisy, API costs, signal-to-noise terrible |
| Multi-language news | Overkill for US-political-trade focus |
| Election prediction markets (Polymarket / Kalshi) | Tangential signal class; would dilute scope |
| Custom ML endorsement classifier | Sentiment gate (#3) gets 90% of value at 1% cost |
| Brokerage integration / auto-execution | The whole point is "awareness not alpha" — don't cross this line |
| Subscriber model / public newsletter | Securities-information-distribution issues; stay private |
| Single "buy/sell/hold" score | Lies. The backtest table tells truth; condensing it loses information |

---

## Notes for next-session pickup

- **Wipe-DB-required-before-test:** when changing parsing (e.g., EDGAR
  filter, sentiment gate), the old events in `digest.db` have the
  pre-fix actor/headline/kind values. New events get the fix; old stay
  stale for ~45 days until they age out of the convergence window.
  Either wipe `digest.db` to get a clean slate, or wait for the rolling
  window to flush.
- **GitHub Actions cron is best-effort.** Delays of 5-30 min are common
  during peak hours. Don't rely on sub-minute timing for anything.
- **API quotas to watch:**
  - Finnhub free: 60 calls/min (we use ~13 calls/run for prices)
  - FMP free: 250 calls/day (we use ~2 calls/run)
  - Resend free: 3,000 emails/month (we use ~60)
  - Telegram bot: 30 messages/sec/chat (we use ~5/run worst case)
  - GitHub Actions: 2,000 min/month private repo (we use ~720)
- **EDGAR `EDGAR_UA`** must be a real contact email. SEC actually emails
  bot operators who violate fair use.
- **Resend free tier** only sends from `onboarding@resend.dev` (or a
  verified domain) and only to the account's registered email. Currently
  registered to `doughnut23456@gmail.com`. Verify a domain to send from
  / to anywhere.
