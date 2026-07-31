"""
chart_csv.py — publish CHART-READY wide CSVs (one flat table per figure).

Each file's rows are the chart's x-axis/index and columns are the series, with
YEAR dimensions pre-allocated out to config.DISPLAY_END_YEAR (blank until data
exists). So on Windows a user just does Data > From Web > Load, links the chart
to the columns, and every refresh updates in place with NO cell movement — and
future years appear automatically in the pre-allocated columns.

Country-year columns are named "<CC>_<YYYY>" (e.g. DE_2024); genmix series add
the series suffix "<CC>_<YYYY>_<series>".

Reads : data/processed/summaries/*.parquet
Writes: outputs/csv/charts/*.csv
"""
from __future__ import annotations
import os, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
import config as cfg

SUM = os.path.join(cfg.PROC_DIR, "summaries")
OUT = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")
os.makedirs(OUT, exist_ok=True)

YRS = cfg.DISPLAY_YEARS                 # 2019..2035 (pre-allocated)
CO = cfg.COUNTRY_ORDER
CY = [(c, y) for c in CO for y in YRS]  # country-year column order
def cyname(c, y): return f"{c}_{y}"

from completeness import cutoffs as _cutoffs
_LCY = _cutoffs()["last_complete_year"]
WINDOW = cfg.window_years(_LCY)          # e.g. [2019..2025]; rolls every January


def save_window(out, index_col, name):
    """Write a SEPARATE rolling-window table for the annual bar charts.

    A separate file, not extra columns on the existing one, because the twelve original
    Fig sheets carry tables inherited from the Redburn workbook that are a fixed 86
    columns wide (A1:CH). Anything past CH falls outside the table and the chart cannot
    see it, so widening would mean rewriting table + queryTable + column definitions on
    legacy parts — exactly the surgery that broke chart12 in July. Its own tab uses the
    same proven load path as the six Phase-4 tabs.

    The columns are {country}_w1..wN: their POSITION never changes, so the chart's
    references stay valid for ever, while their MEANING advances one year each January.
    build_status publishes the same year list as the w1..wN labels the legends read, so
    data and labels cannot drift apart.
    """
    w = pd.DataFrame({index_col: out[index_col]})
    for c in CO:
        for i, y in enumerate(WINDOW, start=1):
            src = cyname(c, y)
            w[cfg.wcol(c, i)] = out[src] if src in out.columns else np.nan
    save(w, name)


def load(n): return pd.read_parquet(os.path.join(SUM, f"{n}.parquet"))
def save(df, name):
    p = os.path.join(OUT, f"{name}.csv"); df.to_csv(p, index=False, encoding="utf-8")
    print(f"  {name:22s} {df.shape}", flush=True)

def _pivot(df, index_col, value_col, index_vals):
    """wide table: given index + one value per (country,year); pre-allocated cols."""
    out = pd.DataFrame({index_col: index_vals})
    look = df.set_index(["country", "year", index_col])[value_col]
    for c, y in CY:
        col = cyname(c, y)
        out[col] = [look.get((c, y, iv), np.nan) for iv in index_vals]
    return out

# --- Fig 1: price SD, rows=year, cols=country -------------------------------
def fig1():
    df = load("price_sd").set_index(["country", "year"])["sd"]
    out = pd.DataFrame({"year": YRS})
    for c in CO:
        out[cfg.COUNTRIES[c]["name"]] = [df.get((c, y), np.nan) for y in YRS]
    save(out.round(2), "fig1_price_sd")

# --- Fig 2: indexed & avg intraday price, rows=hour, cols=country_year ------
def fig2():
    df = load("intraday_price")
    save(_pivot(df, "hour_utc", "indexed", list(range(24))).round(4), "fig2_intraday_indexed")
    save(_pivot(df, "hour_utc", "avg_price", list(range(24))).round(2), "fig2_intraday_avg")

# --- Fig 3: neg-hour totals (year x country) + cumulative (doy x cy) --------
def fig3():
    n = load("neg_hours").set_index(["country", "year"])
    out = pd.DataFrame({"year": YRS})
    for c in CO:
        out[f"{cfg.COUNTRIES[c]['name']}_neg"] = [n["neg_hours"].get((c, y), np.nan) for y in YRS]
    for c in CO:
        out[f"{cfg.COUNTRIES[c]['name']}_nearneg"] = [n["near_neg_hours"].get((c, y), np.nan) for y in YRS]
    save(out, "fig3_neg_hours_annual")
    cum = load("cum_neghours")
    save(_pivot(cum, "doy", "cum_near_neg", list(range(1, 367))), "fig3_cum_near_neg")

# --- Fig 4: duration curve, rows=pct, cols=country_year ---------------------
def fig4():
    d = load("duration_curve")
    pcts = sorted(d["pct_of_hours"].unique())
    save(_pivot(d, "pct_of_hours", "price", pcts).round(2), "fig4_duration_curve")

# --- Fig 5: capture vs base % and absolute, rows=tech, cols=country_year ----
def fig5():
    d = load("capture_annual")
    for metric, name in [("capture_vs_base_pct", "fig5_capture_pct"),
                         ("capture_price", "fig5_capture_abs")]:
        # curated display order: each country's set is a contiguous row block
        out = pd.DataFrame({"technology": cfg.tech_row_order()})
        look = d.set_index(["country", "year", "tech"])[metric]
        for c, y in CY:
            out[cyname(c, y)] = [look.get((c, y, t), np.nan)
                                 for t in cfg.tech_row_order()]
        save(out.round(2), name)
        if name == "fig5_capture_pct":
            save_window(out.round(2), "technology", "fig5_capture_window")

# --- Fig 6: daily min/max, rows=doy, cols=country_year_{min,max} ------------
def fig6():
    d = load("daily_minmax").copy()
    d["doy"] = pd.to_datetime(d["date"]).dt.dayofyear
    out = pd.DataFrame({"doy": list(range(1, 367))})
    for metric in ["min_price", "max_price", "mean_price"]:
        look = d.set_index(["country", "year", "doy"])[metric]
        suffix = metric.replace("_price", "")
        for c, y in CY:
            out[f"{cyname(c, y)}_{suffix}"] = [look.get((c, y, dd), np.nan) for dd in range(1, 367)]
    save(out.round(2), "fig6_daily_minmax")

# --- Fig 7: intraday gen mix, rows=hour, cols=country_year_series -----------
def fig7():
    d = load("intraday_genmix")
    series = [f"gen_{t}" for t in cfg.TECH_ORDER] + ["pumped_consumption", "flow_net", "price"]
    out = pd.DataFrame({"hour_utc": list(range(24))})
    look = {s: d.set_index(["country", "year", "hour_utc"])[s] for s in series if s in d.columns}
    for c, y in CY:
        for s in series:
            if s not in look:
                continue
            lab = s.replace("gen_", "")
            out[f"{cyname(c, y)}_{lab}"] = [look[s].get((c, y, h), np.nan) for h in range(24)]
    save(out.round(1), "fig7_gen_mix")

# --- Fig 9: capacity, rows=tech, cols=country_year --------------------------
def fig9():
    d = load("capacity")
    out = pd.DataFrame({"technology": cfg.tech_row_order()})
    look = d.set_index(["country", "year", "tech"])["capacity_mw"]
    for c, y in CY:
        out[cyname(c, y)] = [look.get((c, y, t), np.nan)
                             for t in cfg.tech_row_order()]
    save(out.round(1), "fig9_capacity")
    save_window(out.round(1), "technology", "fig9_capacity_window")

# --- Capture monthly, rows=YYYY-MM, cols=country_tech -----------------------
def capture_monthly():
    d = load("capture_monthly")
    months = [f"{y}-{m:02d}" for y in YRS for m in range(1, 13)]
    d["ym"] = d["year"].astype(str) + "-" + d["month"].astype(str).str.zfill(2)
    look = d.set_index(["country", "tech", "ym"])["capture_price"]
    out = pd.DataFrame({"month": months})
    for c in CO:
        for t in cfg.TECH_ORDER:
            out[f"{c}_{t}"] = [look.get((c, t, ym), np.nan) for ym in months]
    save(out.round(2), "capture_monthly")

def main():
    print("building chart-ready wide CSVs ->", OUT, flush=True)
    fig1(); fig2(); fig3(); fig4(); fig5(); fig6(); fig7(); fig9(); capture_monthly()
    print("chart CSVs done", flush=True)

if __name__ == "__main__":
    main()
