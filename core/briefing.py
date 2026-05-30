"""
TLDR briefing — the long-form, human-readable top of the digest.

Goal: ~one page of structured commentary that walks through what fired today,
*who* is behind each signal, *where* the company sits (sector + watchlist
status), *how* the signal surfaced (lag + source count), and *why* it might
matter — or, more often, why it probably doesn't on its own. The tone is
deliberately flat; the digest is for awareness, not hype.

Deterministic / template-based (no LLM). The cost of "free" is more code here
and slightly repetitive prose across days; the benefit is offline, predictable,
and tunable by editing this file or config.py.

Structure each run produces:
  1. Headline line  — one-liner summarizing the day
  2. FRESH-24H section — anything dated today or yesterday, surfaced FIRST.
     This is the part the user reads to decide whether to keep scrolling.
     If empty, that's stated explicitly (the rolling-window stuff below is
     by definition lagged).
  3. Opening orientation paragraph (rolling-window framing)
  4. Per-convergence deep-dive (one paragraph each, in priority order)
  5. Watchlist-but-not-convergence paragraph
  6. Setup-signals paragraph (contracts, government stakes, donations)
  7. Sector cluster observation (if 2+ events land in the same sector)
  8. Firehose mention (if SHOW_FIREHOSE is on)
  9. Backtest interpretation paragraph
 10. Quiet-day variant (if zero events) — gets its own 100-word body
"""

# How many days back "fresh" means. 1 = strictly today + yesterday, which
# matches the daily cron cadence so nothing slips through the cracks if a
# run goes long or starts a few minutes late.
FRESH_DAYS = 1

import datetime as dt
from collections import Counter

import config
from core.store import (KIND_ENDORSEMENT, KIND_EXEC_TRADE, KIND_CONGRESS_TRADE,
                        KIND_INSIDER, KIND_SETUP, KIND_NEWS)


KIND_VERB = {
    KIND_ENDORSEMENT:    "publicly endorsed",
    KIND_EXEC_TRADE:     "was disclosed buying",
    KIND_CONGRESS_TRADE: "traded",
    KIND_INSIDER:        "saw an insider Form 4 on",
    KIND_SETUP:          "tied itself to the administration via",
    KIND_NEWS:           "was in the news re:",
}

# Short, opinionated framings for each signal type — used inside the
# convergence and watchlist paragraphs to add a sentence of "what this
# signal historically means."
KIND_FRAMING = {
    KIND_ENDORSEMENT:    ("Endorsement-style signals (a Truth Social post, a "
                          "spoken shoutout, a televised praise line) move tape "
                          "fast — research finds an average ~0.8–1.2% pop "
                          "captured by algos in seconds and a tendency to "
                          "mean-revert over the following days."),
    KIND_EXEC_TRADE:     ("Executive-branch disclosed trades (OGE filings, "
                          "ethics paperwork) arrive months after the trade "
                          "executed; the informational edge is mostly gone "
                          "by the time the public sees it."),
    KIND_CONGRESS_TRADE: ("Congressional STOCK Act filings lag the actual "
                          "trade by ~45 days. The aggregate Pelosi-family "
                          "portfolio has outperformed historically, but the "
                          "lagged signal copying it has been mixed."),
    KIND_INSIDER:        ("Corporate insider Form 4 filings are filed within "
                          "2 business days, which is by far the freshest "
                          "signal in this digest. Open-market BUYS (code P) "
                          "are the better-studied subset; the current parser "
                          "surfaces all Form 4s without classifying — verify "
                          "buy vs sell in the linked filing."),
    KIND_SETUP:          ("Setup signals (contract awards, government stakes, "
                          "tariff carve-outs, donations) are the *leading* "
                          "indicator class — the corporate side moves first, "
                          "then the endorsement / trade follows. These are "
                          "the ones worth watching for as the pre-pattern."),
}

# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

def build(new_events, convergences, backtest, snap_cache):
    """
    Returns (headline_str, list_of_paragraph_strs). Used by both text and
    HTML digest builders so the TLDR is byte-identical in both.
    """
    today = dt.date.today()
    n_events = len(new_events)
    n_conv = len(convergences)
    wl_hits = sorted({e["ticker"] for e in new_events
                      if e.get("ticker") in config.WATCHLIST})
    fresh = _fresh_events(new_events, today)

    headline = _headline(n_events, n_conv, wl_hits, len(fresh))

    # --- quiet-day path ---
    if not n_events and not n_conv:
        return headline, _quiet_day_paragraphs(backtest)

    paras = []

    # --- (0) FRESH-24H section — first thing the reader sees ---
    # Always renders, even when empty, so the user can trust that "no fresh
    # block" really means nothing happened in the last day (vs. tool broken).
    paras.append(_fresh_paragraph(fresh, snap_cache, today))

    # --- (1) orientation opener — rolling-window framing ---
    paras.append(_orientation(today, n_events, n_conv, wl_hits, new_events))

    # --- (2) per-convergence deep dives ---
    for t, info in sorted(convergences.items(),
                          key=lambda kv: len(kv[1]["actors"]), reverse=True):
        paras.append(_convergence_paragraph(t, info, snap_cache))

    # --- (3) watchlist-but-not-convergence ---
    wl_only = [e for e in new_events
               if e.get("ticker") in config.WATCHLIST
               and e.get("ticker") not in convergences]
    if wl_only:
        paras.append(_watchlist_paragraph(wl_only, snap_cache))

    # --- (4) setup signals ---
    setups = [e for e in new_events if e.get("is_setup")
              and e.get("ticker") not in convergences]
    if setups:
        paras.append(_setup_paragraph(setups, snap_cache))

    # --- (5) sector cluster observation ---
    cluster = _sector_cluster_paragraph(new_events, convergences)
    if cluster:
        paras.append(cluster)

    # --- (6) firehose mention ---
    other_tickers = sorted({e["ticker"] for e in new_events
                            if e.get("ticker")
                            and e["ticker"] not in config.WATCHLIST
                            and e["ticker"] not in convergences})
    if other_tickers and config.SHOW_FIREHOSE:
        paras.append("Also surfaced today (not on your watchlist): "
                     + ", ".join(f"<b>{t}</b>" for t in other_tickers[:15])
                     + ("…" if len(other_tickers) > 15 else "")
                     + ". These don't move the needle for your portfolio but "
                     + "appear in the firehose section below.")

    # --- (7) backtest interpretation ---
    paras.append(_backtest_paragraph(backtest))

    return headline, paras


# ---------------------------------------------------------------------------
# fresh (last 24h) — pinned to the top of the TLDR
# ---------------------------------------------------------------------------

def _fresh_events(new_events, today):
    """Events whose event_date is today or within FRESH_DAYS prior."""
    cutoff = today - dt.timedelta(days=FRESH_DAYS)
    out = []
    for e in new_events:
        try:
            d = dt.date.fromisoformat(e["event_date"])
        except Exception:
            continue
        if d >= cutoff:
            out.append((d, e))
    # newest first
    out.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in out]


def _fresh_paragraph(fresh, snap_cache, today):
    """
    First paragraph of every TLDR. Surfaces only events dated today or
    yesterday (FRESH_DAYS). If empty, says so explicitly — the rest of the
    digest is by definition rolling-window / lagged data.
    """
    if not fresh:
        return ("<b>FRESH (last 24h):</b> nothing new dated today or yesterday. "
                "Everything below is rolling-window context — convergences and "
                "filings that surfaced in the last 45 days but didn't move "
                "since the previous digest. That's normal; most calendar days "
                "produce no fresh tracked event.")

    bits = []
    for e in fresh[:8]:
        t = e.get("ticker") or "—"
        kind = _humanize_kind(e["kind"])
        who = e.get("actor") or ""
        if who in ("News", "Insider", "Congress", ""):
            who = ""
        # price + since-event
        snap = snap_cache.get(e.get("ticker")) if e.get("ticker") else None
        price_bit = ""
        if snap and snap.get("price"):
            price_bit = f" — now ~${snap['price']:.2f}"
            mv = _pct_since(e, snap_cache)
            if mv is not None:
                if mv > 5:
                    price_bit += f", already +{mv:.0f}% since (caution: likely in price)"
                elif mv >= 0:
                    price_bit += f", +{mv:.0f}% since"
                else:
                    price_bit += f", {mv:.0f}% since"
        watchlist_tag = " ⭐" if e.get("ticker") in config.WATCHLIST else ""
        actor_bit = f" by {who.capitalize()}" if who else ""
        # short headline excerpt
        excerpt = e["headline"][:90] + ("…" if len(e["headline"]) > 90 else "")
        bits.append(f"<b>{t}</b>{watchlist_tag} — {kind}{actor_bit} on "
                    f"{e['event_date']}{price_bit}. <i>{excerpt}</i>")

    body = "<br>• ".join(bits)
    n = len(fresh)
    n_str = f"{n} item{'s' if n != 1 else ''}"
    return (f"<b>FRESH (last 24h):</b> {n_str} dated today or yesterday — "
            f"this is what's actually new since the last digest, before any "
            f"rolling-window noise:<br>• {body}")


# ---------------------------------------------------------------------------
# headline + opener
# ---------------------------------------------------------------------------

def _headline(n_events, n_conv, wl_hits, n_fresh):
    # Lead with freshness when there is any — that's what the reader cares about.
    parts = []
    if n_fresh:
        parts.append(f"{n_fresh} fresh today")
    if n_conv:
        parts.append(f"{n_conv} convergence{'s' if n_conv != 1 else ''} in 45d window")
    if wl_hits and not parts:
        parts.append(f"{len(wl_hits)} watchlist name"
                     f"{'s' if len(wl_hits) != 1 else ''} active")
    if not parts and n_events:
        parts.append(f"{n_events} tracked, nothing on watchlist")
    if not parts:
        return "Quiet day — nothing new"
    return " · ".join(parts)


def _orientation(today, n_events, n_conv, wl_hits, new_events):
    """Conversational opener that sets up the day before the deep dives."""
    weekday = today.strftime("%A")
    parts = []

    # one-sentence framing of magnitude
    if n_conv >= 2:
        parts.append(f"It's a notable {weekday} — {n_conv} separate names "
                     f"crossed the convergence threshold (two or more distinct "
                     f"actors or signal types on the same ticker inside the "
                     f"{config.CONVERGENCE_WINDOW_DAYS}-day window).")
    elif n_conv == 1:
        parts.append(f"One name crossed the convergence threshold this "
                     f"{weekday} — multiple independent actors landed on the "
                     f"same ticker inside the {config.CONVERGENCE_WINDOW_DAYS}-day window. "
                     f"That's the line item to actually look at; everything "
                     f"else is context.")
    else:
        parts.append(f"No convergences this {weekday}, but {n_events} tracked "
                     f"event{'s' if n_events != 1 else ''} fired across the "
                     f"news/congress/insider feeds.")

    # what kinds dominate today
    kinds = Counter(e["kind"] for e in new_events)
    if kinds:
        leading_kind, leading_n = kinds.most_common(1)[0]
        leading_label = {
            KIND_INSIDER: "corporate insider Form 4 filings",
            KIND_CONGRESS_TRADE: "congressional STOCK Act filings",
            KIND_EXEC_TRADE: "executive-branch disclosed trades",
            KIND_ENDORSEMENT: "endorsement/posted-praise items",
            KIND_SETUP: "setup-style items (contracts, stakes, donations)",
            KIND_NEWS: "general news items",
        }.get(leading_kind, leading_kind)
        if leading_n >= 2:
            parts.append(f"The bulk ({leading_n} of {n_events}) are "
                         f"{leading_label} — keep in mind the freshness "
                         f"hierarchy: insider Form 4s are 2-day-fresh, "
                         f"news/endorsements are same-day, congressional "
                         f"filings ~45 days late, executive-branch OGE "
                         f"filings months late.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# convergence paragraph (the headline section)
# ---------------------------------------------------------------------------

def _convergence_paragraph(t, info, snap_cache):
    """
    One ~100-word paragraph per convergence ticker covering WHO, WHAT,
    WHERE (sector / watchlist), HOW (signal types + lag), WHY it might
    matter, and the mean-reversion caveat.
    """
    name = config.WATCHLIST.get(t, "")
    sector = config.TICKER_SECTOR.get(t)
    actors = sorted(info["actors"])
    kinds = info["kinds"]
    events = sorted(info["events"], key=lambda e: e["event_date"])
    earliest = events[0]
    most_recent = events[-1]

    label = f"<b>{t}</b>" + (f" ({name})" if name else "")

    # WHO + WHERE
    where_bits = []
    if t in config.WATCHLIST:
        where_bits.append("on your watchlist")
    if sector:
        where_bits.append(f"in {sector}")
    where = ", ".join(where_bits)
    where = f", {where}" if where else ""
    actor_str = _humanize_actors(actors) if actors else "multiple independent signals"
    sentence = (f"{label} is the name to look at{where}: "
                f"{actor_str} {'both' if len(actors)==2 else ('all' if len(actors)>=3 else '')}"
                f" touched it within the last {config.CONVERGENCE_WINDOW_DAYS} days, "
                f"first on {earliest['event_date']} via "
                f"{_humanize_kind(earliest['kind'])}, most recently on "
                f"{most_recent['event_date']} via "
                f"{_humanize_kind(most_recent['kind'])}.")

    # actor-specific colour
    notes = _actor_notes_for(actors)
    if notes:
        sentence += " " + notes

    # HOW it showed up (signal types)
    types = []
    if KIND_ENDORSEMENT in kinds:    types.append("a public endorsement")
    if KIND_EXEC_TRADE in kinds:     types.append("a disclosed executive-branch trade")
    if KIND_CONGRESS_TRADE in kinds: types.append("a congressional trade")
    if KIND_INSIDER in kinds:        types.append("a corporate insider Form 4")
    if KIND_SETUP in kinds:          types.append("an administration-tie / setup event")
    if len(types) >= 2:
        sentence += (f" The signal types are mixed — {_join(types)} — which is "
                     f"the more informative convergence: independent classes of "
                     f"insider all landing on the same name suggests something "
                     f"the broader market hasn't priced yet, vs. multiple actors "
                     f"in the same class (e.g. three congressional filings) which "
                     f"often reflects shared committee briefings rather than "
                     f"independent insight.")

    # WHY / price framing — the "did I miss it" check
    snap = snap_cache.get(t)
    mv = _pct_since(earliest, snap_cache)
    if snap and snap.get("price"):
        sentence += f" Now ~${snap['price']:.2f}"
        if snap.get("day_pct") is not None:
            arrow = "up" if snap["day_pct"] >= 0 else "down"
            sentence += f" ({arrow} {abs(snap['day_pct']):.1f}% on the day)"
        if mv is not None:
            if mv > 10:
                sentence += (f", already up {mv:.0f}% since the earliest signal "
                             f"on {earliest['event_date']} — that's well past the "
                             f"window where any post-signal alpha would still "
                             f"exist. Chasing here is the trap, not the trade.")
            elif mv > 5:
                sentence += (f", already up {mv:.0f}% since the earliest signal "
                             f"({earliest['event_date']}). The move that the "
                             f"signal would have flagged is likely in the price; "
                             f"treat this as confirmation of past action, not "
                             f"a fresh entry.")
            elif mv >= 0:
                sentence += (f", +{mv:.0f}% since the earliest signal "
                             f"({earliest['event_date']}) — within the noise "
                             f"window, so the signal hasn't obviously played out "
                             f"either way yet.")
            else:
                sentence += (f", down {abs(mv):.0f}% since the earliest signal "
                             f"({earliest['event_date']}). Either the signal "
                             f"was wrong, or the post-signal mean-reversion that "
                             f"the research warns about is doing its thing.")
        else:
            sentence += "."

    # source-density note
    src_total = sum(e.get("source_count", 1) for e in events)
    if src_total >= 5:
        sentence += (f" Reported across {src_total} sources total — the story "
                     f"is mainstream by now, which usually means the algos got "
                     f"the news first.")

    return sentence


# ---------------------------------------------------------------------------
# watchlist (non-convergence) paragraph
# ---------------------------------------------------------------------------

def _watchlist_paragraph(wl_only, snap_cache):
    """One paragraph touching every watchlist event that isn't already a convergence."""
    bits = []
    seen = set()
    for e in wl_only:
        t = e["ticker"]
        if t in seen:
            continue
        seen.add(t)
        sector = config.TICKER_SECTOR.get(t)
        verb = KIND_VERB.get(e["kind"], "had activity on")
        who = e["actor"] if e["actor"] not in ("News", "Insider", "Congress") else "an actor"
        mv = _pct_since(e, snap_cache)
        tail = ""
        if mv is not None:
            if mv > 5:
                tail = f" (already up {mv:.0f}% since — caution)"
            elif mv >= 0:
                tail = f" (+{mv:.0f}% since)"
            else:
                tail = f" (down {abs(mv):.0f}% since)"
        sector_tag = f" — {sector}" if sector else ""
        bits.append(f"<b>{t}</b>{sector_tag}: {who} {verb} it{tail}")
    body = "; ".join(bits)
    return (f"On your watchlist but not yet a convergence (single actor, single "
            f"signal type — interesting but not yet a cluster): {body}. These get "
            f"promoted to the top section automatically if a second independent "
            f"actor or signal type hits the same name within "
            f"{config.CONVERGENCE_WINDOW_DAYS} days.")


# ---------------------------------------------------------------------------
# setup signals paragraph
# ---------------------------------------------------------------------------

def _setup_paragraph(setups, snap_cache):
    bits = []
    seen = set()
    for e in setups[:6]:
        key = (e.get("ticker") or e["headline"][:40])
        if key in seen:
            continue
        seen.add(key)
        if e.get("ticker"):
            label = f"<b>{e['ticker']}</b>"
        else:
            label = "an unmatched name"
        bits.append(f"{label} — {e['headline'][:90]}")
    body = "; ".join(bits)
    return (f"Setup-style items today (contracts, government stakes, tariff "
            f"carve-outs, donations — the <i>leading</i> indicator class that "
            f"often precedes the endorsement or the trade): {body}. These are "
            f"worth flagging because the corporate side of an administration tie "
            f"tends to move <i>before</i> the public-facing signal does. They're "
            f"the closest thing in this dataset to a pre-pattern; convergences "
            f"that include a setup event are weighted heavier than convergences "
            f"of pure reactions.")


# ---------------------------------------------------------------------------
# sector cluster observation
# ---------------------------------------------------------------------------

def _sector_cluster_paragraph(new_events, convergences):
    """If 2+ events / convergences land in the same sector, narrate it."""
    sectors = Counter()
    for e in new_events:
        s = config.TICKER_SECTOR.get(e.get("ticker"))
        if s:
            sectors[s] += 1
    for t in convergences:
        s = config.TICKER_SECTOR.get(t)
        if s:
            sectors[s] += 2  # double-weight convergences

    hot = [(s, n) for s, n in sectors.most_common() if n >= 3]
    if not hot:
        return None

    bits = []
    for sector, n in hot:
        tickers = sorted({e["ticker"] for e in new_events
                          if config.TICKER_SECTOR.get(e.get("ticker")) == sector})
        bits.append(f"<b>{sector}</b> ({n} weighted hits across "
                    f"{', '.join(tickers[:6])})")
    return ("Sector-level pattern worth noting today: " + "; ".join(bits) + ". "
            "When multiple names in the same sector light up across independent "
            "signal types in the same window, the read-through is usually "
            "policy-driven rather than name-specific — a tariff posture, an "
            "export-control update, or a procurement cycle that lifts the "
            "whole basket. Watch the policy news in that vertical for the "
            "shared catalyst.")


# ---------------------------------------------------------------------------
# backtest interpretation
# ---------------------------------------------------------------------------

def _backtest_paragraph(backtest):
    if not backtest:
        return ("Backtest table empty for now — outcomes get logged at +1, +7, "
                "and +30 days after each event's <i>actual</i> date (which, for "
                "lagged feeds like congressional trades, may already have all "
                "three rows filled within days of first surfacing). Give it "
                "two to four weeks before drawing any conclusion. The point of "
                "the table is not to validate your gut; it's to test whether "
                "any of these signal classes have measurable post-event drift "
                "on <i>your</i> watchlist, in <i>your</i> sample, after the "
                "algos have done their work.")

    # find the loudest signal type with enough sample
    sortable = [r for r in backtest if (r["n"] or 0) >= 3]
    if not sortable:
        return ("Backtest table is building but no signal type yet has n≥3 at "
                "any horizon — the average % column will swing wildly until "
                "samples grow. Don't infer anything yet.")

    sortable.sort(key=lambda r: r["n"], reverse=True)
    top = sortable[0]
    avg = top["avg_pct"] or 0
    win = (top["win_rate"] or 0) * 100
    horizon = top["horizon_days"]
    kind_label = {
        KIND_ENDORSEMENT: "endorsements",
        KIND_EXEC_TRADE: "executive-branch disclosed trades",
        KIND_CONGRESS_TRADE: "congressional trades",
        KIND_INSIDER: "insider Form 4 filings",
        KIND_SETUP: "setup-style items",
    }.get(top["kind"], top["kind"])

    if avg <= -1:
        verdict = (f"which is the mean-reversion the research warns about, "
                   f"showing up in your own data. Acting on this signal in "
                   f"isolation has been a losing bet so far.")
    elif avg < 1:
        verdict = (f"effectively flat — within the noise band, no edge "
                   f"detectable above the typical daily volatility.")
    elif avg < 3:
        verdict = (f"modestly positive but small enough that transaction costs "
                   f"and slippage probably eat it. Not actionable on its own.")
    else:
        verdict = (f"meaningfully positive — large enough sample and effect to "
                   f"deserve a closer look. Re-check at higher n before sizing "
                   f"any real position; sample noise loves to flatter early "
                   f"backtests.")

    return (f"What your accumulated outcomes say so far: {kind_label} average "
            f"{avg:+.1f}% at +{horizon}d (win rate {win:.0f}%, n={top['n']}) — "
            f"{verdict} See the full backtest table below for all "
            f"kind × horizon combinations.")


# ---------------------------------------------------------------------------
# quiet day variant — gets a longer body so the email is still substantive
# ---------------------------------------------------------------------------

def _quiet_day_paragraphs(backtest):
    paras = []
    paras.append("<b>FRESH (last 24h):</b> nothing new dated today or yesterday.")
    paras.append("Nothing new tracked since the last run. That's the literal "
                 "majority of days for this dataset — most calendar days don't "
                 "produce a Trump endorsement, a tracked congressional filing, "
                 "or an open-market insider buy on any of your watchlist names. "
                 "A quiet inbox here is the baseline, not a failure of the tool.")
    paras.append("Worth noting what 'quiet' actually means: Google News RSS is "
                 "running, SEC EDGAR is being polled for every watchlist ticker, "
                 "and congressional providers were checked. Zero events means "
                 "either the feeds genuinely had nothing matching today, or one "
                 "feed silently rate-limited (which is rare but happens with "
                 "free scrapers). If you see 3+ consecutive quiet days, glance "
                 "at the workflow logs to confirm the source counts above the "
                 "TL;DR are nonzero before assuming the market is just calm.")
    bt = _backtest_paragraph(backtest)
    if bt:
        paras.append(bt)
    paras.append("Enjoy the coffee. Nothing to chase.")
    return paras


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pct_since(ev, snap_cache):
    ep = ev.get("event_price")
    snap = snap_cache.get(ev.get("ticker"))
    if ep and snap and snap.get("price"):
        return (snap["price"] - ep) / ep * 100
    return None


def _humanize_actors(actors):
    pretty = [a.capitalize() for a in actors]
    return _join(pretty)


def _humanize_kind(kind):
    return {
        KIND_ENDORSEMENT: "a public endorsement",
        KIND_EXEC_TRADE: "an executive-branch disclosed trade",
        KIND_CONGRESS_TRADE: "a congressional trade",
        KIND_INSIDER: "an insider Form 4 filing",
        KIND_SETUP: "an administration-tie / setup event",
        KIND_NEWS: "a news item",
    }.get(kind, kind)


def _actor_notes_for(actors):
    """Pull short qualitative notes from config.ACTOR_NOTES for known actors."""
    notes = []
    for a in actors:
        key = a.lower().strip()
        if key in config.ACTOR_NOTES:
            notes.append(f"{a.capitalize()} — {config.ACTOR_NOTES[key]}.")
    return " ".join(notes)


def _join(items):
    items = list(items)
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
