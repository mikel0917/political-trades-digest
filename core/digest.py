"""
Digest builder — turns events + convergences + backtest into an email.

Layout (designed as one clean scannable read, no section duplication):

  1. TL;DR             — the long-form narrative (from core.briefing)
  2. TICKERS TODAY     — one compact card per ticker, sorted by signal
                         strength. Replaces the previous CONVERGENCE /
                         WATCHLIST / OTHER sections that all listed the
                         same names. Every ticker appears once.
  3. BACKTEST table    — aligned, with % signs and a header row
  4. Standing reminder — lag + mean-reversion caveat
"""

import datetime as dt
import re
import textwrap

import config
from core.store import KIND_LABELS
from core import enrich, briefing


# ---------------------------------------------------------------------------
# helpers shared by text + html
# ---------------------------------------------------------------------------

def _pct_since_earliest(events, snap_cache):
    """% change from the earliest event_price for these events to now."""
    if not events:
        return None
    events = sorted(events, key=lambda e: e["event_date"])
    for e in events:
        ep = e.get("event_price")
        snap = snap_cache.get(e.get("ticker"))
        if ep and snap and snap.get("price"):
            return (snap["price"] - ep) / ep * 100, e["event_date"]
    return None


def _ticker_order(convergences, new_events, fresh_24h=None):
    """
    Return a list of (ticker, events_for_card, priority_class, conv_info).

    priority_class is one of: "convergence", "watchlist", "other".
    Each ticker appears at most once. Sorted: convergences first (by
    actor count then kind count), then watchlist names, then others.

    Event source for each card:
      - convergence ticker -> full 45d event list from convergence detection
      - watchlist / other ticker -> union of new_events + fresh_24h for that
        ticker (deduped by dedup_key). This keeps recent-by-date items
        visible even after they've been marked notified.
    """
    seen = set()
    rows = []

    # union new_events + fresh_24h, dedup by key
    combined = {}
    for e in (new_events or []) + (fresh_24h or []):
        k = e.get("dedup_key") or id(e)
        if k not in combined:
            combined[k] = e

    # convergences first
    for t, info in sorted(
        convergences.items(),
        key=lambda kv: (len(kv[1]["actors"]), len(kv[1]["kinds"])),
        reverse=True,
    ):
        rows.append((t,
                     sorted(info["events"],
                            key=lambda e: e["event_date"], reverse=True),
                     "convergence", info))
        seen.add(t)

    # group remaining events by ticker
    by_ticker = {}
    for e in combined.values():
        t = e.get("ticker")
        if t and t not in seen:
            by_ticker.setdefault(t, []).append(e)

    # watchlist tickers
    wl_tickers = [t for t in by_ticker if t in config.WATCHLIST]
    for t in sorted(wl_tickers,
                    key=lambda t: max(e["event_date"] for e in by_ticker[t]),
                    reverse=True):
        rows.append((t,
                     sorted(by_ticker[t],
                            key=lambda e: e["event_date"], reverse=True),
                     "watchlist", None))
        seen.add(t)

    # other tickers (firehose only)
    if config.SHOW_FIREHOSE:
        other_tickers = [t for t in by_ticker if t not in seen]
        for t in sorted(other_tickers,
                        key=lambda t: max(e["event_date"] for e in by_ticker[t]),
                        reverse=True):
            rows.append((t,
                         sorted(by_ticker[t],
                                key=lambda e: e["event_date"], reverse=True),
                         "other", None))
            seen.add(t)

    return rows


def _kind_short(kind):
    """Compact kind label for table-style listing."""
    return {
        "endorsement":    "📣 ENDORSE",
        "exec_trade":     "🏛️  EXEC",
        "congress_trade": "🏦 CONGRESS",
        "insider_buy":    "👔 INSIDER",
        "setup":          "🔧 SETUP",
        "news":           "📰 NEWS",
    }.get(kind, kind.upper())


# ---------------------------------------------------------------------------
# plain text builder
# ---------------------------------------------------------------------------

def _wrap(text, width=72):
    return "\n".join(textwrap.wrap(text, width)) or text


def build_text(new_events, convergences, backtest, snap_cache, fresh_24h=None):
    today_h = dt.date.today().strftime("%A, %B %d, %Y")
    out = []
    out.append(f"POLITICAL & INSIDER TRADES DIGEST — {today_h}")
    out.append("=" * 64)
    out.append("")

    # --- TL;DR ---
    headline, paras = briefing.build(new_events, convergences, backtest,
                                     snap_cache, fresh_24h)
    out.append(f"TL;DR — {headline}")
    out.append("─" * 64)
    for p in paras:
        clean = re.sub(r"<br\s*/?>", "\n", p)
        clean = re.sub(r"</?(b|i|em|strong)>", "", clean)
        for line in clean.split("\n"):
            out.append(_wrap(line, 72) if line.strip() else "")
        out.append("")

    # --- TICKERS TODAY ---
    rows = _ticker_order(convergences, new_events, fresh_24h)
    if rows:
        out.append("")
        out.append("─" * 64)
        out.append(f"TICKERS TODAY  ({len(rows)} name{'s' if len(rows)!=1 else ''}, "
                   f"sorted by signal strength)")
        out.append("─" * 64)
        out.append("")
        for t, events, klass, conv_info in rows:
            out.append(_ticker_card_text(t, events, klass, conv_info, snap_cache))
            out.append("")
    elif not convergences:
        out.append("Nothing new on watchlist or convergences today.")
        out.append("")

    # --- BACKTEST ---
    if backtest:
        out.append("─" * 64)
        out.append("BACKTEST — how past signals have performed for you")
        out.append("─" * 64)
        out.append("")
        out.append(f"  {'Signal':<16}  {'Horizon':>7}  {'n':>3}   {'Avg %':>7}   {'Win %':>5}")
        out.append("  " + "─" * 52)
        for row in backtest:
            avg = row["avg_pct"] or 0
            out.append(
                f"  {row['kind'][:16]:<16}  "
                f"{'+' + str(row['horizon_days']) + 'd':>7}  "
                f"{row['n']:>3}   "
                f"{avg:>+6.1f}%   "
                f"{(row['win_rate'] or 0)*100:>4.0f}%"
            )
        out.append("")

    # --- standing reminder ---
    out.append("─" * 64)
    out.append("⚠️  These signals are LAGGED — the move is usually already in")
    out.append("    the price by the time you read this. Endorsement/post pops")
    out.append("    tend to mean-revert. Awareness, not alpha. Check the")
    out.append("    'since' number before chasing anything green.")

    return "\n".join(out)


def _ticker_card_text(t, events, klass, conv_info, snap_cache):
    """Render one ticker's card in plain text."""
    name = config.WATCHLIST.get(t, "")
    sector = config.TICKER_SECTOR.get(t, "")
    snap = snap_cache.get(t)

    # header line: BADGE TICKER  NAME ........... $PRICE  ±DAY%
    badge = {
        "convergence": "⚡",
        "watchlist":   "⭐",
        "other":       " •",
    }[klass]
    price_bit = ""
    if snap and snap.get("price"):
        price_bit = f"${snap['price']:.2f}"
        if snap.get("day_pct") is not None:
            arrow = "▲" if snap["day_pct"] >= 0 else "▼"
            price_bit += f"  {arrow}{abs(snap['day_pct']):.1f}%"
    left = f"{badge} {t:<5} {name}"
    # right-align price bit at column 64
    pad = max(2, 64 - len(left) - len(price_bit))
    lines = [f"{left}{' ' * pad}{price_bit}"]

    # tag line: sector · watchlist · convergence badge with details
    tag_bits = []
    if sector:
        tag_bits.append(sector)
    if t in config.WATCHLIST and klass != "convergence":
        tag_bits.append("⭐ watchlist")
    if klass == "convergence" and conv_info:
        n_act = len(conv_info["actors"])
        n_knd = len(conv_info["kinds"])
        tag_bits.append(f"CONVERGENCE ({n_act} actor{'s' if n_act!=1 else ''}, "
                        f"{n_knd} kind{'s' if n_knd!=1 else ''})")
    if tag_bits:
        lines.append("   " + " · ".join(tag_bits))

    # events list — one per line
    for e in events[:6]:
        srcs = e.get("source_count", 1)
        src_bit = f"  ({srcs} src)" if srcs > 1 else ""
        headline = e["headline"][:55] + ("…" if len(e["headline"]) > 55 else "")
        kind = _kind_short(e["kind"])
        lines.append(f"   • {e['event_date']}  {kind:<14}  {headline}{src_bit}")

    # price-since-earliest summary
    chg = _pct_since_earliest(events, snap_cache)
    if chg is not None:
        pct, since = chg
        arrow = "▲" if pct >= 0 else "▼"
        if pct > 5:
            tail = " — already ran; chasing here is the trap"
        elif pct < -5:
            tail = " — post-signal reversion may be doing its thing"
        else:
            tail = " — still within the noise window"
        lines.append(f"   {arrow} {abs(pct):.1f}% since earliest signal "
                     f"({since}){tail}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(new_events, convergences, backtest, snap_cache, fresh_24h=None):
    today_h = dt.date.today().strftime("%A, %B %d, %Y")
    css = """
    <style>
      body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
           color:#1a1a1a;line-height:1.5;max-width:680px;margin:0 auto;padding:12px;}
      h1{font-size:19px;margin:0 0 4px;}
      .date{color:#666;font-size:13px;margin-bottom:18px;}
      .section{margin:24px 0 10px;font-size:12px;font-weight:700;
               text-transform:uppercase;letter-spacing:.7px;color:#444;
               border-bottom:2px solid #e6e6e6;padding-bottom:5px;}
      .section .sub{font-weight:400;color:#888;text-transform:none;letter-spacing:0;}
      .tldr{background:#f4f7fb;border:1px solid #d6e2f0;border-radius:8px;
            padding:16px 18px;margin:10px 0 4px;}
      .tldr h2{font-size:14px;margin:0 0 10px;color:#234;text-transform:uppercase;
               letter-spacing:.5px;}
      .tldr p{margin:0 0 10px;font-size:14.5px;line-height:1.55;}
      .tldr p:last-child{margin-bottom:0;}
      .card{border:1px solid #e6e6e6;border-radius:8px;padding:12px 14px;
            margin:10px 0;}
      .card.conv{background:#fff8e1;border-color:#f0c97a;}
      .card.wl{background:#fbfbf3;border-color:#e0d8a0;}
      .card .hd{display:flex;justify-content:space-between;align-items:baseline;
                gap:8px;}
      .card .tk{font-size:17px;font-weight:700;}
      .card .nm{color:#444;font-weight:500;}
      .card .px{font-size:15px;font-weight:600;white-space:nowrap;}
      .card .px.pos{color:#0a7d28;} .card .px.neg{color:#c0392b;}
      .card .tags{margin:4px 0 8px;font-size:12px;color:#666;}
      .card .badge{display:inline-block;font-size:10.5px;font-weight:700;
                   padding:1.5px 7px;border-radius:4px;letter-spacing:.4px;
                   text-transform:uppercase;}
      .card .badge.conv{background:#ffe08a;color:#5a3d00;}
      .card .badge.wl{background:#fff0b8;color:#5a4a00;}
      .ev{font-size:13.5px;color:#333;padding:3px 0;border-top:1px solid #f0f0f0;}
      .ev:first-of-type{border-top:none;padding-top:6px;}
      .ev .when{color:#777;font-variant-numeric:tabular-nums;}
      .ev .kind{display:inline-block;min-width:90px;font-weight:600;color:#445;}
      .ev .src{color:#999;font-size:12px;}
      .since{margin-top:8px;font-size:13px;}
      .since.pos{color:#0a7d28;} .since.neg{color:#c0392b;}
      .since.miss{color:#a25c00;font-weight:600;}
      a{color:#2a6ebd;text-decoration:none;}
      table.bt{border-collapse:collapse;font-size:13px;width:100%;
               margin-top:8px;font-variant-numeric:tabular-nums;}
      table.bt th{background:#f0f0f4;text-align:left;
                  padding:6px 10px;border-bottom:2px solid #d0d0d8;
                  font-size:11.5px;text-transform:uppercase;letter-spacing:.4px;
                  color:#445;}
      table.bt td{padding:6px 10px;border-bottom:1px solid #eee;}
      table.bt td.num{text-align:right;}
      table.bt td.pos{color:#0a7d28;font-weight:600;}
      table.bt td.neg{color:#c0392b;font-weight:600;}
      .warn{background:#fdecea;border:1px solid #f5c6cb;border-radius:8px;
            padding:11px 14px;margin-top:22px;font-size:13px;color:#611;}
    </style>"""

    h = [css,
         "<h1>📈 Political &amp; Insider Trades Digest</h1>",
         f'<div class="date">{today_h}</div>']

    # --- TLDR ---
    headline, paras = briefing.build(new_events, convergences, backtest,
                                     snap_cache, fresh_24h)
    h.append('<div class="tldr">')
    h.append(f'<h2>TL;DR — {headline}</h2>')
    for p in paras:
        h.append(f'<p>{p}</p>')
    h.append('</div>')

    # --- TICKERS TODAY ---
    rows = _ticker_order(convergences, new_events, fresh_24h)
    if rows:
        h.append(f'<div class="section">Tickers today '
                 f'<span class="sub">— {len(rows)} name'
                 f'{"s" if len(rows)!=1 else ""}, sorted by signal strength</span></div>')
        for t, events, klass, conv_info in rows:
            h.append(_ticker_card_html(t, events, klass, conv_info, snap_cache))
    elif not convergences:
        h.append('<p>Nothing new on watchlist or convergences today. ☕</p>')

    # --- BACKTEST ---
    if backtest:
        h.append('<div class="section">Backtest '
                 '<span class="sub">— how past signals have performed for you</span></div>')
        h.append('<table class="bt">')
        h.append('<tr><th>Signal</th><th>Horizon</th>'
                 '<th class="num">n</th><th class="num">Avg %</th>'
                 '<th class="num">Win %</th></tr>')
        for row in backtest:
            avg = row["avg_pct"] or 0
            cls = "pos" if avg > 0.5 else ("neg" if avg < -0.5 else "")
            sign = "+" if avg >= 0 else ""
            h.append(
                f'<tr><td>{row["kind"]}</td>'
                f'<td>+{row["horizon_days"]}d</td>'
                f'<td class="num">{row["n"]}</td>'
                f'<td class="num {cls}">{sign}{avg:.1f}%</td>'
                f'<td class="num">{(row["win_rate"] or 0)*100:.0f}%</td></tr>'
            )
        h.append('</table>')

    # --- standing reminder ---
    h.append('<div class="warn">⚠️ <b>These signals are lagged.</b> The move is '
             'usually already in the price by the time you read this. '
             'Endorsement / post pops tend to mean-revert. Awareness, not '
             'alpha — check the "since" number before chasing anything green.</div>')

    return "\n".join(h)


def _ticker_card_html(t, events, klass, conv_info, snap_cache):
    """Render one ticker's card in HTML."""
    name = config.WATCHLIST.get(t, "")
    sector = config.TICKER_SECTOR.get(t, "")
    snap = snap_cache.get(t)

    card_cls = {"convergence": "card conv", "watchlist": "card wl",
                "other": "card"}[klass]

    # header: ticker + name + price
    px_html = ""
    if snap and snap.get("price"):
        day_pct = snap.get("day_pct")
        px_cls = "" if day_pct is None else ("pos" if day_pct >= 0 else "neg")
        px_html = f'<div class="px {px_cls}">${snap["price"]:.2f}'
        if day_pct is not None:
            arrow = "▲" if day_pct >= 0 else "▼"
            px_html += f' {arrow}{abs(day_pct):.1f}%'
        px_html += '</div>'

    name_html = f' <span class="nm">{name}</span>' if name else ""
    head = (f'<div class="hd"><div><span class="tk">{t}</span>{name_html}</div>'
            f'{px_html}</div>')

    # tag row: sector + badges
    tag_bits = []
    if sector:
        tag_bits.append(sector)
    if klass == "convergence" and conv_info:
        n_act = len(conv_info["actors"])
        n_knd = len(conv_info["kinds"])
        tag_bits.append(f'<span class="badge conv">⚡ Convergence · '
                        f'{n_act} actor{"s" if n_act!=1 else ""} · '
                        f'{n_knd} kind{"s" if n_knd!=1 else ""}</span>')
    elif klass == "watchlist":
        tag_bits.append('<span class="badge wl">⭐ Watchlist</span>')
    tags_html = ('<div class="tags">' + " &nbsp;·&nbsp; ".join(tag_bits) + '</div>'
                 if tag_bits else "")

    # events
    ev_html = []
    for e in events[:6]:
        srcs = e.get("source_count", 1)
        src_bit = f' <span class="src">· {srcs} src</span>' if srcs > 1 else ""
        url = f' <a href="{e["url"]}">↗</a>' if e.get("url") else ""
        kind = _kind_short(e["kind"])
        head_text = e["headline"][:90] + ("…" if len(e["headline"]) > 90 else "")
        ev_html.append(
            f'<div class="ev"><span class="when">{e["event_date"]}</span> '
            f'<span class="kind">{kind}</span> {head_text}{src_bit}{url}</div>'
        )

    # since-earliest summary
    chg_block = ""
    chg = _pct_since_earliest(events, snap_cache)
    if chg is not None:
        pct, since = chg
        arrow = "▲" if pct >= 0 else "▼"
        if pct > 5:
            cls, tail = "miss", " — already ran; chasing here is the trap"
        elif pct < -5:
            cls, tail = "neg", " — post-signal reversion may be doing its thing"
        elif pct >= 0:
            cls, tail = "pos", " — still in the noise window"
        else:
            cls, tail = "neg", " — drifting against the signal"
        chg_block = (f'<div class="since {cls}">{arrow} {abs(pct):.1f}% since '
                     f'earliest signal ({since}){tail}</div>')

    return f'<div class="{card_cls}">{head}{tags_html}{"".join(ev_html)}{chg_block}</div>'
