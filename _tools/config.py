"""
config.py — canonical configuration for the ENTSO-E power-price data system.

Countries: Germany (DE-LU), France, Spain, Portugal, Italy.
Range:     2019-01-01 .. present (2026 is YTD).
Timebase:  everything is stored on an HOURLY UTC canonical timeline (DST-safe).

Key design decisions (locked with Fred, 2026-07-16):
  * Italy has no single national day-ahead price -> we build a load-weighted
    PUN *proxy* across the Italian bidding zones. Generation / load / flows /
    capacity for Italy are queried at national "IT" level (verified to work).
  * Intraday "hour-of-day" analytics bucket by UTC hour (Fred's choice).
  * Charts to reproduce: Redburn Figs 1-6 (ENTSO-E), + Fig 7 (intraday gen mix)
    + Fig 9 (annual capacity).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------
# Key resolution (never hardcode — repo may be public):
#   1) ENTSOE_API_KEY env var (GitHub Actions injects this from encrypted Secrets)
#   2) a git-ignored local file  _tools/.entsoe_key  (for runs on Fred's machine)
import os as _os
def _load_api_key():
    # Lazy: return None if absent so build/summary scripts (which don't fetch)
    # can import config without a key. fetch.py raises when it actually needs it.
    k = _os.environ.get("ENTSOE_API_KEY")
    if k:
        return k.strip()
    kf = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), ".entsoe_key")
    if _os.path.exists(kf):
        with open(kf) as f:
            return f.read().strip()
    return None
API_KEY = _load_api_key()

# ---- Year handling (future-proof) -----------------------------------------
# DATA years auto-extend to the current calendar year, so next January the
# pipeline fetches 2027 with no code change. The current year is partial (YTD).
from datetime import date as _date
START_YEAR = 2019
CURRENT_YEAR = _date.today().year
YEARS = list(range(START_YEAR, CURRENT_YEAR + 1))   # years we actually fetch/have data for

# DISPLAY horizon: the published chart CSVs pre-allocate a fixed cell grid out to
# DISPLAY_END_YEAR, so future years land in already-reserved cells without any
# reference shifting. The delivered Redburn charts CAP their plotted range at the
# last year WITH data (so no empty future years show — Fred, 2026-07-17).
#
# MUST stay 2035: the live workbook's chart column references are built for a
# 17-year block per country (DE_2019..DE_2035, then ES_..., then PT_...). Shrinking
# this horizon shifts every country block left, so e.g. the Portugal capture chart
# silently starts plotting French data. Verified 2026-07-21.
DISPLAY_END_YEAR = 2035
DISPLAY_YEARS = list(range(START_YEAR, DISPLAY_END_YEAR + 1))

# ---------------------------------------------------------------------------
# Countries
# ---------------------------------------------------------------------------
# For each country:
#   code        : the ENTSO-E area used for generation / load / flows / capacity
#   price_zones : zone(s) used to derive the representative day-ahead price
#                 - single-element -> used directly
#                 - multi-element  -> load-weighted PUN proxy
#   tz          : local market timezone (documentation only; storage is UTC)
COUNTRIES = {
    "DE": {
        "name": "Germany",
        "code": "DE_LU",
        "price_zones": ["DE_LU"],
        "tz": "Europe/Berlin",
    },
    "FR": {
        "name": "France",
        "code": "FR",
        "price_zones": ["FR"],
        "tz": "Europe/Paris",
    },
    "ES": {
        "name": "Spain",
        "code": "ES",
        "price_zones": ["ES"],
        "tz": "Europe/Madrid",
    },
    "PT": {
        "name": "Portugal",
        "code": "PT",
        "price_zones": ["PT"],
        "tz": "Europe/Lisbon",  # WET/WEST (UTC+0/+1) — the only non-CET market
    },
    # GREAT BRITAIN IS NOT AN ENTSO-E COUNTRY ANY MORE. Its series come from Elexon,
    # the ECB and DUKES via fetch_uk.py, which writes the SAME raw parquet shapes, so
    # everything downstream of the fetch treats GB like any other market. See that
    # file's header for why, and for the Northern Ireland trap.
    #
    # `code` and `price_zones` are still "GB" because cross-border flows DO still come
    # from ENTSO-E (the counterparty TSO publishes each border), and because the stored
    # price file is named price_<zone> like everyone else's.
    "GB": {
        # GREAT BRITAIN, not the United Kingdom. Every GB source here excludes Northern
        # Ireland: DUKES 5.12.A puts NI in its own table 5.12.B, and Elexon's price, load
        # and generation are all GB-only. Labelling it "United Kingdom" would re-import
        # the exact Northern Ireland confusion fetch_uk.py's header warns about, through
        # the caption instead of the domain code. Renamed 2026-08-25 after review.
        "name": "Great Britain",
        "code": "GB",
        "price_zones": ["GB"],
        "tz": "Europe/London",
        "source": "elexon",          # read by fetch.py to skip GB, and by build_status
        # The GB price is NOT a day-ahead auction. Recorded here so anything that
        # displays a UK figure can say so without hunting for the reason.
        "price_basis": "Elexon market index (APX), within-day near gate closure",
    },
    "IT": {
        "name": "Italy",
        "code": "IT",  # national generation/load/flows/capacity work at "IT"
        # PUN proxy: load-weighted across bidding zones. CALA (Calabria) only
        # exists from 2021; zones that return no data for a year are skipped.
        "price_zones": [
            "IT_NORD", "IT_CNOR", "IT_CSUD", "IT_SUD",
            "IT_CALA", "IT_SICI", "IT_SARD",
        ],
        "tz": "Europe/Rome",
    },
}

# DISPLAY ORDER, AND A HARD APPEND-ONLY RULE. Every wide chart CSV lays out one block
# of columns per country in THIS order, and the workbook's chart references are absolute
# column letters into those blocks. Inserting a country anywhere but the end shifts every
# block to its right, so e.g. the Italian capture chart would silently start plotting
# British data — the same class of fault that un-curated chart12 on 2026-07-22.
# ADD NEW COUNTRIES AT THE END. GB was appended 2026-08-25 for exactly this reason,
# even though grouping it beside France would read better.
COUNTRY_ORDER = ["DE", "ES", "PT", "FR", "IT", "GB"]  # display order (Iberia grouped)

# Countries whose raw series come from somewhere other than ENTSO-E. fetch.py skips
# these; fetch_uk.py fills them. Kept as a set so the test is a lookup, not a country
# name spelled out in five places.
NON_ENTSOE = {c for c, m in COUNTRIES.items() if m.get("source")}

# THE TWELVE LEGACY FIGURE TABS ARE FROZEN AT FIVE COUNTRIES, AND THIS IS WHY.
#
# Fig1..Fig9, Fig2_Intraday_avg, Fig5_Capture_abs and CaptureMonthly come from the
# query-wired base workbook, and their Excel tables are fixed at 86 columns (A1:CH) —
# exactly 1 + 5 x 17. Unlike the Phase-4 tabs, add_power_queries.py does NOT rebuild
# them, so their width does not follow their CSV. Publishing a 103-column CSV into an
# 86-column table puts every GB column OUTSIDE the table, where a chart cannot see it
# and a refresh does not reach it. Widening them means rewriting table, queryTable and
# column definitions on inherited parts, which is the exact surgery that silently
# un-curated chart12 on 2026-07-22.
#
# It costs nothing, because the CHARTS DO NOT READ THESE TABS. Every annual bar chart
# reads Fig5_Window or Fig9_Window and every line chart reads Line_Window, all three of
# which add_power_queries rebuilds from their CSV each run, so their width tracks the
# country list on its own and GB arrives there with no surgery at all.
#
# The one series that genuinely needed the legacy path is monthly capture, because the
# CaptureVsBase formulas read CaptureMonthly directly. GB's goes to its own tab from its
# own CSV, which is the same pattern the rolling-window tables already use.
LEGACY_CSV_COUNTRIES = ["DE", "ES", "PT", "FR", "IT"]

# ---------------------------------------------------------------------------
# Technology taxonomy
# ---------------------------------------------------------------------------
# Maps raw ENTSO-E production types -> canonical categories used in every
# output (capture prices, generation mix, capacity). Pumped-storage consumption
# is tracked as its OWN category (stored positive here; rendered negative in the
# intraday-mix chart, per Redburn Fig 7).
#
# ENTSO-E returns generation columns as a MultiIndex (psr_type, business_type)
# where business_type is "Actual Aggregated" (production) or
# "Actual Consumption" (load of the unit, used for pumped storage).
TECH_MAP = {
    "Solar":                              "Solar",
    "Wind Onshore":                       "Onshore wind",
    "Wind Offshore":                      "Offshore wind",
    "Hydro Run-of-river and poundage":    "Hydro run-of-river",
    "Hydro Water Reservoir":              "Hydro reservoir",
    "Hydro Pumped Storage":               "Hydro pumped (production)",  # Actual Aggregated
    "Nuclear":                            "Nuclear",
    "Biomass":                            "Biomass",
    "Fossil Gas":                         "Gas",
    "Fossil Coal-derived gas":            "Gas",
    "Fossil Brown coal/Lignite":          "Lignite",
    "Fossil Hard coal":                   "Hard coal",
    "Fossil Oil":                         "Oil & other fossil",
    "Fossil Oil shale":                   "Oil & other fossil",
    "Fossil Peat":                        "Oil & other fossil",
    "Geothermal":                         "Geothermal",
    "Marine":                             "Marine",
    "Waste":                              "Waste",
    "Other":                              "Other",
    "Other renewable":                    "Other renewable",
}

# Special category for pumped-storage CONSUMPTION (from the "Actual Consumption"
# business type on Hydro Pumped Storage). Stored as a positive MW figure.
PUMPED_CONSUMPTION = "Hydro pumped (consumption)"

# Canonical ordered category list (production categories, stacking order for
# Fig 7 roughly bottom->top; consumption handled separately).
TECH_ORDER = [
    "Nuclear",
    "Lignite",
    "Hard coal",
    "Gas",
    "Oil & other fossil",
    "Biomass",
    "Waste",
    "Geothermal",
    "Hydro run-of-river",
    "Hydro reservoir",
    "Hydro pumped (production)",
    "Onshore wind",
    "Offshore wind",
    "Solar",
    "Marine",
    "Other renewable",
    "Other",
]

# ---------------------------------------------------------------------------
# Display curation — technology charts
# ---------------------------------------------------------------------------
# ENTSO-E reports 17 production types, but plotting all 17 as bar categories (or
# as stack/legend entries) makes the exhibit unreadable. Skye's volatility-capture
# note shows a CURATED set instead: Fig 5/47 (German capture vs base) uses 10
# technologies, Fig 50 (Portugal) 7, Fig 7 (Portugal intraday mix) 8 + storage
# consumption, net imports and price. We mirror that.
#
# An Excel chart series reads ONE contiguous range, so each country's set gets its
# own STACKED BLOCK of rows in the capture/capacity CSVs. That lets every chart keep
# the note's exact ordering rather than sharing one compromise order (the blocks
# repeat some technologies — deliberate; these are chart-feed tables, one per chart).
#
#   rows  2-12  Germany  — note Fig 5/47 order
#   rows 13-19  Portugal — note Fig 50 order
#   rows 20-25  technologies in neither chart, kept for reference
TECH_BLOCKS = {
    # Fig 5/47: Solar, Onshore wind, Offshore wind, Hydro pumped, Hydro,
    #           Nuclear, Biomass, Gas, Lignite, Hard coal
    #
    # NUCLEAR IS DELIBERATELY LAST (moved 2026-07-30), not in the note's position.
    # Germany's last three reactors closed 15 April 2023, so the German nuclear
    # capture series is 2019-22 plus a PART-YEAR 2023 figure of +19.3% — an artefact
    # of the fleet running only through the high-price winter months before shutting,
    # not a real premium — and then blank 2024/25 slots. On the capture chart that is
    # both misleading and the source of the empty-bar gaps, so Fig 5 stops before it.
    # Fig 9 (installed capacity) KEEPS Nuclear: there the run-down to zero IS the story.
    #
    # An Excel series reads one CONTIGUOUS range, so putting Nuclear at the tail lets
    # each chart take a prefix of the same block — capture 10 rows, capacity 11 — with
    # no row added or removed. That matters: the Portugal block still starts at row 13
    # and nothing changes shape on refresh, which is the invariant check_consistency
    # asserts and the exact fault that silently un-curated chart12 on 2026-07-22.
    "DE": [
        "Solar",
        "Onshore wind",
        "Offshore wind",
        "Hydro pumped (production)",
        "Hydro reservoir",
        "Hydro run-of-river",
        "Biomass",
        "Gas",
        "Lignite",
        "Hard coal",
        "Nuclear",
    ],
    # Fig 50: Solar, Wind, Hydro run-of-river, Hydro reservoir, Hydro pumped,
    #         Biomass, Gas
    "PT": [
        "Solar",
        "Onshore wind",
        "Hydro run-of-river",
        "Hydro reservoir",
        "Hydro pumped (production)",
        "Biomass",
        "Gas",
    ],
}

_BLOCK_SEQ = ["DE", "PT"]          # stacking order == row order in the CSVs


# ---------------------------------------------------------------------------
# Rolling year window — how the annual bar charts survive the year turn
# ---------------------------------------------------------------------------
# A year is a chart SERIES, and Excel fixes the series count when the file is built,
# so a refresh can never add one: a workbook built in 2026 keeps showing 2019-2025 for
# ever. Reserving empty series in advance does not work on a BAR chart — measured
# 2026-07-30, an empty series still claims its slot, so seven bars became twelve slots
# and the visible bars lost ~40% of their width with blank gaps in every cluster.
#
# So the window rolls instead of growing. The chart always reads the same WINDOW_YEARS
# columns, and the build decides which years those are; the series NAMES point at label
# cells that roll with them (verified: a name read from a cell renders that cell's text —
# a probe showed 2013-2019 in the legend from cells alone, with bar width unchanged).
# Nothing about the chart's shape changes, so nothing compresses, and the new year
# appears on an ordinary Power Query refresh.
#
# The trade: the exhibit becomes "the last seven complete years" rather than "everything
# since 2019", so 2019 drops off in 2027. Fred chose that over the alternatives.
WINDOW_YEARS = 7


def window_years(last_complete_year):
    """The WINDOW_YEARS complete years ending at last_complete_year, oldest first."""
    return list(range(last_complete_year - WINDOW_YEARS + 1, last_complete_year + 1))


def wcol(country, i):
    """Window column name: i is 1-based, 1 = oldest year in the window."""
    return f"{country}_w{i}"


def tech_keep(country):
    """Curated technology list for a country's capture / capacity charts."""
    return TECH_BLOCKS.get(country, TECH_BLOCKS["DE"])


# Technologies dropped from the CAPTURE chart only, as a count of rows trimmed off
# the END of the block (they must be contiguous — one Excel series, one range).
# See the TECH_BLOCKS note: German nuclear is a closed fleet whose only post-2022
# datapoint is a part-year artefact, so Fig 5 excludes it while Fig 9 keeps it.
CAPTURE_TAIL_DROP = {"DE": 1}


def tech_keep_capture(country):
    """Technology list for the capture chart (Fig 5) — a prefix of tech_keep()."""
    keep = tech_keep(country)
    drop = CAPTURE_TAIL_DROP.get(country, 0)
    return keep[: len(keep) - drop] if drop else keep


def tech_block_start(country):
    """1-based data-row offset of this country's block (row 1 = CSV header)."""
    row = 2
    for c in _BLOCK_SEQ:
        if c == country:
            return row
        row += len(TECH_BLOCKS[c])
    return row


def tech_row_order():
    """Full row order of the capture/capacity CSVs: the blocks, then the leftovers."""
    rows = []
    for c in _BLOCK_SEQ:
        rows += TECH_BLOCKS[c]
    seen = set(rows)
    rows += [t for t in TECH_ORDER if t not in seen]
    return rows


TECH_DISPLAY_ORDER = None   # superseded by TECH_BLOCKS / tech_row_order()


# Intraday generation mix (note Fig 7): the same curated set plus the "Other"
# bucket. For Portugal the 9 omitted types are 0.13% of volume (no nuclear,
# lignite, coal, oil, waste, geothermal or marine at all).
GENMIX_KEEP = TECH_BLOCKS["PT"] + ["Other"]

# ---------------------------------------------------------------------------
# Hydro reservoir tracker
# ---------------------------------------------------------------------------
# ENTSO-E's "Water Reservoirs and Hydro Storage Plants" (A72) is a WEEKLY stored-energy
# figure in MWh, published per bidding zone. It is a different endpoint from anything
# the price pipeline touched before 2026-08-25, and it is the series behind the
# reservoir-fill-vs-historic-range charts.
#
# WHO HAS IT, probed 2026-08-25 (single-year call per zone, 2025):
#   yes  FR ES PT IT, NO + NO_1..NO_5, SE, FI, AT, CH   (53 weekly points each)
#   no   Germany, under DE_LU, DE and DE_AT_LU alike
#   no   Great Britain, under any domain code
# So "every country we have data for" genuinely excludes Germany and the UK. Both get a
# pumped-storage chart instead (see PUMPED_ONLY below) rather than a blank panel.
#
# Zone choice: the national zone where one exists, plus Norway's five price zones,
# because Norwegian hydro is the market where the zonal split is the story. Sweden is
# taken nationally: SE_1..SE_4 exist but the reservoir series is reported for SE.
HYDRO_RESERVOIR_ZONES = [
    ("FR", "FR", "France"),
    ("ES", "ES", "Spain"),
    ("PT", "PT", "Portugal"),
    ("IT", "IT", "Italy"),
    ("NO", "NO", "Norway"),
    # Norway's five price zones (NO_1..NO_5) all return clean weekly data and were built
    # on 2026-08-25, then dropped the same day on Fred's call: five zonal charts beside
    # the national one crowded the tab for a split nothing else in the workbook makes.
    # The raw pulls are still on disk, so restoring them is a matter of adding the rows
    # back here and re-running summarise_hydro.
    ("SE", "SE", "Sweden"),
    ("FI", "FI", "Finland"),
    ("AT", "AT", "Austria"),
    ("CH", "CH", "Switzerland"),
]

# Markets with no reservoir series at all. They get a weekly PUMPED-STORAGE chart built
# from the hourly master instead (Fred's call, 2026-08-25: "add pumped storage where
# possible for data that exists"). It is deliberately captioned as pumped storage, never
# as reservoir: a pumped fleet's weekly output says nothing about stored inflow, and the
# two would be read as the same exhibit if the captions let them.
PUMPED_ONLY = ["DE", "GB"]

# The tracker's historic band. The Hydro Tracker workbook this was modelled on uses a
# 2015-2025 min/max range, which predates the price pipeline's 2019 start; reservoir data
# is fetched from here regardless of START_YEAR so the band has its full depth.
HYDRO_START_YEAR = 2015

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
import os
_TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_TOOLS)
RAW_DIR = os.path.join(ROOT, "data", "raw")            # per (country, series, year) parquet
PROC_DIR = os.path.join(ROOT, "data", "processed")     # master hourly parquet + duckdb
OUTPUT_DIR = os.path.join(ROOT, "outputs")             # Excel + charts (house-style dir)
META_DIR = os.path.join(ROOT, "_meta")

for _d in (RAW_DIR, PROC_DIR, OUTPUT_DIR, META_DIR):
    os.makedirs(_d, exist_ok=True)

# ---------------------------------------------------------------------------
# Thresholds / analytics params
# ---------------------------------------------------------------------------
NEG_PRICE_THRESHOLD = 0.0          # "negative hours" : price < 0
NEAR_NEG_THRESHOLD = 1.0           # Redburn Fig 3 : price < 1 EUR/MWh (near-negative)
DURATION_CURVE_STEPS = 101         # 0..100% in 1% steps for price-duration curves
