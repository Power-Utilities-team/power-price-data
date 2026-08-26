"""windows.py — how much of the year to ask ENTSO-E for, and in what pieces.

TWO SEPARATE DECISIONS, deliberately kept apart, because conflating them is what produced
the fault this replaces.

  1. HOW MUCH to fetch. Normally a trailing window; the whole year only when something went
     wrong (Fred, 2026-08-26: "trailing window, periodic full only in case of error").
  2. HOW to ask for it. Never as one request spanning months, always in month-sized blocks.

WHY A TRAILING WINDOW IS ENOUGH. Measured 2026-08-26: German January re-fetched today came
back identical to what was stored, 0 differing cells out of 50,524 for generation and 0 out
of 2,972 for price. So re-pulling January in August buys nothing, and re-pulling it eight
times a month buys nothing eight times. That is one month of one market at one moment, so
the claim is "old months are settled", NOT "ENTSO-E never restates". Recent weeks are where
restatement actually happens, and the trailing window covers exactly those.

The previous design was a 30-day trailing window, dropped because it "could only ever
rewrite the last 30 days": a file that went bad in March would stay bad for ever. That
objection is real and is answered by the error path rather than by re-pulling everything
every time. The gaps record names the series that failed, and the repair run re-fetches
those in full. (That record raised NameError on every partial fetch until 2026-08-26, so
this design depends on a mechanism that had never once run. See undefined_names_test.py.)

WHY MONTH BLOCKS. Measured the same day, against the live API, for the German generation
window that had just failed in production:

    one request, 2026-01-01..2026-08-26   FAILED, HTTP 504 after 180s
    eight monthly requests                ALL SUCCEEDED, 341s total

The 504 is a gateway giving up on generating a huge response, not a rate limit, so retrying
the identical request cannot work. Production retried it three times with 20s, 40s and 80s
backoff and then gave up, spending 16 minutes to fetch nothing.

AND WHY NOT "SPLIT WHEN A 504 ARRIVES", which is the more elegant-looking option and was
rejected on measurement. Every 504 costs the full timeout BEFORE the code learns to split:
eight months fails at 180s, two four-month halves may each fail again, and the search pays
three minutes a level to discover what a fixed monthly schedule knows for nothing. Adaptive
splitting is only cheaper when failures are rare; here the whole-window request fails every
time.

entsoe-py will not do this for us: its `query_generation` carries `@year_limited`, which
splits at year boundaries and nowhere else, so any sub-year window is one HTTP request.
"""
from __future__ import annotations

import pandas as pd

# Roughly six weeks. Long enough to cover ENTSO-E restating recent days, short enough that a
# normal run asks for one or two blocks rather than eight. Not tuned to a measurement of
# restatement lag, because no such measurement exists yet: it is a deliberate over-estimate,
# and the error path is what makes an under-estimate survivable rather than permanent.
TRAILING_DAYS = 45


def month_blocks(start: pd.Timestamp, end: pd.Timestamp):
    """[(a, b), ...] covering [start, end) in blocks that never span a month boundary.

    Half-open throughout, so consecutive blocks share an edge and no timestamp is fetched
    twice or skipped. A window shorter than a month yields exactly one block.
    """
    if start >= end:
        return []
    edges = [start]
    # MS = month start. Anything strictly inside the window becomes a cut.
    for ts in pd.date_range(start, end, freq="MS", tz=start.tz):
        if start < ts < end:
            edges.append(ts)
    edges.append(end)
    return list(zip(edges[:-1], edges[1:]))


def fetch_start(year_start: pd.Timestamp, end: pd.Timestamp, full: bool,
                trailing_days: int = TRAILING_DAYS) -> pd.Timestamp:
    """Where a fetch should begin: the year's start when `full`, else the trailing window.

    Never earlier than `year_start`, because a raw file holds one calendar year and a window
    reaching back past January would write rows belonging to the previous year's file.
    """
    if full:
        return year_start
    cut = end - pd.Timedelta(days=trailing_days)
    return max(year_start, cut)
