"""
extra_summaries.py — build the three NEW chart-ready tables that the deck needs
but the existing summary tabs can't produce (they need raw hourly granularity):

  G1  g1_solar_peakhour.csv       — daily solar share of total generation in each
                                     day's PEAK SOLAR hour, per country, + a
                                     quarterly-average step column per country.
  G2a g2_price_by_quarter.csv     — intraday price profile (abs €/MWh) by hour,
                                     split by country × year × QUARTER.
  G2b g2_price_by_month.csv       — same, split by country × year × MONTH.
  G3  g3_price_july_daily.csv     — every day's hourly price profile in JULY,
                                     per country × year × day (the "daily duck
                                     curve spaghetti").

Reads the assembled master (data/processed/hourly_master.parquet); writes CSVs to
outputs/csv/charts/ AND published/charts/. Year columns pre-allocated to
DISPLAY_END_YEAR so future years fill blank columns without shifting cells.
"""
from __future__ import annotations
import os
import pandas as pd
import config as cfg

MASTER = os.path.join(cfg.PROC_DIR, "hourly_master.parquet")
OUT = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")
PUB = os.path.join(cfg.ROOT, "published", "charts")
YRS = list(range(cfg.START_YEAR, cfg.DISPLAY_END_YEAR + 1))   # 2019..2030
CO = cfg.COUNTRY_ORDER                                        # DE, ES, PT, FR, IT
JULY = 7

# --- charts 16-19 (monthly "market-state" tables) helpers ---
from completeness import cutoffs as _cutoffs
_C = _cutoffs()
_LCM = _C["last_complete_month"]                              # (year, month) — gate partial months
_QEND = _C["last_complete_quarter_end"]                       # gate G1's quarterly average
WIND_SOLAR = ["gen_Solar", "gen_Onshore wind", "gen_Offshore wind"]
# pre-allocated monthly x-axis, first-of-month, 2019-01 .. DISPLAY_END_YEAR-12
MONTH_STR = pd.date_range("2019-01-01", f"{cfg.DISPLAY_END_YEAR}-12-01",
                          freq="MS").strftime("%Y-%m-%d").tolist()

def _load():
    df = pd.read_parquet(MASTER)
    t = pd.to_datetime(df["ts_utc"], utc=True)
    df["year"] = t.dt.year; df["quarter"] = t.dt.quarter
    df["month"] = t.dt.month; df["day"] = t.dt.day
    df["hour"] = t.dt.hour; df["date"] = t.dt.normalize()
    return df

def _save(df, name):
    for d in (OUT, PUB):
        os.makedirs(d, exist_ok=True)
        df.to_csv(os.path.join(d, name + ".csv"), index=False, encoding="utf-8")
    print(f"  wrote {name}: {df.shape[0]} rows x {df.shape[1]} cols", flush=True)

# ---------------------------------------------------------------- G1
def g1(df):
    # peak solar hour per (country, date): row where gen_Solar is maximal.
    # Drop rows with no solar reading FIRST: a country-day that is entirely NA
    # (an ENTSO-E publication gap, or the partial current day) makes idxmax raise
    # "encountered all NA values in a group" and takes the whole refresh down.
    # Such a day simply has no peak-solar hour, so it should be absent, not fatal.
    solar = df.dropna(subset=["gen_Solar"])
    idx = solar.groupby(["country", "date"])["gen_Solar"].idxmax()
    pk = solar.loc[idx, ["country", "date", "gen_Solar", "gen_total"]].copy()
    pk["share"] = (pk["gen_Solar"] / pk["gen_total"] * 100).clip(lower=0)
    wide = pk.pivot(index="date", columns="country", values="share")
    full = pd.date_range("2019-01-01", f"{cfg.DISPLAY_END_YEAR}-12-31", freq="D", tz="UTC")
    wide = wide.reindex(full)
    out = pd.DataFrame({"date": wide.index.strftime("%Y-%m-%d")})
    qkey = [wide.index.year, wide.index.quarter]
    for c in CO:
        if c not in wide.columns:
            continue
        out[c] = wide[c].round(1).values
        out[c + "_qavg"] = wide[c].groupby(qkey).transform("mean").round(1).values

    # Clip the quarterly average to the last COMPLETE quarter.
    #
    # transform("mean") broadcasts a quarter's mean back onto every day of that
    # quarter — including days that have not happened yet. With coverage ending
    # mid-quarter that writes a mean computed from a handful of days across all ~92,
    # so the published series ran up to 2.5 months into the future as a flat line.
    # The PNG path already clipped this (render_all.g1_solarpeak filters to QEND),
    # but the CSV Excel loads did not, so the live workbook and the deck drew the
    # same exhibit differently — the divergence this project exists to prevent.
    #
    # The partial quarter is dropped rather than shown, matching the project rule
    # that a period-based chart never displays an incomplete period.
    qend = pd.Timestamp(_QEND).tz_localize(None)
    stamps = pd.to_datetime(out["date"])
    future = stamps > qend
    out.loc[future, [c + "_qavg" for c in CO if c + "_qavg" in out.columns]] = pd.NA
    if future.any():
        print(f"  G1: cleared {int(future.sum())} qavg day(s) after "
              f"{qend.date()} (incomplete quarter)", flush=True)
    _save(out, "g1_solar_peakhour")

# ---------------------------------------------------------------- G2 / G3 helper
def _intraday_pivot(df, extra_key, key_vals, label, name):
    """avg price by hour, split by country × year × <extra_key>."""
    pt = df.pivot_table(index="hour", columns=["country", "year", extra_key],
                        values="price", aggfunc="mean")
    cols = [(c, y, k) for c in CO for y in YRS for k in key_vals]
    pt = pt.reindex(index=range(24), columns=cols)
    pt.columns = [f"{c}_{y}_{label(k)}" for (c, y, k) in cols]
    out = pt.round(2).reset_index().rename(columns={"hour": "hour_utc"})
    _save(out, name)

def g2_quarter(df):
    _intraday_pivot(df, "quarter", [1, 2, 3, 4], lambda q: f"Q{q}", "g2_price_by_quarter")

def g2_month(df):
    _intraday_pivot(df, "month", list(range(1, 13)), lambda m: f"M{m:02d}", "g2_price_by_month")

def g3_july(df):
    jul = df[df["month"] == JULY]
    _intraday_pivot(jul, "day", list(range(1, 32)), lambda d: f"D{d:02d}", "g3_price_july_daily")

# ---------------------------------------------------------------- charts 16-19: monthly market-state tables
def _write_monthly_country(g, name, roll=None):
    """g has columns [country, year, month, v]; write date x country wide CSV,
    pre-allocated to DISPLAY_END_YEAR, partial months gated, optional 12-mo rolling."""
    g = g[[(y, m) <= _LCM for y, m in zip(g["year"], g["month"])]].copy()   # gate partial months
    g["date"] = pd.to_datetime(dict(year=g["year"], month=g["month"], day=1)).dt.strftime("%Y-%m-%d")
    wide = g.pivot(index="date", columns="country", values="v").reindex(MONTH_STR)
    if roll:
        wide = wide.rolling(roll, min_periods=roll).mean()                  # trailing 12-mo, both paths see it
    out = pd.DataFrame({"date": MONTH_STR})
    for c_ in CO:
        out[c_] = wide[c_].round(2).values if c_ in wide.columns else pd.NA
    _save(out, name)

def figA_monthly_price(df):
    g = df.groupby(["country", "year", "month"])["price"].mean().reset_index(name="v")
    _write_monthly_country(g, "figA_monthly_price")                          # raw monthly (crisis spike is the story)

def figB_penetration(df):
    d = df.copy()
    d["_ws"] = d[WIND_SOLAR].to_numpy().sum(axis=1)
    g = (d.groupby(["country", "year", "month"])
           .apply(lambda s: 100 * s["_ws"].sum() / s["gen_total"].sum())
           .reset_index(name="v"))
    _write_monthly_country(g, "figB_penetration", roll=12)                   # 12-mo rolling (cut seasonal saw-tooth)

def figC_capture_erosion():
    cm = pd.read_parquet(os.path.join(cfg.PROC_DIR, "summaries", "capture_monthly.parquet"))
    cm = cm[(cm["country"] == "DE") & cm["tech"].isin(["Solar", "Onshore wind"])].copy()
    cm = cm[[(y, m) <= _LCM for y, m in zip(cm["year"], cm["month"])]]
    cm["date"] = pd.to_datetime(dict(year=cm["year"], month=cm["month"], day=1)).dt.strftime("%Y-%m-%d")
    wide = cm.pivot(index="date", columns="tech", values="capture_vs_base_pct").reindex(MONTH_STR)
    out = pd.DataFrame({"date": MONTH_STR})
    out["DE_Solar"] = wide["Solar"].round(2).values if "Solar" in wide.columns else pd.NA
    out["DE_Wind"] = wide["Onshore wind"].round(2).values if "Onshore wind" in wide.columns else pd.NA
    _save(out, "figC_capture_erosion")                                       # raw monthly (deepening summer troughs = story)

def figD_netload_duck(df):
    d = df[df["country"] == "DE"].copy()
    d["_res"] = (d["load"] - d[WIND_SOLAR].to_numpy().sum(axis=1)) / 1000.0   # GW; net load = demand - wind - solar
    prof = d.groupby(["year", "hour"])["_res"].mean().reset_index()
    wide = prof.pivot(index="hour", columns="year", values="_res").reindex(range(24))
    out = pd.DataFrame({"hour_utc": list(range(24))})
    for y in YRS:                                                            # pre-allocated year columns
        out[f"DE_{y}"] = wide[y].round(2).values if y in wide.columns else pd.NA
    _save(out, "figD_netload_duck")                                          # keeps current partial year (YTD profile)

# The LINE charts each read 8 consecutive year-columns (7 complete + the current YTD)
# from one of five different sheets. Rather than five more window tabs — the pattern that
# produced three separate package faults on 2026-07-31 — they share ONE table. Row counts
# differ (24 hours, 101 percentiles, 366 days); short ones leave blanks, which a line
# chart simply does not draw.
#
# Slot 1..7 are the last seven COMPLETE years, slot 8 the current year-to-date, matching
# what those charts show today. Their POSITION never moves, so the chart references stay
# valid for ever, while their MEANING advances every January — the same mechanism already
# proven on the annual bar charts, and it adds no series, so it cannot introduce the dead
# legend entry that reserving spare series would.
LINE_WINDOWS = [
    ("fig2_intraday_indexed", ["DE", "ES"], "i"),
    ("fig2_intraday_avg",     ["DE"],       "a"),
    ("fig3_cum_near_neg",     ["DE", "ES"], "c"),
    ("fig4_duration_curve",   ["PT"],       "d"),
    ("figD_netload_duck",     ["DE"],       "n"),
]

# Blocks appended AFTER everything else (see the append-only note in line_windows()):
# the intraday index for the remaining three countries, added 2026-08-06 so the
# Portugal / France / Italy Fig-2 charts can roll like Germany's and Spain's.
LINE_WINDOWS_APPEND = [
    ("fig2_intraday_indexed", ["PT", "FR", "IT"], "i"),
    # cumulative near-negative hours for the remaining three countries, added
    # 2026-08-06 (evening) for the per-country Fig 3 charts
    ("fig3_cum_near_neg",     ["PT", "FR", "IT"], "c"),
    # Great Britain, appended 2026-08-25 so the UK gets the same intraday-shape and
    # cumulative-negative-hours charts every other market has. APPENDED, not slotted in
    # beside its neighbours: every chart reads an absolute column into this table, so a
    # block inserted anywhere but the end repoints all of them one place to the right.
    ("fig2_intraday_indexed", ["GB"], "i"),
    ("fig3_cum_near_neg",     ["GB"], "c"),
]

# Fig 1 and Fig 3 are the other shape: YEARS are the x-axis CATEGORIES and the series are
# countries. They look like they should grow by themselves — a new year is just another
# category — but the range is fixed at rows 2..8, so the 2026 row already holds data the
# chart cannot see. This is exactly what Fred reported: typing into the 2027 row changes
# nothing. Same window treatment, transposed: seven ROWS whose meaning rolls, plus a
# column of year labels for the category axis.
CATEGORY_WINDOWS = [
    ("fig1_price_sd",         "f1"),
    ("fig3_neg_hours_annual", "f3"),
]
CATEGORY_COUNTRIES = ["Germany", "Spain", "Portugal", "France", "Italy"]

# The three charts that plot a SINGLE year (the latest complete one) rather than a span
# of years, so they need one rolling column each rather than a w1..w7 window.
# (source csv stem, column prefix on line_windows, [(suffix, source column template)]).
# {y} is filled with the latest complete year at build time.
SINGLE_YEAR_BLOCKS = [
    # chart 7 — daily min/max scatter, Germany. x = max, y = min.
    ("fig6_daily_minmax", "mm", [("DE_min", "DE_{y}_min"), ("DE_max", "DE_{y}_max")]),
    # chart 8 — intraday generation mix, PORTUGAL (not Germany; easy to assume wrong).
    ("fig7_gen_mix", "gm", [
        ("Gas", "PT_{y}_Gas"), ("Biomass", "PT_{y}_Biomass"),
        ("HydroROR", "PT_{y}_Hydro run-of-river"),
        ("HydroRes", "PT_{y}_Hydro reservoir"),
        ("HydroPump", "PT_{y}_Hydro pumped (production)"),
        ("Onshore", "PT_{y}_Onshore wind"), ("Solar", "PT_{y}_Solar"),
        ("Other", "PT_{y}_Other"), ("Price", "PT_{y}_price")]),
    # chart 15 — price by month duck curve, Germany, one series per calendar month.
    ("g2_price_by_month", "md",
     [(f"M{m:02d}", f"DE_{{y}}_M{m:02d}") for m in range(1, 13)]),
]


def line_windows():
    import config as _c
    from completeness import cutoffs as _cut
    lcy = _cut()["last_complete_year"]
    years = _c.window_years(lcy) + [lcy + 1]        # 7 complete + current YTD

    frames, nrows = {}, 0
    for stem, _co, _tag in LINE_WINDOWS:
        f = os.path.join(OUT, f"{stem}.csv")
        if not os.path.exists(f):
            raise SystemExit(f"line_windows: {stem}.csv missing — build order changed?")
        frames[stem] = pd.read_csv(f)
        nrows = max(nrows, len(frames[stem]))

    out = pd.DataFrame({"row": range(1, nrows + 1)})

    # the category-axis charts: 7 rows, the window years, in fixed positions
    ylab = [""] * nrows
    for i, y in enumerate(cfg_window := _c.window_years(lcy)):
        ylab[i] = str(y)
    out["win_year"] = ylab
    for stem, tag in CATEGORY_WINDOWS:
        f = os.path.join(OUT, f"{stem}.csv")
        if not os.path.exists(f):
            raise SystemExit(f"line_windows: {stem}.csv missing — build order changed?")
        src = pd.read_csv(f)
        ycol = src.columns[0]
        for country in CATEGORY_COUNTRIES:
            col = country if country in src.columns else f"{country}_neg"
            vals = [float("nan")] * nrows
            if col in src.columns:
                lut = dict(zip(src[ycol].astype(str), src[col]))
                for i, y in enumerate(cfg_window):
                    vals[i] = lut.get(str(y), float("nan"))
            out[f"{tag}_{country[:2]}_w"] = vals

    for stem, countries, tag in LINE_WINDOWS:
        src = frames[stem]
        # A country outside the original five is not in the legacy CSV at all — that
        # file's Excel table is fixed at 86 columns and cannot hold a sixth market, so
        # chart_csv publishes those columns to a companion "_extra" file instead. Look
        # there when the main frame does not have the country. Without this the window
        # columns are built, published and loaded exactly as normal, and are silently
        # empty from end to end: the UK's intraday and cumulative-negative charts came
        # out blank with nothing anywhere reporting a fault.
        extra = None
        for c in countries:
            for i, y in enumerate(years, start=1):
                col = f"{c}_{y}"
                frame = src
                if col not in src.columns:
                    if extra is None:
                        ef = os.path.join(OUT, f"{stem}_extra.csv")
                        extra = pd.read_csv(ef) if os.path.exists(ef) else pd.DataFrame()
                    frame = extra
                vals = frame[col].tolist() if col in frame.columns else []
                vals = vals + [float("nan")] * (nrows - len(vals))
                out[f"{tag}_{c}_w{i}"] = vals[:nrows]

    # --- the three SINGLE-YEAR charts (added 2026-08-03) ----------------------
    # Charts 7, 8 and 15 each show ONE year — the latest complete one — and each was
    # pinned to whichever year it was built in, so from January 2027 they would have gone
    # on showing 2025 while every chart around them advanced. They were the last three of
    # the nineteen that a refresh could not carry forward, and the reason the workbook
    # still told the reader to download a replacement every January.
    #
    # The fix is the one already proven for the twelve rolling charts: the column
    # POSITION never changes, so the chart reference stays valid for ever, while its
    # MEANING advances one year each January because `lcy` does. Nothing is pinned.
    #
    # These live on the existing line_windows table rather than a tab of their own.
    # Its 366 rows already cover the longest of them (day-of-year), and a new tab would
    # mean a new query and a new set of content-type and relationship joins to get right
    # — the exact surgery that produced three broken packages on 2026-07-31.
    for src_stem, prefix, cols in SINGLE_YEAR_BLOCKS:
        f = os.path.join(OUT, f"{src_stem}.csv")
        if not os.path.exists(f):
            raise SystemExit(f"line_windows: {src_stem}.csv missing — build order changed?")
        src = pd.read_csv(f)
        for out_name, col_tpl in cols:
            col = col_tpl.format(y=lcy)
            if col not in src.columns:
                raise SystemExit(
                    f"line_windows: {src_stem}.csv has no column {col!r}. The single-year "
                    f"blocks are pinned to the latest complete year ({lcy}); if the column "
                    f"naming changed, update SINGLE_YEAR_BLOCKS.")
            vals = src[col].tolist()
            vals = vals + [float("nan")] * (nrows - len(vals))
            out[f"{prefix}_{out_name}"] = vals[:nrows]

    # --- appended blocks (added 2026-08-06) -----------------------------------
    # Later additions go HERE, at the end, never into LINE_WINDOWS above: the live
    # workbook's chart references and its Power Query column count are pinned to the
    # existing column POSITIONS, so inserting into the middle would silently shift
    # every column to the right of the insertion and repoint every chart at the
    # wrong data. Append-only keeps the published layout stable.
    for stem, countries, tag in LINE_WINDOWS_APPEND:
        f = os.path.join(OUT, f"{stem}.csv")
        if not os.path.exists(f):
            raise SystemExit(f"line_windows: {stem}.csv missing — build order changed?")
        src = pd.read_csv(f)
        ef = os.path.join(OUT, f"{stem}_extra.csv")
        extra = pd.read_csv(ef) if os.path.exists(ef) else pd.DataFrame()
        for c in countries:
            for i, y in enumerate(years, start=1):
                col = f"{c}_{y}"
                # Countries beyond the original five are not in the legacy CSV; their
                # columns are published to a companion "_extra" file. Same reasoning as
                # in the loop above.
                frame = src if col in src.columns else extra
                vals = frame[col].tolist() if col in frame.columns else []
                vals = vals + [float("nan")] * (nrows - len(vals))
                out[f"{tag}_{c}_w{i}"] = vals[:nrows]

    # An all-empty window means the source frame never held that country: the chart
    # reading it draws nothing while every downstream check passes, because the column
    # exists and is the right width. Both lists are checked, since a block added to the
    # append list is exactly the case that went unnoticed.
    for stem, countries, tag in LINE_WINDOWS + LINE_WINDOWS_APPEND:
        for c in countries:
            cols = [f"{tag}_{c}_w{i}" for i in range(1, len(years) + 1)
                    if f"{tag}_{c}_w{i}" in out]
            if cols and all(out[col].isna().all() for col in cols):
                print(f"  !! line_windows: {tag}_{c} is empty in every slot — "
                      f"{stem} has no {c} columns", flush=True)

    _save(out, "line_windows")


def main():
    print("building extra chart tables (G1/G2/G3 + charts 16-19) ->", PUB, flush=True)
    df = _load()
    g1(df); g2_quarter(df); g2_month(df); g3_july(df)
    figA_monthly_price(df); figB_penetration(df); figC_capture_erosion(); figD_netload_duck(df)
    line_windows()   # shared rolling window for the seven LINE charts
    print("done", flush=True)

if __name__ == "__main__":
    main()
