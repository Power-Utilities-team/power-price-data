"""
check_split_parity.py — the two halves of a split series must cover the same period.

WHY THIS EXISTS. Twelve of the published tables are frozen at the original five markets
because their Excel tables are a fixed 86 columns (see config.LEGACY_CSV_COUNTRIES), so a
sixth market's columns are published to a companion "_extra" file instead. That works, and
it introduces a failure nobody had before: the two halves now come from DIFFERENT SOURCES
with independent failure modes. The original five come from ENTSO-E; Great Britain comes
from Elexon. ENTSO-E can spend an afternoon returning 504 while Elexon answers every
request, and it did on 2026-08-25.

The result is a chart that pairs them showing one country running a month past the others,
with no gap and no warning: both files are valid, neither is shorter than it was, no column
moved, and the package is sound. It simply says something untrue about the market.

None of the other guards can see it. check_coverage compares each file against ITS OWN
previous version, so two files can drift apart while both individually grow.
check_reference_stability compares layout. check_consistency compares the decks.

WHAT IT COMPARES. For every legacy/extra pair, the last row index at which each side has
any data. A difference is reported with the period each side reaches, so the answer to
"which source is behind" is in the message rather than something to go and work out.

Exit 0 = both halves reach the same period, or there is nothing split.
"""
from __future__ import annotations

import csv
import os
import sys

import config as cfg

CHARTS = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")

# Legacy file -> its companion. Both are written by chart_csv.py from one lookup, so a
# pair appearing here that does not exist on disk means the build changed, not that the
# data is missing.
PAIRS = [
    ("capture_monthly.csv", "capture_monthly_extra.csv"),
    ("fig2_intraday_indexed.csv", "fig2_intraday_indexed_extra.csv"),
    ("fig3_cum_near_neg.csv", "fig3_cum_near_neg_extra.csv"),
    ("fig1_price_sd.csv", "fig1_price_sd_extra.csv"),
    ("fig3_neg_hours_annual.csv", "fig3_neg_hours_annual_extra.csv"),
]

# How far apart the two halves may legitimately sit. One row, because a genuinely current
# pair can differ by a single period purely on publication timing: the two sources do not
# publish at the same minute. Two is a source that has stopped.
TOLERANCE_ROWS = 1


def _last_populated(path):
    """(row index, that row's label) of the last row with any value beyond column A."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    if len(rows) < 2:
        return None, None
    for i in range(len(rows) - 1, 0, -1):
        if any(c.strip() for c in rows[i][1:]):
            return i, rows[i][0]
    return None, None


def check():
    errs, checked = [], 0
    for legacy, extra in PAIRS:
        lp, ep = os.path.join(CHARTS, legacy), os.path.join(CHARTS, extra)
        if not (os.path.exists(lp) and os.path.exists(ep)):
            continue
        checked += 1
        li, ll = _last_populated(lp)
        ei, el = _last_populated(ep)
        if li is None or ei is None:
            errs.append(f"{legacy} / {extra}: one half has no data at all "
                        f"({legacy} row {li}, {extra} row {ei})")
            continue
        if abs(li - ei) > TOLERANCE_ROWS:
            behind, ahead = ((legacy, ll), (extra, el)) if li < ei else ((extra, el), (legacy, ll))
            errs.append(
                f"{legacy} reaches {ll} and {extra} reaches {el} "
                f"({abs(li - ei)} periods apart) — {behind[0]} is behind at {behind[1]}, "
                f"so a chart pairing them shows one market running past the others")
    print(f"split parity: {checked} legacy/extra pair(s) compared", flush=True)
    return errs


def main():
    errs = check()
    if errs:
        print("SPLIT PARITY: FAIL", flush=True)
        for e in errs:
            print("  ✗", e, flush=True)
        print("\nBoth halves are valid and neither has shortened, so no other check sees\n"
              "this. Find which source is behind and re-fetch it.", flush=True)
        sys.exit(1)
    print("SPLIT PARITY: PASS — both halves of every split table reach the same period",
          flush=True)


if __name__ == "__main__":
    main()
