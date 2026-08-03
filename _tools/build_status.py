"""Publish status.csv — the health record the Excel staleness banner reads.

The workbook pulls this like any other query and compares it against TODAY() on the
user's machine, so the banner fires without anyone here noticing anything is wrong.

Columns (one data row):
  generated_utc         when this file was written (i.e. when the refresh last ran)
  coverage_end          last hour of actual data
  last_complete_year    latest fully-complete calendar year in the data
  frozen_history_end    last year in master_fixed.parquet (what CI builds on)
  charts_built_for_year the year the delivered charts' series were generated for
  expected_refresh_days how many days may pass before a refresh is considered overdue
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd

import config as cfg
from completeness import cutoffs

OUT = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")
PUB = os.path.join(cfg.ROOT, "published", "charts")

# How many days may pass before the workbook and the status page cry stale.
#
# 10, chosen 2026-08-03 to flag a SINGLE missed run — Fred's ask was to catch "anytime a
# run that should have gone through didn't". Runs are on the 2nd, 10th, 18th and 26th, so
# the largest ordinary gap is 8 days (18th to 26th, and 2nd to 10th), falling to 7 at the
# month wrap and less in February.
#
# It deliberately is NOT set to the gap itself. The alarm measures time since the last
# SUCCESSFUL run, and GitHub does not start a scheduled job on time — it queues on shared
# runners, and the one scheduled run available to measure sat 2h02m behind its cron. A
# threshold equal to the cadence would therefore trip a few hours before every ordinary
# run and cry wolf every time, which trains the reader to ignore the one alarm that
# matters. Two days of slack over the 8-day maximum keeps it silent when nothing is
# wrong, and still fires about two days after a genuinely missed run — well before the
# following run would mask it.
#
# If you change the cron dates, change this too. History: 45 under the old monthly-only
# schedule, briefly 14 and then 9 during a short-lived weekly cadence, now 10.
EXPECTED_REFRESH_DAYS = 10


def main():
    c = cutoffs()

    fixed = os.path.join(cfg.PROC_DIR, "master_fixed.parquet")
    frozen_end = ""
    if os.path.exists(fixed):
        d = pd.read_parquet(fixed, columns=["ts_utc"])
        frozen_end = int(pd.to_datetime(d.ts_utc, utc=True).dt.year.max())

    row = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "coverage_end": pd.Timestamp(c["coverage_end"]).strftime("%Y-%m-%d %H:%M"),
        "last_complete_year": c["last_complete_year"],
        "frozen_history_end": frozen_end,
        # The delivered charts carry one series per year up to this year. A later
        # completed year needs a generate.py rebuild — see ROLLOVER.md.
        "charts_built_for_year": c["last_complete_year"],
        "expected_refresh_days": EXPECTED_REFRESH_DAYS,
    }

    # Rolling-window labels (w1..wN), read directly by the annual bar charts' series
    # names. These are the ONLY reason the legend can roll on a refresh: a chart series
    # name pointing at a cell renders that cell's text, so when this row is republished
    # with a later window the legend follows, without the workbook being rebuilt.
    # They must stay in step with chart_csv.add_window, which fills the matching
    # {country}_w{i} data columns from the same cfg.window_years() list.
    for i, y in enumerate(cfg.window_years(c["last_complete_year"]), start=1):
        row[f"w{i}"] = y
    df = pd.DataFrame([row])
    for d in (OUT, PUB):
        os.makedirs(d, exist_ok=True)
        df.to_csv(os.path.join(d, "status.csv"), index=False, encoding="utf-8")
    print("  status.csv", row, flush=True)


if __name__ == "__main__":
    main()
