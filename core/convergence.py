"""
Convergence detection — the headline signal.

A convergence = the same ticker touched by CONVERGENCE_MIN_ACTORS or more
DISTINCT actors within CONVERGENCE_WINDOW_DAYS. A single politician trading is
noise; multiple independent informed actors landing on the same name in the
same window is a cluster worth a look.

"Distinct actors" is judged by a normalized actor key so that "Nancy Pelosi"
and "Pelosi" count once, and generic "News" doesn't inflate the count.
"""

import datetime as dt
from collections import defaultdict

import config
from core.store import Store


GENERIC_ACTORS = {"news", "insider", "congress"}


def _actor_key(actor: str) -> str:
    a = (actor or "").lower().strip()
    if a in GENERIC_ACTORS or not a:
        return a
    # use last name token as the identity key (handles "Nancy Pelosi"/"Pelosi")
    return a.split()[-1]


def detect(store: Store):
    """
    Returns dict: ticker -> {
        'actors': set of distinct actor keys,
        'events': list of event dicts,
        'kinds': set of kinds involved,
    }
    for every ticker meeting the convergence threshold.
    """
    events = store.recent_events(config.CONVERGENCE_WINDOW_DAYS)

    by_ticker = defaultdict(lambda: {"actors": set(), "events": [], "kinds": set()})
    for ev in events:
        t = ev["ticker"]
        ak = _actor_key(ev["actor"])
        if ak and ak not in GENERIC_ACTORS:
            by_ticker[t]["actors"].add(ak)
        by_ticker[t]["events"].append(ev)
        by_ticker[t]["kinds"].add(ev["kind"])

    convergences = {}
    for t, info in by_ticker.items():
        # Count distinct *named* actors; also count distinct event KINDS as a
        # secondary signal (an endorsement + an insider buy on the same name is
        # a convergence even if only one named actor).
        n_actors = len(info["actors"])
        n_kinds = len(info["kinds"])
        if n_actors >= config.CONVERGENCE_MIN_ACTORS or n_kinds >= config.CONVERGENCE_MIN_ACTORS:
            convergences[t] = info

    return convergences
