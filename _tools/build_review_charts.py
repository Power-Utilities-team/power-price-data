"""
build_review_charts.py — SCRATCH / REVIEW ONLY.

Renders candidate new monthly-deck exhibits (A-G) to outputs/review_charts/ so Fred
can eyeball them before deciding which to wire permanently into deck_spec.py + both
paths. Touches NOTHING permanent (no deck_spec, no chart XML, no both-deck build).

All completeness-gated the same way render_all.py gates the real deck.
House style via the chart-style skill (chartstyle).
"""
from __future__ import annotations
import os, sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
# chartstyle is VENDORED into _tools/ (see chartstyle.py) so CI can render too
import chartstyle as cs
sys.path.insert(0, os.path.dirname(__file__))
import config as cfg
import charts as ch
import completeness

OUT = os.path.join(cfg.OUTPUT_DIR, "review_charts")
os.makedirs(OUT, exist_ok=True)
MASTER = os.path.join(cfg.PROC_DIR, "hourly_master.parquet")

CUT = completeness.cutoffs()
LCY = CUT["last_complete_year"]
LCM = CUT["last_complete_month"]                 # (year, month)
LCM_END = pd.Timestamp(CUT["last_complete_month_end"])
COUNTRY_COLORS = cfg.COUNTRY_COLORS   # one palette, declared in config
NAME = {k: v["name"] for k, v in cfg.COUNTRIES.items()}
ORDER = cfg.COUNTRY_ORDER
WIND_SOLAR = ["gen_Solar", "gen_Onshore wind", "gen_Offshore wind"]
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _save(fig, name):
    p = os.path.join(OUT, name); cs.save_fig(fig, p); print("  ->", name, flush=True)

def _month_mask(df, ycol="year", mcol="month"):
    """<= last complete month."""
    return (df[ycol] * 100 + df[mcol]) <= (LCM[0] * 100 + LCM[1])

_master_cache = None
def master(cols):
    global _master_cache
    need = set(cols) | {"country", "ts_utc"}
    if _master_cache is None or not need.issubset(_master_cache.columns):
        _master_cache = pd.read_parquet(MASTER, columns=sorted(need))
        _master_cache["ts_utc"] = pd.to_datetime(_master_cache["ts_utc"]).dt.tz_localize(None)
    return _master_cache


# ---------------------------------------------------------------- A: monthly baseload price by country
def A_monthly_price():
    d = ch.load("capture_monthly")[["country", "year", "month", "base_price"]].drop_duplicates(
        ["country", "year", "month"])
    d = d[_month_mask(d)]
    d["date"] = pd.to_datetime(dict(year=d.year, month=d.month, day=1))
    fig, ax = cs.new_fig(6.6, 2.9)
    for c in ORDER:
        s = d[d.country == c].sort_values("date")
        lw = 1.9 if c == "DE" else 1.0
        ax.plot(s.date, s.base_price, color=COUNTRY_COLORS[c], lw=lw, label=NAME[c])
    cs.style_axes(ax, unit_label="EUR/MWh  (monthly baseload avg)")
    fig.legend(loc="outside lower center", ncols=5, fontsize=6, frameon=False)
    _save(fig, "A_monthly_price_by_country.png")


# ---------------------------------------------------------------- B: wind+solar penetration, monthly
def B_renewables_penetration():
    m = master(WIND_SOLAR + ["gen_total"]).copy()
    m["ym"] = m.ts_utc.dt.to_period("M")
    m["ws"] = m[WIND_SOLAR].sum(axis=1)
    g = m.groupby(["country", "ym"]).agg(ws=("ws", "sum"), tot=("gen_total", "sum")).reset_index()
    g["pen"] = 100 * g.ws / g.tot
    g["year"] = g.ym.dt.year; g["month"] = g.ym.dt.month
    g = g[_month_mask(g)]
    g["date"] = g.ym.dt.to_timestamp()
    fig, ax = cs.new_fig(6.6, 2.9)
    for c in ORDER:
        s = g[g.country == c].sort_values("date")
        lw = 1.9 if c == "DE" else 1.0
        ax.plot(s.date, s.pen, color=COUNTRY_COLORS[c], lw=lw, label=NAME[c])
    cs.style_axes(ax, unit_label="wind + solar, % of generation")
    fig.legend(loc="outside lower center", ncols=5, fontsize=6, frameon=False)
    _save(fig, "B_renewables_penetration.png")


# ---------------------------------------------------------------- C: solar & wind capture-rate erosion (DE)
def C_capture_erosion(country="DE"):
    d = ch.load("capture_monthly")
    d = d[(d.country == country) & d.tech.isin(["Solar", "Onshore wind"])].copy()
    d = d[_month_mask(d)]
    d["date"] = pd.to_datetime(dict(year=d.year, month=d.month, day=1))
    fig, ax = cs.new_fig(6.6, 2.9)
    styles = {"Solar": (cs.GOLD, "Solar"), "Onshore wind": (cs.TEAL, "Onshore wind")}
    for tech, (col, lab) in styles.items():
        s = d[d.tech == tech].sort_values("date")
        ax.plot(s.date, s.capture_vs_base_pct, color=col, lw=1.4, label=lab)
    ax.axhline(0, color="#606060", lw=0.7)                       # 0 = parity with baseload
    cs.style_axes(ax, unit_label=f"capture price vs baseload, %  (0 = parity, {NAME[country]})")
    fig.legend(loc="outside lower center", ncols=2, fontsize=6, frameon=False)
    _save(fig, "C_capture_erosion_DE.png")


# ---------------------------------------------------------------- D: net-load duck deepening (DE)
def D_netload_duck(country="DE"):
    m = master(WIND_SOLAR + ["load"]).copy()
    m = m[m.country == country]
    m["res"] = m["load"] - m[WIND_SOLAR].sum(axis=1)
    m["year"] = m.ts_utc.dt.year; m["hour"] = m.ts_utc.dt.hour
    prof = m.groupby(["year", "hour"])["res"].mean().reset_index()
    yrs = sorted(prof.year.unique())
    cmap = ch.year_colors(yrs)
    fig, ax = cs.new_fig(4.6, 2.8)
    for y in yrs:
        s = prof[prof.year == y].sort_values("hour")
        lab = f"{y} YTD" if y > LCY else str(y)
        ax.plot(s.hour, s.res / 1000, color=cmap[y], lw=1.9 if y == yrs[-1] else 1.0, label=lab)
    cs.style_axes(ax, unit_label=f"net load = demand - wind - solar, GW  ({NAME[country]})")
    ax.set_xticks(range(0, 24, 4)); ax.set_xlabel("hour (UTC)", fontsize=6)
    fig.legend(loc="outside lower center", ncols=min(len(yrs), 8), fontsize=5.5, frameon=False)
    _save(fig, "D_netload_duck_DE.png")


# ---------------------------------------------------------------- E: cross-border net flows, monthly
def E_flows():
    m = master(["flow_net"]).copy()
    m["ym"] = m.ts_utc.dt.to_period("M")
    g = m.groupby(["country", "ym"])["flow_net"].mean().reset_index()
    g["year"] = g.ym.dt.year; g["month"] = g.ym.dt.month
    g = g[_month_mask(g)]
    g["date"] = g.ym.dt.to_timestamp()
    # sign check: report FR (big exporter) and IT (big importer) mean
    fr = g[g.country == "FR"]["flow_net"].mean(); it = g[g.country == "IT"]["flow_net"].mean()
    sign = "+ = net export" if fr > it else "+ = net import"
    print(f"  [E] FR mean flow_net={fr:.0f}, IT={it:.0f} -> label '{sign}'")
    fig, ax = cs.new_fig(6.6, 2.9)
    for c in ORDER:
        s = g[g.country == c].sort_values("date")
        ax.plot(s.date, s["flow_net"] / 1000, color=COUNTRY_COLORS[c], lw=1.2, label=NAME[c])
    ax.axhline(0, color="#606060", lw=0.7)
    cs.style_axes(ax, unit_label=f"net cross-border flow, GW  ({sign})")
    fig.legend(loc="outside lower center", ncols=5, fontsize=6, frameon=False)
    _save(fig, "E_crossborder_flows.png")


# ---------------------------------------------------------------- F: cannibalisation scatter (DE)
def F_cannibalisation(country="DE"):
    m = master(WIND_SOLAR + ["gen_total", "price"]).copy()
    m = m[(m.country == country) & (m.gen_total > 0)]
    m["share"] = 100 * m[WIND_SOLAR].sum(axis=1) / m.gen_total
    m["year"] = m.ts_utc.dt.year
    yrs = sorted(m.year.unique())
    cmap = ch.year_colors(yrs)
    # sample for legibility (deterministic: every Nth after sort)
    m = m.sort_values("ts_utc")
    step = max(1, len(m) // 9000)
    s = m.iloc[::step]
    fig, ax = cs.new_fig(4.8, 3.0)
    for y in yrs:
        d = s[s.year == y]
        ax.scatter(d.share, d.price, s=4, color=cmap[y], alpha=0.30, edgecolors="none", label=str(y))
    ax.axhline(0, color="#B0B0B0", lw=0.6)
    cs.style_axes(ax, unit_label=f"hourly price EUR/MWh  ({NAME[country]})")
    ax.set_xlabel("wind + solar share of generation, %", fontsize=6)
    leg = fig.legend(loc="outside lower center", ncols=min(len(yrs), 8), fontsize=5.5, frameon=False)
    for h in leg.legend_handles: h.set_alpha(1)
    _save(fig, "F_cannibalisation_scatter_DE.png")


# ---------------------------------------------------------------- G: monthly negative-hours run-rate
def G_neg_hours_monthly():
    m = master(["price"]).copy()
    m["ym"] = m.ts_utc.dt.to_period("M")
    m["neg"] = (m.price < 0).astype(int)
    g = m.groupby(["country", "ym"])["neg"].sum().reset_index()
    g["year"] = g.ym.dt.year; g["month"] = g.ym.dt.month
    g = g[_month_mask(g)]
    g["date"] = g.ym.dt.to_timestamp()
    fig, ax = cs.new_fig(6.6, 2.9)
    for c in ORDER:
        s = g[g.country == c].sort_values("date")
        lw = 1.9 if c == "DE" else 1.0
        ax.plot(s.date, s["neg"], color=COUNTRY_COLORS[c], lw=lw, label=NAME[c])
    cs.style_axes(ax, unit_label="negative-price hours per month")
    fig.legend(loc="outside lower center", ncols=5, fontsize=6, frameon=False)
    _save(fig, "G_neg_hours_monthly.png")


if __name__ == "__main__":
    print(f"coverage_end={CUT['coverage_end']}  LCY={LCY}  last_complete_month={LCM}")
    A_monthly_price()
    B_renewables_penetration()
    C_capture_erosion()
    D_netload_duck()
    E_flows()
    F_cannibalisation()
    G_neg_hours_monthly()
    print("done ->", OUT)
