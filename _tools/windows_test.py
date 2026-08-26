"""windows_test.py — the block splitter must lose nothing and duplicate nothing.

The properties that matter are not "it returns eight blocks". They are that the blocks
exactly tile the window, that no block spans a month boundary (which is what makes each
request small enough for ENTSO-E's gateway), and that a trailing window never reaches back
into the previous year's file.

Deliberately no network. This is arithmetic on timestamps and is tested as such.
"""
from __future__ import annotations

import sys

import pandas as pd

import windows as w

TZ = "Europe/Brussels"
fails = []


def check(ok, name, extra=None):
    print(f"  {'ok  ' if ok else 'FAIL'}  {name}"
          + ("" if ok or extra is None else f"   {extra}"), flush=True)
    if not ok:
        fails.append(name)


def ts(s):
    return pd.Timestamp(s, tz=TZ)


# ---- tiling -----------------------------------------------------------------------------
S, E = ts("2026-01-01"), ts("2026-08-26")
blocks = w.month_blocks(S, E)
check(len(blocks) == 8, "Jan to late Aug splits into eight blocks", len(blocks))
check(blocks[0][0] == S, "the first block starts where the window does")
check(blocks[-1][1] == E, "the last block ends where the window does")
check(all(b[1] == blocks[i + 1][0] for i, b in enumerate(blocks[:-1])),
      "consecutive blocks share an edge, so nothing is skipped")
check(all(a < b for a, b in blocks), "every block is non-empty")

# THE property, stated as coverage rather than as a block count: every quarter-hour in the
# window falls in exactly one block. A count can be right while the tiling is wrong.
pts = pd.date_range(S, E, freq="15min", inclusive="left")
covered = sum(((pts >= a) & (pts < b)).sum() for a, b in blocks)
check(covered == len(pts),
      "every quarter-hour is covered exactly once", f"{covered} vs {len(pts)}")

# No block spans a month boundary, which is the whole reason for splitting.
def same_month(a, b):
    last = b - pd.Timedelta(seconds=1)
    return (a.year, a.month) == (last.year, last.month)
check(all(same_month(a, b) for a, b in blocks),
      "no block spans a month boundary")

# ---- degenerate and short windows -------------------------------------------------------
check(w.month_blocks(ts("2026-03-05"), ts("2026-03-05")) == [],
      "an empty window yields no blocks")
check(w.month_blocks(ts("2026-03-10"), ts("2026-03-01")) == [],
      "a reversed window yields no blocks rather than raising")
one = w.month_blocks(ts("2026-03-05"), ts("2026-03-20"))
check(len(one) == 1 and one[0] == (ts("2026-03-05"), ts("2026-03-20")),
      "a window inside one month is a single block", one)
# A window that starts exactly on a month boundary must not emit a zero-length first block.
edge = w.month_blocks(ts("2026-03-01"), ts("2026-04-01"))
check(len(edge) == 1 and edge[0] == (ts("2026-03-01"), ts("2026-04-01")),
      "a window that is exactly one month is one block, not two", edge)

# ---- the trailing window ----------------------------------------------------------------
YS = ts("2026-01-01")
check(w.fetch_start(YS, ts("2026-08-26"), full=True) == YS,
      "a full fetch starts at the year's start")
check(w.fetch_start(YS, ts("2026-08-26"), full=False, trailing_days=45)
      == ts("2026-08-26") - pd.Timedelta(days=45),
      "a normal fetch starts one trailing window back")
# THE clamp that matters: in January the window would reach into last year's file, and a
# raw file holds exactly one calendar year. Reaching back would write rows into the wrong
# one, which is the class of fault that cost France and Italy six months on 2026-07-31.
check(w.fetch_start(YS, ts("2026-01-10"), full=False, trailing_days=45) == YS,
      "in January it clamps to the year's start rather than reaching into last year")

# And the trailing window must still tile correctly once split.
tstart = w.fetch_start(YS, ts("2026-08-26"), full=False)
tblocks = w.month_blocks(tstart, ts("2026-08-26"))
check(len(tblocks) == 2, "a 45-day window is one or two blocks, not eight", len(tblocks))
tpts = pd.date_range(tstart, ts("2026-08-26"), freq="15min", inclusive="left")
tcov = sum(((tpts >= a) & (tpts < b)).sum() for a, b in tblocks)
check(tcov == len(tpts), "and it covers its own window exactly once")

print("WINDOWS: " + ("FAIL " + ", ".join(fails) if fails else "PASS"), flush=True)
sys.exit(1 if fails else 0)
