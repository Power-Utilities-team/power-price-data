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

def main():
    print("building extra chart tables (G1/G2/G3 + charts 16-19) ->", PUB, flush=True)
    df = _load()
    g1(df); g2_quarter(df); g2_month(df); g3_july(df)
    figA_monthly_price(df); figB_penetration(df); figC_capture_erosion(); figD_netload_duck(df)
    print("done", flush=True)

if __name__ == "__main__":
    main()
