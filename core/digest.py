"""
Digest builder — turns events + convergences + backtest into an email.

Layout (designed as a scannable coffee read):
  1. ⚡ CONVERGENCE — tickers hit by 2+ actors/kinds. The thing to actually look at.
  2. ⭐ WATCHLIST — new events on tickers you own/track.
  3. 📋 EVERYTHING ELSE — other tracked events (only if SHOW_FIREHOSE).
  4. 📊 YOUR BACKTEST — running tally of how past signals actually performed.
  5. ⚠️ the standing reminder that this is awareness, not alpha.

Every line carries a WHY tag (kind) and, where possible, a price snapshot with
a "vs event price" so you can see whether you've ALREADY missed the move.
"""

import datetime as dt

import config
import re
from core.store import KIND_LABELS
from core import enrich, briefing


# ---- plain text ----------------------------------------------------------

def _wrap(text, width=72):
    import textwrap
    return "\n".join(textwrap.wrap(text, width)) or text

def _fmt_event_line(ev: dict, snap_cache: dict) -> str:
    tag = KIND_LABELS.get(ev["kind"], ev["kind"])
    ticker = ev.get("ticker") or "—"
    line = f"{tag}  {ticker}  {ev['headline']}"
    if ev.get("source_count", 1) > 1:
        line += f"  ({ev['source_count']} sources)"
    # price + did-i-miss-it
    if ev.get("ticker"):
        snap = snap_cache.get(ev["ticker"])
        if snap:
            line += f"\n        now {enrich.format_snapshot(snap)}"
            ep = ev.get("event_price")
            if ep and snap.get("price"):
                chg = (snap["price"] - ep) / ep * 100
                arrow = "▲" if chg >= 0 else "▼"
                line += f"  |  {arrow}{abs(chg):.1f}% since event (${ep:.2f})"
    if ev.get("detail"):
        line += f"\n        {ev['detail']}"
    if ev.get("url"):
        line += f"\n        {ev['url']}"
    return line


def build_text(new_events, convergences, backtest, snap_cache):
    today = dt.date.today().strftime("%A, %B %d, %Y")
    out = [f"POLITICAL & INSIDER TRADES DIGEST — {today}", "=" * 56, ""]

    # 0. TLDR briefing
    headline, paras = briefing.build(new_events, convergences, backtest, snap_cache)
    out.append(f"TL;DR — {headline}")
    out.append("-" * 56)
    for p in paras:
        # strip html bold for plaintext
        clean = re.sub(r"</?b>", "", p)
        out.append(_wrap(clean, 72))
        out.append("")

    # 1. convergence
    if convergences:
        out.append("⚡ CONVERGENCE — multiple actors on the same name")
        out.append("-" * 56)
        for t, info in sorted(convergences.items(),
                              key=lambda kv: len(kv[1]["actors"]), reverse=True):
            actors = ", ".join(sorted(info["actors"])) or "multiple signals"
            kinds = ", ".join(KIND_LABELS.get(k, k) for k in info["kinds"])
            out.append(f"\n  >>> {t} — {len(info['actors'])} actors: {actors}")
            out.append(f"      signal types: {kinds}")
            snap = snap_cache.get(t)
            if snap:
                out.append(f"      {enrich.format_snapshot(snap)}")
            for ev in sorted(info["events"], key=lambda e: e["event_date"], reverse=True)[:5]:
                out.append(f"        · [{ev['event_date']}] {KIND_LABELS.get(ev['kind'], ev['kind'])} {ev['headline'][:70]}")
        out.append("")

    # 2. watchlist new events
    wl_events = [e for e in new_events if e.get("ticker") in config.WATCHLIST]
    if wl_events:
        out.append("⭐ WATCHLIST — new events on your tickers")
        out.append("-" * 56)
        for ev in wl_events:
            out.append(_fmt_event_line(ev, snap_cache))
            out.append("")

    # 3. everything else
    other = [e for e in new_events if e.get("ticker") not in config.WATCHLIST]
    if other and config.SHOW_FIREHOSE:
        out.append("📋 OTHER TRACKED EVENTS")
        out.append("-" * 56)
        for ev in other:
            out.append(_fmt_event_line(ev, snap_cache))
            out.append("")

    if not new_events and not convergences:
        out.append("Nothing new today. Enjoy the coffee.\n")

    # 4. backtest
    if backtest:
        out.append("📊 YOUR BACKTEST — how past signals actually performed")
        out.append("-" * 56)
        out.append("  kind            horizon   n    avg%    win%")
        for row in backtest:
            out.append(
                f"  {row['kind'][:14]:<14}  +{row['horizon_days']:>3}d  "
                f"{row['n']:>3}  {row['avg_pct'] or 0:>6.1f}  "
                f"{(row['win_rate'] or 0)*100:>5.0f}%"
            )
        out.append("")

    # 5. standing reminder
    out.append("-" * 56)
    out.append("⚠️  Reminder: these signals are LAGGED and the move is usually")
    out.append("    already in the price. Endorsement/post pops tend to mean-revert.")
    out.append("    This digest is for awareness, not a buy list. Check the")
    out.append("    'since event' number before chasing anything green.")

    return "\n".join(out)


# ---- html ----------------------------------------------------------------

def build_html(new_events, convergences, backtest, snap_cache):
    today = dt.date.today().strftime("%A, %B %d, %Y")
    css = """
    <style>
      body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
           color:#1a1a1a;line-height:1.45;max-width:640px;margin:0 auto;padding:8px;}
      h1{font-size:18px;margin:0 0 4px;}
      .date{color:#666;font-size:13px;margin-bottom:16px;}
      .section{margin:20px 0 8px;font-size:13px;font-weight:700;
               text-transform:uppercase;letter-spacing:.5px;color:#333;
               border-bottom:2px solid #eee;padding-bottom:4px;}
      .conv{background:#fff8e1;border:1px solid #ffe08a;border-radius:8px;
            padding:10px 12px;margin:8px 0;}
      .conv .tk{font-size:16px;font-weight:700;}
      .ev{padding:8px 0;border-bottom:1px solid #f0f0f0;font-size:14px;}
      .tag{display:inline-block;font-size:11px;font-weight:700;padding:1px 6px;
           border-radius:4px;background:#eef;color:#334;margin-right:6px;}
      .tk{font-weight:700;}
      .meta{color:#666;font-size:12px;margin-top:2px;}
      .pos{color:#0a7d28;font-weight:600;} .neg{color:#c0392b;font-weight:600;}
      .miss{color:#b8860b;font-weight:600;}
      a{color:#2a6ebd;text-decoration:none;}
      table{border-collapse:collapse;font-size:13px;width:100%;}
      td,th{padding:4px 8px;text-align:left;border-bottom:1px solid #eee;}
      .warn{background:#fdecea;border:1px solid #f5c6cb;border-radius:8px;
            padding:10px 12px;margin-top:20px;font-size:13px;color:#611;}
      .tldr{background:#f4f7fb;border:1px solid #d6e2f0;border-radius:8px;
            padding:14px 16px;margin:8px 0 4px;}
      .tldr h2{font-size:14px;margin:0 0 8px;color:#234;text-transform:uppercase;
               letter-spacing:.5px;}
      .tldr p{margin:0 0 9px;font-size:14.5px;line-height:1.5;}
      .tldr p:last-child{margin-bottom:0;}
    </style>"""

    def snap_html(t):
        snap = snap_cache.get(t)
        if not snap:
            return ""
        return f'<div class="meta">now {enrich.format_snapshot(snap)}</div>'

    def since_html(ev):
        ep = ev.get("event_price"); snap = snap_cache.get(ev.get("ticker"))
        if ep and snap and snap.get("price"):
            chg = (snap["price"] - ep) / ep * 100
            cls = "miss" if chg > 5 else ("pos" if chg >= 0 else "neg")
            arrow = "▲" if chg >= 0 else "▼"
            note = " (already ran)" if chg > 5 else ""
            return f'<span class="{cls}">{arrow}{abs(chg):.1f}% since event{note}</span>'
        return ""

    h = [css, f"<h1>📈 Political &amp; Insider Trades Digest</h1>",
         f'<div class="date">{today}</div>']

    # TLDR briefing card
    headline, paras = briefing.build(new_events, convergences, backtest, snap_cache)
    h.append('<div class="tldr">')
    h.append(f'<h2>TL;DR — {headline}</h2>')
    for p in paras:
        h.append(f'<p>{p}</p>')
    h.append('</div>')

    if convergences:
        h.append('<div class="section">⚡ Convergence — multiple actors, same name</div>')
        for t, info in sorted(convergences.items(),
                              key=lambda kv: len(kv[1]["actors"]), reverse=True):
            actors = ", ".join(sorted(info["actors"])) or "multiple signal types"
            kinds = " · ".join(KIND_LABELS.get(k, k) for k in info["kinds"])
            h.append('<div class="conv">')
            h.append(f'<div class="tk">{t} — {len(info["actors"])} actors</div>')
            h.append(f'<div class="meta">{actors}<br>{kinds}</div>')
            h.append(snap_html(t))
            for ev in sorted(info["events"], key=lambda e: e["event_date"], reverse=True)[:5]:
                h.append(f'<div class="meta">· [{ev["event_date"]}] '
                         f'{KIND_LABELS.get(ev["kind"], ev["kind"])} {ev["headline"][:80]}</div>')
            h.append('</div>')

    wl = [e for e in new_events if e.get("ticker") in config.WATCHLIST]
    if wl:
        h.append('<div class="section">⭐ Watchlist</div>')
        for ev in wl:
            h.append(_ev_html(ev, snap_html, since_html))

    other = [e for e in new_events if e.get("ticker") not in config.WATCHLIST]
    if other and config.SHOW_FIREHOSE:
        h.append('<div class="section">📋 Other tracked events</div>')
        for ev in other:
            h.append(_ev_html(ev, snap_html, since_html))

    if not new_events and not convergences:
        h.append("<p>Nothing new today. Enjoy the coffee. ☕</p>")

    if backtest:
        h.append('<div class="section">📊 Your backtest</div>')
        h.append("<table><tr><th>Kind</th><th>Horizon</th><th>n</th>"
                 "<th>Avg %</th><th>Win %</th></tr>")
        for row in backtest:
            h.append(f"<tr><td>{row['kind']}</td><td>+{row['horizon_days']}d</td>"
                     f"<td>{row['n']}</td><td>{row['avg_pct'] or 0:.1f}</td>"
                     f"<td>{(row['win_rate'] or 0)*100:.0f}%</td></tr>")
        h.append("</table>")

    h.append('<div class="warn">⚠️ <b>Reminder:</b> these signals are lagged and '
             'the move is usually already in the price. Endorsement/post pops tend '
             'to mean-revert. This is for awareness, not a buy list — check the '
             '"since event" number before chasing anything green.</div>')
    return "\n".join(h)


def _ev_html(ev, snap_html, since_html):
    tag = KIND_LABELS.get(ev["kind"], ev["kind"])
    ticker = ev.get("ticker") or "—"
    src = f' · {ev["source_count"]} sources' if ev.get("source_count", 1) > 1 else ""
    detail = f'<br>{ev["detail"]}' if ev.get("detail") else ""
    url = f' · <a href="{ev["url"]}">link</a>' if ev.get("url") else ""
    return (f'<div class="ev"><span class="tag">{tag}</span>'
            f'<span class="tk">{ticker}</span> {ev["headline"]}'
            f'<div class="meta">{since_html(ev)}{src}{url}{detail}</div>'
            f'{snap_html(ev.get("ticker")) if ev.get("ticker") else ""}</div>')
