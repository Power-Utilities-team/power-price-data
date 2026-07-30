"""
render_all.py — render EVERY deck exhibit as a house-style PNG, straight from the
data (no Excel). Feeds build_static_deck.py, which assembles a self-contained deck.

Charts are drawn CLEAN (no in-image title/footer) — the deck adds the navy Redburn
caption bars + source line, so the static deck matches the linked one.

Completeness gating (completeness.py):
  * annual-stat charts  -> years <= last_complete_year
  * intraday PROFILES    -> keep the current partial year, labelled "<yr> YTD"
  * G1 quarterly-avg     -> only dates within complete quarters
  * single-year exhibits -> default to the LATEST COMPLETE year
  * Spain snapshots       -> fixed complete years (render_snapshots.py)

Writes: outputs/deck_charts/*.png
"""
from __future__ import annotations
import os, sys, warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
# chartstyle is VENDORED into _tools/ so CI (and any machine) can render without the skill
import chartstyle as cs
import config as cfg
import charts as ch                     # reuse load(), year_colors(), footer(), TECH_COLORS
import completeness

OUT = os.path.join(cfg.OUTPUT_DIR, "deck_charts")
CSV = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")
os.makedirs(OUT, exist_ok=True)

CUT = completeness.cutoffs()
LCY = CUT["last_complete_year"]
QEND = pd.Timestamp(CUT["last_complete_quarter_end"])
COUNTRY_COLORS = {"DE": "#2E3E80", "ES": "#8A1E41", "PT": "#CC9F53", "FR": "#5FA1AD", "IT": "#3D664A"}
MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]


def _save(fig, name):
    p = os.path.join(OUT, name); cs.save_fig(fig, p); print("  ->", name, flush=True)

def _years(avail, mode):
    yrs = sorted(int(y) for y in avail)
    if mode == "annual":
        yrs = [y for y in yrs if y <= LCY]
        return yrs, {y: str(y) for y in yrs}
    return yrs, {y: (f"{y} YTD" if y > LCY else str(y)) for y in yrs}   # profile


# ---- line-by-year (fig2 indexed / avg, fig4 duration, fig3 cumneg, country variants) ----
def line_by_year(summary, xcol, ycol, country, mode, name, unit,
                 size=(4.3, 2.6), xlabel=None, xlim=None, xticks=None, hline=None):
    d = ch.load(summary); d = d[d.country == country]
    yrs, labels = _years(d.year.unique(), mode)
    cmap = ch.year_colors(yrs)
    fig, ax = cs.new_fig(*size)
    for y in yrs:
        s = d[d.year == y].sort_values(xcol)
        ax.plot(s[xcol], s[ycol], color=cmap[y], lw=1.9 if y == yrs[-1] else 1.0, label=labels[y])
    if hline is not None: ax.axhline(hline, color="#B0B0B0", lw=0.6)
    cs.style_axes(ax, unit_label=unit)
    if xticks is not None: ax.set_xticks(xticks)
    if xlim: ax.set_xlim(*xlim)
    if xlabel: ax.set_xlabel(xlabel, fontsize=6)
    fig.legend(loc="outside lower center", ncols=min(len(yrs), 8), fontsize=5.5, frameon=False)
    _save(fig, name)


def fig1_sd(country="DE", name="fig1_sd.png"):
    d = ch.load("price_sd"); d = d[(d.country == country) & (d.year <= LCY)].sort_values("year")
    fig, ax = cs.new_fig(4.3, 2.6)
    ax.plot(d.year, d.sd, color=cs.NAVY, marker="o", ms=4, lw=1.6)
    for _, r in d.iterrows():
        ax.annotate(f"{r.sd:.0f}", (r.year, r.sd), textcoords="offset points",
                    xytext=(0, 6), ha="center", fontsize=6, color=cs.NAVY)
    cs.style_axes(ax, unit_label="std dev (EUR/MWh)")
    _save(fig, name)


def fig3_annual(name="fig3_annual.png"):
    d = ch.load("neg_hours"); d = d[d.year <= LCY]
    yrs = sorted(d.year.unique())
    countries = [c for c in cfg.COUNTRY_ORDER]
    fig, ax = cs.new_fig(4.3, 2.6)
    x = np.arange(len(yrs)); w = 0.8 / len(countries)
    for i, c in enumerate(countries):
        vals = [d[(d.country == c) & (d.year == y)]["neg_hours"].pipe(
                lambda s: s.iloc[0] if len(s) else np.nan) for y in yrs]
        ax.bar(x + i * w - 0.4 + w / 2, vals, w, color=COUNTRY_COLORS[c], label=cfg.COUNTRIES[c]["name"])
    cs.style_axes(ax, unit_label="# negative-price hours")
    ax.set_xticks(x); ax.set_xticklabels([str(y) for y in yrs], fontsize=6)
    fig.legend(loc="outside lower center", ncols=len(countries), fontsize=5.5, frameon=False)
    _save(fig, name)


def bar_tech_by_year(summary, valcol, country, name, unit, size=(6.6, 3.0), zero_line=True):
    d = ch.load(summary); d = d[(d.country == country) & (d.year <= LCY)]
    yrs = sorted(d.year.unique())
    # curated set (note Figs 5/47 Germany, 50 Portugal) — not all 17 ENTSO-E types.
    # The capture chart uses the shorter list: German nuclear is excluded there but
    # kept on capacity, so the two must not share one list (see config.TECH_BLOCKS).
    if valcol == "capture_vs_base_pct":
        keep = cfg.tech_keep_capture(country)
        techs = [t for t in keep if d[d.tech == t][valcol].notna().any()]
    else:
        keep = cfg.tech_keep(country)
        techs = [t for t in keep if d[d.tech == t][valcol].sum() > 0]
    cmap = ch.year_colors(yrs)
    fig, ax = cs.new_fig(*size)
    x = np.arange(len(techs)); w = 0.8 / len(yrs)
    for i, y in enumerate(yrs):
        vals = [d[(d.tech == t) & (d.year == y)][valcol].pipe(
                lambda s: s.iloc[0] if len(s) and pd.notna(s.iloc[0]) else np.nan) for t in techs]
        ax.bar(x + i * w - 0.4 + w / 2, vals, w, color=cmap[y], label=str(y))
    if zero_line: ax.axhline(0, color="#606060", lw=0.7)
    cs.style_axes(ax, unit_label=unit)
    ax.set_xticks(x); ax.set_xticklabels(techs, rotation=45, ha="right", fontsize=5.5)
    fig.legend(loc="outside lower center", ncols=len(yrs), fontsize=5.5, frameon=False)
    _save(fig, name)


def fig6_minmax(country="DE", year=None, name="fig6.png"):
    year = year or LCY
    d = ch.load("daily_minmax"); d = d[(d.country == country) & (d.year == year)]
    fig, ax = cs.new_fig(4.3, 2.9)
    ax.scatter(d.max_price, d.min_price, s=9, color=cs.TEAL, alpha=0.6, edgecolors="none")
    ax.scatter([d.max_price.mean()], [d.min_price.mean()], s=45, color=cs.NAVY, zorder=5)
    ax.axhline(0, color="#B0B0B0", lw=0.6); ax.axvline(0, color="#B0B0B0", lw=0.6)
    cs.style_axes(ax, unit_label="min price (EUR/MWh)")
    ax.set_xlabel("max price (EUR/MWh)", fontsize=6)
    _save(fig, name)
    return year


def fig7_genmix(country="PT", year=None, name="fig7.png"):
    year = year or LCY
    d = ch.load("intraday_genmix"); d = d[(d.country == country) & (d.year == year)].sort_values("hour_utc")
    # curated legend (note Fig 7): the omitted types are 0.13% of Portuguese volume
    techs = [t for t in cfg.GENMIX_KEEP
             if f"gen_{t}" in d.columns and d[f"gen_{t}"].abs().sum() > 0]
    fig, ax = cs.new_fig(8.4, 3.4)
    hours = d.hour_utc.values; bottom = np.zeros(len(d))
    for t in techs:
        v = d[f"gen_{t}"].values
        ax.bar(hours, v, bottom=bottom, color=ch.TECH_COLORS.get(t, "#CCCCCC"), width=0.9, label=t)
        bottom += np.nan_to_num(v)
    ax.bar(hours, d["pumped_consumption"].values, color="#9CCC65", width=0.9, label="Pumped (consumption)")
    ax.bar(hours, d["flow_net"].values, bottom=bottom, color="#D4A017", width=0.5, label="Net import/(export)")
    cs.style_axes(ax, unit_label="MW")
    ax2 = ax.twinx(); ax2.plot(hours, d["price"].values, color="black", lw=1.8, label="Power price")
    ax2.set_ylabel("EUR/MWh", fontsize=6); ax2.tick_params(labelsize=6)
    ax.set_xlabel("hour (UTC)", fontsize=6); ax.set_xticks(range(0, 24, 3))
    fig.legend(loc="outside right upper", fontsize=4.8, frameon=False)
    _save(fig, name)
    return year


def g1_solarpeak(name="g1_solarpeak.png"):
    df = pd.read_csv(os.path.join(CSV, "g1_solar_peakhour.csv"))
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= QEND]                       # only complete quarters
    fig, ax = cs.new_fig(4.3, 2.6)
    for cc, col, name_ in [("DE", "DE_qavg", "Germany"), ("ES", "ES_qavg", "Spain"), ("PT", "PT_qavg", "Portugal")]:
        ax.plot(df["date"], df[col], color=COUNTRY_COLORS[cc], lw=1.6, label=name_)
    cs.style_axes(ax, unit_label="solar share of peak hour (%)")
    fig.legend(loc="outside lower center", ncols=3, fontsize=5.5, frameon=False)
    _save(fig, name)


def g2_monthduck(country="DE", year=None, name="g2_monthduck.png"):
    year = year or LCY
    df = pd.read_csv(os.path.join(CSV, "g2_price_by_month.csv"))
    import matplotlib.colors as mc
    ramp = mc.LinearSegmentedColormap.from_list("mon", [cs.NAVY, cs.TEAL, cs.GOLD, cs.WINE])
    # only complete months if plotting the current (partial) year
    lcy_y, lcy_m = CUT["last_complete_month"]
    max_m = 12 if year < lcy_y else (lcy_m if year == lcy_y else 0)
    fig, ax = cs.new_fig(4.3, 2.6)
    for mi in range(1, max_m + 1):
        col = f"{country}_{year}_M{mi:02d}"
        if col in df.columns:
            ax.plot(df["hour_utc"], df[col], color=ramp((mi - 1) / 11), lw=1.4, label=MONTHS[mi - 1])
    ax.axhline(0, color="#B0B0B0", lw=0.6)
    cs.style_axes(ax, unit_label="EUR/MWh")
    ax.set_xticks(range(0, 24, 3)); ax.set_xlabel("hour (UTC)", fontsize=6)
    fig.legend(loc="outside lower center", ncols=6, fontsize=5.0, frameon=False)
    _save(fig, name)


# ---- charts 16-19 + F: monthly market-state exhibits (read the SAME published CSVs as Path A) ----
WIND_SOLAR = ["gen_Solar", "gen_Onshore wind", "gen_Offshore wind"]

def a_price(name="A_monthly_price.png"):
    df = pd.read_csv(os.path.join(CSV, "figA_monthly_price.csv")); df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(how="all", subset=list(cfg.COUNTRY_ORDER))
    fig, ax = cs.new_fig(4.3, 2.7)
    for cc in cfg.COUNTRY_ORDER:
        ax.plot(df["date"], df[cc], color=COUNTRY_COLORS[cc], lw=1.7 if cc == "DE" else 1.0,
                label=cfg.COUNTRIES[cc]["name"])
    cs.style_axes(ax, unit_label="EUR/MWh  (monthly baseload)")
    fig.legend(loc="outside lower center", ncols=5, fontsize=5.2, frameon=False)
    _save(fig, name)


def b_pen(name="B_penetration.png"):
    df = pd.read_csv(os.path.join(CSV, "figB_penetration.csv")); df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(how="all", subset=list(cfg.COUNTRY_ORDER))
    fig, ax = cs.new_fig(4.3, 2.7)
    for cc in cfg.COUNTRY_ORDER:
        ax.plot(df["date"], df[cc], color=COUNTRY_COLORS[cc], lw=1.7 if cc == "DE" else 1.0,
                label=cfg.COUNTRIES[cc]["name"])
    cs.style_axes(ax, unit_label="wind + solar, % of generation  (12-mo avg)")
    fig.legend(loc="outside lower center", ncols=5, fontsize=5.2, frameon=False)
    _save(fig, name)


def c_capture(name="C_capture_erosion.png"):
    df = pd.read_csv(os.path.join(CSV, "figC_capture_erosion.csv")); df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(how="all", subset=["DE_Solar", "DE_Wind"])
    fig, ax = cs.new_fig(4.3, 2.7)
    ax.plot(df["date"], df["DE_Solar"], color=cs.GOLD, lw=1.3, label="Solar")
    ax.plot(df["date"], df["DE_Wind"], color=cs.TEAL, lw=1.3, label="Onshore wind")
    ax.axhline(0, color="#606060", lw=0.7)                       # 0 = parity with baseload
    cs.style_axes(ax, unit_label="capture vs baseload, %  (Germany)")
    fig.legend(loc="outside lower center", ncols=2, fontsize=6, frameon=False)
    _save(fig, name)


def d_netload(name="D_netload_duck.png"):
    df = pd.read_csv(os.path.join(CSV, "figD_netload_duck.csv"))
    ycols = [c for c in df.columns if c.startswith("DE_") and df[c].notna().any()]
    yrs = [int(c.split("_")[1]) for c in ycols]
    cmap = ch.year_colors(yrs)
    fig, ax = cs.new_fig(4.3, 2.7)
    for cc, y in zip(ycols, yrs):
        lab = f"{y} YTD" if y > LCY else str(y)
        ax.plot(df["hour_utc"], df[cc], color=cmap[y], lw=1.8 if y == yrs[-1] else 1.0, label=lab)
    cs.style_axes(ax, unit_label="net load, GW  (demand − wind − solar, DE)")
    ax.set_xticks(range(0, 24, 4)); ax.set_xlabel("hour (UTC)", fontsize=6)
    fig.legend(loc="outside lower center", ncols=min(len(yrs), 8), fontsize=5.2, frameon=False)
    _save(fig, name)


def f_scatter(name="F_cannibalisation_DE.png"):
    m = pd.read_parquet(os.path.join(cfg.PROC_DIR, "hourly_master.parquet"),
                        columns=["country", "ts_utc", "price", "gen_total"] + WIND_SOLAR)
    m = m[(m.country == "DE") & (m.gen_total > 0)].copy()
    m["ts_utc"] = pd.to_datetime(m.ts_utc)
    m["share"] = 100 * m[WIND_SOLAR].to_numpy().sum(axis=1) / m.gen_total
    m["year"] = m.ts_utc.dt.year
    yrs = sorted(m.year.unique()); cmap = ch.year_colors(yrs)
    m = m.sort_values("ts_utc"); step = max(1, len(m) // 9000); s = m.iloc[::step]
    fig, ax = cs.new_fig(4.8, 3.0)
    for y in yrs:
        d = s[s.year == y]
        ax.scatter(d.share, d.price, s=4, color=cmap[y], alpha=0.30, edgecolors="none", label=str(y))
    ax.axhline(0, color="#B0B0B0", lw=0.6)
    cs.style_axes(ax, unit_label="hourly price EUR/MWh  (Germany)")
    ax.set_xlabel("wind + solar share of generation, %", fontsize=6)
    leg = fig.legend(loc="outside lower center", ncols=min(len(yrs), 8), fontsize=5.2, frameon=False)
    for h in leg.legend_handles:
        h.set_alpha(1)
    _save(fig, name)


def render_exhibit(png, r):
    """Dispatch one deck_spec render recipe to its renderer (output = png)."""
    k = r["kind"]
    if k == "fig1_sd":
        fig1_sd(r.get("country", "DE"), png)
    elif k == "fig3_annual":
        fig3_annual(png)
    elif k == "line":
        line_by_year(r["summary"], r["x"], r["y"], r["country"], r.get("mode", "profile"), png,
                     r["unit"], size=tuple(r.get("size", (4.3, 2.6))), xlabel=r.get("xlabel"),
                     xlim=tuple(r["xlim"]) if r.get("xlim") else None,
                     xticks=range(0, 24, 3) if r.get("hours") else None, hline=r.get("hline"))
    elif k == "scatter":
        fig6_minmax(r.get("country", "DE"), None, png)
    elif k == "genmix":
        fig7_genmix(r.get("country", "PT"), None, png)
    elif k == "bar":
        bar_tech_by_year(r["summary"], r["val"], r["country"], png, r["unit"],
                         size=tuple(r.get("size", (6.6, 3.0))), zero_line=r.get("zero_line", True))
    elif k == "g1":
        g1_solarpeak(png)
    elif k == "g2":
        g2_monthduck(r.get("country", "DE"), None, png)
    elif k == "a_price":
        a_price(png)
    elif k == "b_pen":
        b_pen(png)
    elif k == "c_capture":
        c_capture(png)
    elif k == "d_netload":
        d_netload(png)
    elif k == "f_scatter":
        f_scatter(png)
    else:
        raise ValueError(f"unknown render kind: {k}")


def main():
    import deck_spec
    print(f"rendering deck charts -> {OUT}  (last complete year={LCY}, quarter={CUT['last_complete_quarter']}, "
          f"month={CUT['last_complete_month']})", flush=True)
    for e in deck_spec.chart_exhibits():
        render_exhibit(e["png"], e["render"])
    print("deck charts done", flush=True)


if __name__ == "__main__":
    main()
