"""
summarise_hydro.py — turn the weekly reservoir pulls into the two chart-ready CSVs.

THE EXHIBIT THIS FEEDS. One chart per zone: a shaded band showing the historic
minimum-to-maximum range of reservoir fill for that week of the year, with the recent
years drawn over it as lines plus the long-run average. It is the standard way a hydro
position is read, and it is the shape of every chart on the Hydro Tracker's "Graphs
Only" sheet, which this reproduces from the ENTSO-E source rather than by hand.

HOW THE BAND IS DRAWN, AND WHY IT IS TWO SERIES. Excel has no band primitive. The
Hydro Tracker builds one as a STACKED AREA of two series: the minimum (drawn in no
fill, so it is invisible) and then the range (max - min) stacked on top of it, which
occupies exactly the space between the two. So the CSV publishes `min` and `range`
rather than `min` and `max`, because the chart needs the second series to be the
DIFFERENCE. Publishing max and subtracting in the chart is not possible.

WEEK NUMBERING. ENTSO-E stamps each observation at the start of its week, and years
contain 52 or 53 of them. The x-axis is week-of-year 1..53, so a 52-week year simply
leaves week 53 blank, which a line chart does not draw. Aligning on week number rather
than on date is what makes years comparable at all: a fixed calendar date falls in a
different part of the melt season each year.

UNITS. Stored energy is published in MWh and shown in TWh, matching the tracker.

Reads : data/raw/hydro_<zone>_<year>.parquet   (fetch_hydro.py)
        data/processed/hourly_master.parquet   (for the pumped-storage fallback)
Writes: outputs/csv/charts/hydro_reservoir.csv
        outputs/csv/charts/hydro_window.csv
"""
from __future__ import annotations
import glob
import os
import re
import warnings
warnings.filterwarnings("ignore")
import numpy as np
import pandas as pd

import config as cfg
from completeness import cutoffs as _cutoffs

OUT = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")
os.makedirs(OUT, exist_ok=True)

WEEKS = list(range(1, 54))
YRS = cfg.DISPLAY_YEARS
_LCY = _cutoffs()["last_complete_year"]

# The band's history. Every COMPLETE year we hold, which is what makes "the widest the
# reservoir has been this week of the year" mean something. The current year is excluded
# from the band by construction: a part-year would narrow the band it is plotted against.
def _band_years(available):
    return [y for y in available if y <= _LCY]


# The lines drawn over the band: the last four complete years plus the current year to
# date, and the long-run average. Five year-lines matches the tracker's own charts, and
# they sit in the same rolling w-slots the rest of the workbook uses, so they roll every
# January with no chart rebuild. w1..w7 exist for consistency with the other window
# tables; the hydro charts read w4..w8.
def _window_years():
    return cfg.window_years(_LCY) + [_LCY + 1]


def _read_zone(key):
    """Every stored year for one zone, as a single weekly series in TWh."""
    frames = []
    for p in sorted(glob.glob(os.path.join(cfg.RAW_DIR, f"hydro_{key}_*.parquet"))):
        if os.path.getsize(p) == 0:
            continue
        df = pd.read_parquet(p)
        if df.empty:
            continue
        col = "stored_mwh" if "stored_mwh" in df.columns else df.columns[0]
        frames.append(df[[col]].rename(columns={col: "mwh"}))
    if not frames:
        return None
    s = pd.concat(frames).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    out = pd.DataFrame({"twh": s["mwh"] / 1e6})
    idx = pd.DatetimeIndex(out.index)
    iso = idx.isocalendar()
    out["year"] = iso.year.values
    out["week"] = iso.week.values
    # ENTSO-E stamps the week start, so a reading dated 29 December belongs to ISO week 1
    # of the NEXT year. isocalendar already resolves that; taking the calendar year here
    # instead would put one stray point at week 1 of the wrong year, which shows up as a
    # single spike at the left edge of the chart.
    return out


def _pumped_weekly(country):
    """Weekly pumped-storage generation, for markets with no reservoir series at all.

    Germany and Great Britain publish no A72 water-reservoir data (probed 2026-08-25),
    so there is nothing to draw a fill-level band from. Fred's call was to show pumped
    storage where the data exists rather than leave a blank panel. This is a FLOW, not a
    stock: it is weekly generation in GWh, and every caption says pumped storage, never
    reservoir, because the two answer different questions and would otherwise be read as
    the same exhibit.
    """
    p = os.path.join(cfg.PROC_DIR, "hourly_master.parquet")
    if not os.path.exists(p):
        return None
    col = "gen_Hydro pumped (production)"
    df = pd.read_parquet(p, columns=["country", "ts_utc", col])
    df = df[df["country"] == country]
    if df.empty or df[col].isna().all():
        return None
    ts = pd.DatetimeIndex(pd.to_datetime(df["ts_utc"], utc=True))
    iso = ts.isocalendar()
    out = pd.DataFrame({"twh": df[col].to_numpy() / 1000.0,   # MW hourly -> GWh for the week
                        "year": iso.year.values, "week": iso.week.values})
    return out.groupby(["year", "week"], as_index=False)["twh"].sum()


def _zone_columns(out, win, label, data, band_years):
    """Write one zone's block into both tables. Returns False if it has nothing."""
    if data is None or data.empty:
        return False
    wide = data.pivot_table(index="week", columns="year", values="twh", aggfunc="mean")
    wide = wide.reindex(WEEKS)
    available = [int(y) for y in wide.columns]
    band = [y for y in _band_years(available)]
    if not band:
        return False

    for y in YRS:
        out[f"{label}_{y}"] = wide[y].round(3).values if y in wide.columns else np.nan

    b = wide[band]
    mn = b.min(axis=1)
    mx = b.max(axis=1)
    out[f"{label}_min"] = mn.round(3).values
    # The SECOND band series is the range, not the max: the chart stacks it on the
    # invisible minimum to fill the space between. See the module docstring.
    out[f"{label}_range"] = (mx - mn).round(3).values
    out[f"{label}_max"] = mx.round(3).values
    out[f"{label}_avg"] = b.mean(axis=1).round(3).values

    for i, y in enumerate(_window_years(), start=1):
        win[cfg.wcol(label, i)] = wide[y].round(3).values if y in wide.columns else np.nan
    win[f"{label}_min"] = out[f"{label}_min"]
    win[f"{label}_range"] = out[f"{label}_range"]
    win[f"{label}_avg"] = out[f"{label}_avg"]
    return True


def build():
    out = pd.DataFrame({"week": WEEKS})
    win = pd.DataFrame({"week": WEEKS})
    built, empty = [], []

    for key, _area, _name in cfg.HYDRO_RESERVOIR_ZONES:
        data = _read_zone(key)
        ok = _zone_columns(out, win, key, data, band_years=None)
        (built if ok else empty).append(key)

    # Germany and the UK: pumped storage instead of a blank panel.
    for country in cfg.PUMPED_ONLY:
        label = f"{country}pump"
        ok = _zone_columns(out, win, label, _pumped_weekly(country), band_years=None)
        (built if ok else empty).append(label)

    out.to_csv(os.path.join(OUT, "hydro_reservoir.csv"), index=False, encoding="utf-8")
    win.to_csv(os.path.join(OUT, "hydro_window.csv"), index=False, encoding="utf-8")
    print(f"hydro: {len(built)} block(s) written -> {', '.join(built)}", flush=True)
    if empty:
        print(f"hydro: no data for {', '.join(empty)}", flush=True)
    return built, empty


if __name__ == "__main__":
    build()
