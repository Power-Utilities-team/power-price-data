"""
summaries.py — compute all derived/summary tables from the hourly UTC master.

Reads : data/processed/hourly_master.parquet, capacity_annual.parquet
Writes: data/processed/summaries/*.parquet   (tidy long form)

Tables (each feeds one or more Redburn figures / Fred's requested analytics):
  neg_hours          negative & near-negative hour counts   (Fred a; Fig 3 totals)
  cum_neghours       cumulative near-neg / neg by day-of-year (Fig 3 curves)
  intraday_price     avg price by UTC hour, per year + indexed (Fred b; Fig 2)
  price_sd           annual std-dev / mean / CV of hourly price (Fig 1)
  duration_curve     price at each 0..100% percentile, per year   (Fig 4)
  daily_minmax       daily min/max/mean price & spread            (Fig 6)
  capture_monthly    capture price per tech per month + base + %  (Fred c; Fig 5)
  capture_annual     capture price per tech per year + base + %   (Fig 5)
  intraday_genmix    avg generation mix + pumped cons + net flow + price by UTC hour (Fig 7)
  capacity           annual installed capacity per tech          (Fig 9)

All time buckets use UTC (Fred's instruction). 2026 is partial (YTD).
"""
from __future__ import annotations
import os, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import config as cfg

SUM_DIR = os.path.join(cfg.PROC_DIR, "summaries")
os.makedirs(SUM_DIR, exist_ok=True)

def _load():
    m = pd.read_parquet(os.path.join(cfg.PROC_DIR, "hourly_master.parquet"))
    m["ts_utc"] = pd.to_datetime(m["ts_utc"], utc=True)
    m["year"] = m["ts_utc"].dt.year
    m["month"] = m["ts_utc"].dt.month
    m["hour_utc"] = m["ts_utc"].dt.hour
    m["date"] = m["ts_utc"].dt.date
    m["doy"] = m["ts_utc"].dt.dayofyear
    return m

def _save(df, name):
    p = os.path.join(SUM_DIR, f"{name}.parquet")
    df.to_parquet(p, index=False)
    print(f"  {name:16s} {df.shape}", flush=True)
    return df

GEN_COLS = [f"gen_{t}" for t in cfg.TECH_ORDER]

# ---------------------------------------------------------------------------
def neg_hours(m):
    rows = []
    for (c, y), g in m.groupby(["country", "year"]):
        p = g["price"].dropna()
        n = len(p)
        rows.append({
            "country": c, "year": y, "total_hours": n,
            "neg_hours": int((p < cfg.NEG_PRICE_THRESHOLD).sum()),
            "near_neg_hours": int((p < cfg.NEAR_NEG_THRESHOLD).sum()),
            "neg_pct": round(float((p < cfg.NEG_PRICE_THRESHOLD).mean() * 100), 2) if n else np.nan,
            "near_neg_pct": round(float((p < cfg.NEAR_NEG_THRESHOLD).mean() * 100), 2) if n else np.nan,
        })
    return _save(pd.DataFrame(rows), "neg_hours")

def cum_neghours(m):
    rows = []
    for (c, y), g in m.groupby(["country", "year"]):
        g = g.sort_values("ts_utc")
        daily = g.groupby("doy")["price"].agg(
            near=lambda s: (s < cfg.NEAR_NEG_THRESHOLD).sum(),
            neg=lambda s: (s < cfg.NEG_PRICE_THRESHOLD).sum(),
        )
        # Days with no negative hours legitimately contribute zero, so reindex-with-0
        # is right WITHIN the covered period. Past the end of the data it is not: the
        # cumulative total simply repeats, drawing a dead-flat line to 31 December that
        # asserts "no further negative hours all year" when the truth is "we do not know
        # yet". On the 2026 YTD series that was 154 days of invented flat line.
        last_doy = int(g["doy"].max())
        daily = daily.reindex(range(1, 367), fill_value=0)
        doy = np.arange(1, 367)
        beyond = doy > last_doy
        cum_near = np.where(beyond, np.nan, daily["near"].cumsum().to_numpy(float))
        cum_neg = np.where(beyond, np.nan, daily["neg"].cumsum().to_numpy(float))
        rows.append(pd.DataFrame({
            "country": c, "year": y, "doy": doy,
            "cum_near_neg": cum_near,
            "cum_neg": cum_neg,
        }))
    return _save(pd.concat(rows, ignore_index=True), "cum_neghours")

def intraday_price(m):
    rows = []
    for (c, y), g in m.groupby(["country", "year"]):
        ym = g["price"].mean()
        hp = g.groupby("hour_utc")["price"].mean().reindex(range(24))
        rows.append(pd.DataFrame({
            "country": c, "year": y, "hour_utc": range(24),
            "avg_price": hp.values.round(3),
            "indexed": (hp / ym).values.round(4),
        }))
    return _save(pd.concat(rows, ignore_index=True), "intraday_price")

def price_sd(m):
    rows = []
    for (c, y), g in m.groupby(["country", "year"]):
        p = g["price"].dropna()
        rows.append({"country": c, "year": y,
                     "sd": round(float(p.std()), 3),
                     "mean": round(float(p.mean()), 3),
                     "cv": round(float(p.std() / p.mean()), 4) if p.mean() else np.nan})
    return _save(pd.DataFrame(rows), "price_sd")

def duration_curve(m):
    steps = cfg.DURATION_CURVE_STEPS  # 101 -> 0,1,..,100%
    pct = np.linspace(0, 100, steps)
    rows = []
    for (c, y), g in m.groupby(["country", "year"]):
        p = g["price"].dropna().sort_values(ascending=False).values
        if len(p) == 0:
            continue
        # x = share of hours (0% = highest price). interpolate price at each pct
        xp = np.linspace(0, 100, len(p))
        vals = np.interp(pct, xp, p)
        rows.append(pd.DataFrame({"country": c, "year": y,
                                  "pct_of_hours": pct.round(1),
                                  "price": vals.round(3)}))
    return _save(pd.concat(rows, ignore_index=True), "duration_curve")

def daily_minmax(m):
    rows = []
    for (c, y), g in m.groupby(["country", "year"]):
        d = g.groupby("date")["price"].agg(["min", "max", "mean"]).reset_index()
        d["spread"] = d["max"] - d["min"]
        d.insert(0, "year", y); d.insert(0, "country", c)
        rows.append(d)
    out = pd.concat(rows, ignore_index=True)
    out = out.rename(columns={"min": "min_price", "max": "max_price", "mean": "mean_price"})
    return _save(out.round(3), "daily_minmax")

def _capture(g):
    """capture price per tech over a group; returns dict tech->capture, plus base."""
    p = g["price"]
    base = p.mean()
    res = {}
    for t in cfg.TECH_ORDER:
        col = f"gen_{t}"
        if col not in g:
            continue
        gg = g[col]
        m = gg.notna() & p.notna()
        tot = gg[m].sum()
        res[t] = (gg[m] * p[m]).sum() / tot if tot > 0 else np.nan
    return res, base

def capture_monthly(m):
    rows = []
    for (c, y, mo), g in m.groupby(["country", "year", "month"]):
        cap, base = _capture(g)
        for t, v in cap.items():
            gcol = g[f"gen_{t}"]
            rows.append({"country": c, "year": y, "month": mo, "tech": t,
                         "capture_price": round(v, 3) if pd.notna(v) else np.nan,
                         "base_price": round(base, 3),
                         "capture_vs_base_pct": round((v / base - 1) * 100, 2) if (pd.notna(v) and base) else np.nan,
                         "generation_gwh": round(float(gcol.sum() / 1e3), 2)})
    return _save(pd.DataFrame(rows), "capture_monthly")

def capture_annual(m):
    rows = []
    for (c, y), g in m.groupby(["country", "year"]):
        cap, base = _capture(g)
        for t, v in cap.items():
            gcol = g[f"gen_{t}"]
            rows.append({"country": c, "year": y, "tech": t,
                         "capture_price": round(v, 3) if pd.notna(v) else np.nan,
                         "base_price": round(base, 3),
                         "capture_vs_base_pct": round((v / base - 1) * 100, 2) if (pd.notna(v) and base) else np.nan,
                         "generation_twh": round(float(gcol.sum() / 1e6), 3)})
    return _save(pd.DataFrame(rows), "capture_annual")

def intraday_genmix(m):
    rows = []
    aggmap = {c: "mean" for c in GEN_COLS if c in m.columns}
    aggmap.update({"pumped_consumption": "mean", "flow_net": "mean",
                   "flow_import": "mean", "flow_export": "mean", "price": "mean"})
    for (c, y), g in m.groupby(["country", "year"]):
        h = g.groupby("hour_utc").agg(aggmap).reindex(range(24)).reset_index()
        # render pumped consumption as negative for stacking (per Fig 7)
        h["pumped_consumption"] = -h["pumped_consumption"]
        h.insert(0, "year", y); h.insert(0, "country", c)
        rows.append(h)
    out = pd.concat(rows, ignore_index=True)
    return _save(out.round(2), "intraday_genmix")

def capacity(_m):
    cap = pd.read_parquet(os.path.join(cfg.PROC_DIR, "capacity_annual.parquet"))
    return _save(cap.round(2), "capacity")

def main():
    m = _load()
    print(f"master loaded {m.shape}, countries {sorted(m.country.unique())}, years {sorted(m.year.unique())}", flush=True)
    neg_hours(m); cum_neghours(m); intraday_price(m); price_sd(m)
    duration_curve(m); daily_minmax(m); capture_monthly(m); capture_annual(m)
    intraday_genmix(m); capacity(m)
    print("summaries done", flush=True)

if __name__ == "__main__":
    main()
