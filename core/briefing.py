"""
TLDR briefing — the human-readable top of the digest.

Turns the day's events + convergences into a short plain-English summary that
answers WHO did WHAT, WHY it matters, and HOW to read it. No new data; it just
narrates what the structured sections show, so you can read one paragraph over
coffee and decide whether to scroll.

Deterministic / template-based (no LLM, stays free and predictable). The tone
is deliberately flat — it describes, it does not hype, and it always closes the
loop on "is this already in the price."
"""

import datetime as dt

import config
from core.store import (KIND_ENDORSEMENT, KIND_EXEC_TRADE, KIND_CONGRESS_TRADE,
                        KIND_INSIDER, KIND_SETUP, KIND_NEWS)


KIND_VERB = {
    KIND_ENDORSEMENT: "publicly endorsed",
    KIND_EXEC_TRADE: "was disclosed buying",
    KIND_CONGRESS_TRADE: "traded",
    KIND_INSIDER: "saw an insider Form 4 on",
    KIND_SETUP: "tied itself to the administration via",
    KIND_NEWS: "was in the news re:",
}


def _pct_since(ev, snap_cache):
    """Return signed % move since the event, or None."""
    ep = ev.get("event_price")
    snap = snap_cache.get(ev.get("ticker"))
    if ep and snap and snap.get("price"):
        return (snap["price"] - ep) / ep * 100
    return None


def _ticker_name(t):
    return config.WATCHLIST.get(t, t)


def build(new_events, convergences, backtest, snap_cache):
    """
    Returns (headline_str, list_of_paragraph_strs). Used by both text and HTML
    digest builders so the TLDR is identical in both.
    """
    today = dt.date.today()
    paras = []

    n_events = len(new_events)
    n_conv = len(convergences)
    wl_hits = sorted({e["ticker"] for e in new_events
                      if e.get("ticker") in config.WATCHLIST})

    # --- headline line ---
    if n_conv:
        headline = (f"{n_conv} convergence "
                    f"{'signal' if n_conv == 1 else 'signals'} today"
                    + (f" · {len(wl_hits)} on your watchlist" if wl_hits else ""))
    elif wl_hits:
        headline = f"{len(wl_hits)} watchlist name{'s' if len(wl_hits)!=1 else ''} moved today"
    elif n_events:
        headline = f"{n_events} tracked event{'s' if n_events!=1 else ''}, nothing on your watchlist"
    else:
        headline = "Quiet day — nothing new"

    if not n_events and not n_conv:
        paras.append("No new tracked trades, endorsements, or filings since the "
                     "last run. Nothing to act on. Enjoy the coffee.")
        return headline, paras

    # --- convergence narration (the important part) ---
    if convergences:
        for t, info in sorted(convergences.items(),
                              key=lambda kv: len(kv[1]["actors"]), reverse=True):
            actors = sorted(info["actors"])
            actor_str = _humanize_actors(actors)
            kinds = info["kinds"]
            name = _ticker_name(t)

            # WHO + WHAT
            sentence = f"<b>{t} ({name})</b> is the name to look at: "
            if len(actors) >= 2:
                allboth = "both" if len(actors) == 2 else "all"
                sentence += f"{actor_str} {allboth} touched it"
            else:
                sentence += "multiple independent signals hit it"
            sentence += f" within the last {config.CONVERGENCE_WINDOW_DAYS} days"

            # HOW it showed up (signal types)
            types = []
            if KIND_ENDORSEMENT in kinds: types.append("a public endorsement")
            if KIND_EXEC_TRADE in kinds: types.append("a disclosed executive-branch trade")
            if KIND_CONGRESS_TRADE in kinds: types.append("a congressional trade")
            if KIND_INSIDER in kinds: types.append("a corporate insider filing")
            if KIND_SETUP in kinds: types.append("an administration-tie/setup event")
            if types:
                sentence += " — via " + _join(types) + "."
            else:
                sentence += "."

            # WHY it matters + the reversion caveat (the "did I miss it")
            ticker_events = [e for e in new_events if e.get("ticker") == t]
            mv = None
            for e in info["events"]:
                p = _pct_since(e, snap_cache)
                if p is not None:
                    mv = p if mv is None else mv
            snap = snap_cache.get(t)
            if snap and snap.get("price"):
                sentence += f" Now ~${snap['price']:.2f}"
                if mv is not None:
                    if mv > 5:
                        sentence += (f", already up {mv:.0f}% since the earliest signal — "
                                     f"the move is likely in the price; chasing here is the "
                                     f"trap, not the trade.")
                    elif mv >= 0:
                        sentence += f", +{mv:.0f}% since the earliest signal."
                    else:
                        sentence += f", down {abs(mv):.0f}% since the earliest signal."
                else:
                    sentence += "."
            paras.append(sentence)

    # --- watchlist-but-not-convergence summary ---
    wl_only = [e for e in new_events
               if e.get("ticker") in config.WATCHLIST
               and e.get("ticker") not in convergences]
    if wl_only:
        bits = []
        seen = set()
        for e in wl_only:
            t = e["ticker"]
            if t in seen:
                continue
            seen.add(t)
            verb = KIND_VERB.get(e["kind"], "had activity on")
            who = e["actor"] if e["actor"] not in ("News", "Insider") else "an actor"
            mv = _pct_since(e, snap_cache)
            tail = ""
            if mv is not None:
                tail = (f" (already +{mv:.0f}%)" if mv > 5
                        else f" ({'+' if mv>=0 else ''}{mv:.0f}% since)")
            bits.append(f"<b>{t}</b> — {who} {verb} it{tail}")
        if bits:
            paras.append("On your watchlist, no convergence but worth a glance: "
                         + "; ".join(bits) + ".")

    # --- firehose one-liner ---
    other_tickers = sorted({e["ticker"] for e in new_events
                            if e.get("ticker") and e["ticker"] not in config.WATCHLIST
                            and e["ticker"] not in convergences})
    if other_tickers and config.SHOW_FIREHOSE:
        paras.append("Also tracked (not your names): "
                     + ", ".join(other_tickers[:12])
                     + ("…" if len(other_tickers) > 12 else "") + ".")

    # --- backtest one-liner (the gut check) ---
    bt_line = _backtest_oneliner(backtest)
    if bt_line:
        paras.append(bt_line)

    return headline, paras


def _backtest_oneliner(backtest):
    """Surface the most relevant horizon for the loudest signal type."""
    if not backtest:
        return ("No outcome history yet — the backtest table fills in as events "
                "age past 1/7/30 days. Give it a few weeks before trusting any signal.")
    # find endorsement @7d if present (the classic reversion check)
    target = next((r for r in backtest
                   if r["kind"] == KIND_ENDORSEMENT and r["horizon_days"] == 7), None)
    if target and target["n"] >= 3:
        avg = target["avg_pct"] or 0
        win = (target["win_rate"] or 0) * 100
        verdict = ("which is the mean-reversion the research warns about — be skeptical of chasing"
                   if avg < 0 else "modestly positive so far, but small sample")
        return (f"Your data so far: endorsements average {avg:+.1f}% at 7 days "
                f"({win:.0f}% positive, n={target['n']}) — {verdict}.")
    return ("Backtest still building — not enough aged events yet to draw a "
            "conclusion. Keep letting it run before acting on any pattern.")


def _humanize_actors(actors):
    pretty = [a.capitalize() for a in actors]
    return _join(pretty)


def _join(items):
    items = list(items)
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"
