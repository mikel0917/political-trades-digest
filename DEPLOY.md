# Deploy Guide — for Claude Code

This is a Python daily-digest tool that tracks political/insider stock trades
(Trump endorsements + OGE-disclosed trades, congressional STOCK Act trades, SEC
Form 4 insider filings), detects when multiple actors converge on the same
ticker, enriches with price + "since event" move, logs outcomes over time to
build a self-backtest, and emails a TL;DR digest each morning.

**Status:** built and unit-tested. NEVER run against live feeds — it was built
in a sandbox that could only reach package registries, so the news / EDGAR /
congressional fetches returned 0 by design there. The logic, dedup, convergence,
TL;DR rendering, and ticker resolver all pass. The live feeds need a first real
run + tuning.

**Read first:** `README.md` (architecture + caveats), `config.py` (all tunables),
`run.py` (orchestration flow).

---

## Recommended host: GitHub Actions (free, no always-on machine)

The user's VPS is off. GitHub Actions runs the job on a schedule with no server
to maintain. The workflow is already written: `.github/workflows/digest.yml`
(runs 11:00 UTC = 7am ET daily, plus manual trigger; commits `digest.db` back to
the repo so dedup history + backtest outcomes persist across runs).

### Steps

1. **Create a PRIVATE GitHub repo** and push this project.
   ```bash
   git init && git add -A && git commit -m "initial: trades digest"
   git branch -M main
   git remote add origin git@github.com:USERNAME/trades-digest.git
   git push -u origin main
   ```
   (Private matters: the committed `digest.db` will contain your watchlist
   activity, and you don't want the workflow's repo-write token on a public repo.)

2. **Add Secrets** at repo → Settings → Secrets and variables → Actions → New
   repository secret. All optional; unset ones just disable that feature:
   | Secret | Purpose | Get it |
   |---|---|---|
   | `FINNHUB_API_KEY` | congressional trades + prices | finnhub.io (free) |
   | `RESEND_API_KEY` | email delivery | resend.com (free, 3k/mo) |
   | `DIGEST_EMAIL_FROM` | sender (must be a Resend-verified domain) | — |
   | `DIGEST_EMAIL_TO` | your inbox | — |
   | `EDGAR_UA` | SEC requires this, e.g. `Mikel mikel@email.com` | — |
   | `FMP_API_KEY` | alt congressional source (optional) | financialmodelingprep.com |
   | `TELNYX_API_KEY` / `TELNYX_FROM_NUMBER` / `TELNYX_TO_NUMBER` | SMS nudge (optional) | already has Telnyx |

3. **Manual test run:** Actions tab → "Daily Trades Digest" → Run workflow.
   Watch the log. Confirm the source counts are NONZERO (this is the thing the
   sandbox couldn't verify). Confirm the email arrives.

4. **Done.** It now runs every morning. The DB commit-back means each run's
   events + outcomes accumulate.

### Likely first-run issues to debug (logic is fine; these are live realities)
- **EDGAR returns 0 or 403** → `EDGAR_UA` secret missing or not descriptive.
  SEC requires a real contact. Must be set.
- **News too noisy / too quiet** → tune `config.NEWS_QUERIES`. They were written
  blind; check what real Google News RSS returns and adjust. Also extend the
  name→ticker map in `core/tickers.py` for any company it misses.
- **Congressional source empty** → confirm `FINNHUB_API_KEY` set; Finnhub's
  congressional endpoint is per-symbol and only returns watchlist names.
- **Resend 403/422** → `DIGEST_EMAIL_FROM` must be on a domain verified in
  Resend, or use their onboarding `onboarding@resend.dev` sender for testing.
- **DB commit-back fails** → ensure workflow `permissions: contents: write` (it
  is) and the repo allows Actions to push (Settings → Actions → Workflow
  permissions → Read and write).

---

## Alternative host: local machine cron (only if it's reliably on at 7am)

Simpler (no DB-persistence wrinkle — the file just stays put) but skips days the
machine is asleep. The 2-day lookback + dedup makes catch-up runs safe.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in keys
set -a; . ./.env; set +a
python run.py          # test
cat output/digest-$(date +%F).txt
```
Cron:
```
0 7 * * *  cd /path/to/political-trades-digest && set -a && . ./.env && set +a && venv/bin/python run.py >> cron.log 2>&1
```

---

## What to prioritize after it's live

1. Confirm a few real runs produce sensible TL;DRs.
2. Tune `NEWS_QUERIES` + the ticker map over the first week.
3. **Then leave it alone for ~3 months and watch the backtest table** at the
   bottom of the digest. That table — how endorsements/trades actually performed
   at +1/+7/+30 days — is the whole point. It answers whether acting on these
   signals would make or lose money (the research says probably not on its own).
   Don't expand the tool (USAspending contracts, Form 4 buy/sell parse, 13F)
   unless the backtest says the core signal is worth it.

## v2 enhancements (only if backtest justifies)
- Parse Form 4 XML to separate insider BUYS from sells (currently surfaces the
  filing without classifying).
- USAspending.gov contract-award tracking (the *setup* signal before endorsements).
- Quarterly 13F note when a tracked fund appears in a watchlist name.
