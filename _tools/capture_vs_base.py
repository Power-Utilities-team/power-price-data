"""
capture_vs_base.py — the CaptureVsBase sheet layout, as data rather than as a workbook.

WHAT THE SHEET IS. Two derived figures per country and technology, monthly: capture
price MINUS baseload (a EUR/MWh spread) and capture price AS A PERCENTAGE of baseload.
Both are computed in Excel from CaptureMonthly and A_MonthPrice, which the pipeline
already publishes, so the sheet needs no query of its own and stays correct on every
refresh. After those come the rolling w1..w8 window blocks the monthly line charts read.

WHY IT IS GENERATED RATHER THAN COPIED. The sheet arrived as a hand-built tab in the
workbook Fred circulated, and it was never in this repo, so a fresh generate.py run
produced a workbook missing it and the 43 charts that read it. Rebuilding it here is
what makes the file reproducible.

AND WHY THE LAYOUT CHANGED IN THE REBUILD. The hand-built version held a column pair
only for technologies that HAD data: 67 pairs, not the 6 x 17 the taxonomy allows. That
looks tidy and is a trap. Every chart reference into this sheet is an absolute column
letter, so the first month a country reports a technology it had never reported before,
a pair is inserted, every column to its right shifts one place, and each of the thirty
monthly charts silently starts plotting its neighbour. Nothing would fail; the numbers
would simply be wrong, under the right title. It is the same class of fault that
un-curated chart12 in July 2026, found only because someone looked.

So the generated layout is FULL and FIXED: every country in COUNTRY_ORDER, every
technology in TECH_ORDER, present or not. A technology with no data yields a column of
NA() and the chart draws nothing, which is the correct rendering of "no data" and costs
only width. Positions can then never move for a data reason.

Used by add_extra_charts.py, which turns this into worksheet XML and points the charts
at the columns this module names.
"""
from __future__ import annotations

import config as cfg

# Rows: one per month across the display horizon, mirroring CaptureMonthly exactly, so
# row N here and row N there are the same month and the formulas need no offset.
MONTHS = [f"{y}-{m:02d}" for y in cfg.DISPLAY_YEARS for m in range(1, 13)]

# The technologies that get a monthly capture CHART, per country. Six each, matching the
# workbook Fred circulated, with three deliberate changes he asked for on 2026-08-25:
#
#   Italy   Hydro run-of-river -> Hydro reservoir. Italy showed hydro as a SINGLE series
#           and his rule was that a single hydro series becomes reservoir. Portugal and
#           France already show both, so they are untouched.
#   Germany GAINS Hydro reservoir as a SEVENTH chart. It had no hydro chart at all, and
#           his ask was that the reservoir series exist for every country with data.
#           Nothing is dropped to make room: he asked for an addition, and quietly
#           retiring one of his six to keep the count even would be a change he never
#           agreed to. The grid takes an odd chart without trouble.
#   GB      is new, and keeps Hydro run-of-river BECAUSE IT MUST: Elexon reports
#           run-of-river and pumped storage for Great Britain and no water-reservoir
#           category at all, so there is nothing to swap to. This is the one country
#           where the single-series rule cannot apply, and saying so here is cheaper
#           than someone rediscovering it from an empty chart.
CHARTED = {
    "DE": ["Onshore wind", "Solar", "Lignite", "Gas", "Biomass", "Hard coal",
           "Hydro reservoir"],
    "ES": ["Onshore wind", "Solar", "Nuclear", "Gas", "Hydro reservoir",
           "Hydro pumped (production)"],
    "PT": ["Onshore wind", "Hydro run-of-river", "Gas", "Hydro pumped (production)",
           "Solar", "Hydro reservoir"],
    "FR": ["Nuclear", "Onshore wind", "Hydro run-of-river", "Solar", "Gas",
           "Hydro reservoir"],
    "IT": ["Gas", "Solar", "Hydro reservoir", "Onshore wind", "Other", "Biomass"],
    "GB": ["Onshore wind", "Offshore wind", "Solar", "Gas", "Nuclear",
           "Hydro run-of-river"],
}

DIFF = "diff"
PCT = "% of base"


def pair_columns():
    """[(country, tech, diff_header, pct_header)] in sheet order, full and fixed."""
    out = []
    for c in cfg.COUNTRY_ORDER:
        for t in cfg.TECH_ORDER:
            out.append((c, t, f"{c}_{t} {DIFF}", f"{c}_{t} {PCT}"))
    return out


def window_columns():
    """[(country, tech, [w1..w8 headers])] in sheet order, after every pair column."""
    out = []
    for c in cfg.COUNTRY_ORDER:
        for t in CHARTED.get(c, []):
            out.append((c, t, [f"{c}_{t} w{i}" for i in range(1, 9)]))
    return out


# The category axis of every monthly chart. A literal column of month names rather than
# a formula, because it is the same twelve labels for ever and a chart's category
# reference must resolve whether or not the workbook has been refreshed yet.
MONTH_LABELS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
MONTH_LABEL_HEADER = "month"


def headers():
    """The full header row, column A first."""
    hdr = ["date"]
    for _c, _t, d, p in pair_columns():
        hdr += [d, p]
    hdr.append(MONTH_LABEL_HEADER)
    for _c, _t, ws in window_columns():
        hdr += ws
    return hdr


CAPTURE_SHEET = "CaptureMonthly"
CAPTURE_SHEET_EXTRA = "CaptureMonthlyExtra"
PRICE_SHEET = "A_MonthPrice"


def source_sheet(country):
    """Which tab holds this country's monthly capture prices.

    The original five sit on CaptureMonthly, whose Excel table is one of the inherited
    86-column ones and cannot take a sixth country. Anything beyond them is published to
    its own CSV and its own tab. See config.LEGACY_CSV_COUNTRIES.
    """
    return CAPTURE_SHEET if country in cfg.LEGACY_CSV_COUNTRIES else CAPTURE_SHEET_EXTRA


def source_col_index(country, tech):
    """1-based column of (country, tech) on whichever capture tab holds it.

    Both tabs are written by chart_csv.capture_monthly as month, then each country it
    covers crossed with every technology in TECH_ORDER. Deriving the index from the same
    lists is what stops the sheets drifting apart: add a country or reorder a technology
    and every consumer moves with it.
    """
    peers = (cfg.LEGACY_CSV_COUNTRIES if country in cfg.LEGACY_CSV_COUNTRIES
             else [c for c in cfg.COUNTRY_ORDER if c not in cfg.LEGACY_CSV_COUNTRIES])
    ci = peers.index(country)
    ti = cfg.TECH_ORDER.index(tech)
    return 2 + ci * len(cfg.TECH_ORDER) + ti


def price_col_index(country):
    """1-based column of this country's baseload price on A_MonthPrice.

    That tab IS rebuilt from its CSV by add_power_queries, so it simply widens as
    countries are added and every market lives on the one sheet.
    """
    return 2 + cfg.COUNTRY_ORDER.index(country)


def layout():
    """Everything add_extra_charts needs: headers, and where each chart series lives."""
    hdr = headers()
    index = {h: i + 1 for i, h in enumerate(hdr)}   # 1-based column numbers
    return hdr, index
