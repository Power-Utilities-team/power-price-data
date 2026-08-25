"""
deck_spec.py — THE SINGLE SOURCE OF TRUTH for the Hourly Power Data deck.

Every builder reads this and nothing else for structure/captions/identity:
  * build_deck.py          (linked deck)   — uses caption, box, chart#
  * build_static_deck.py   (static deck)   — uses caption, box, png
  * render_all.py          (static charts) — uses png, render recipe
  * build_frozen_excel.py  (frozen wb)     — inherits the workbook charts (no change here)
  * check_consistency.py                    — asserts the built decks match THIS

Change an exhibit HERE and every output follows. Adding/moving/relabelling a chart
is a one-place edit; check_consistency.py fails the build if any output drifts.

Each exhibit:
  id        stable key (also the render_all PNG stem for chart exhibits)
  caption   navy exhibit-bar text — IDENTICAL in both decks
  box       "L" | "R" | "1up"
  chart     linked-workbook chart number (xl/charts/chartN.xml), or None for image-only
  png       PNG filename (deck_charts/ for charts, deck_img/ for snapshots)
  render    recipe dict for render_all (kind + params); None = pre-rendered snapshot

Year policy (locked 2026-07-18): single-year exhibits (fig6, fig7) = LATEST COMPLETE
year in both paths; intraday profiles keep the current partial year labelled "YTD".
"""

SOURCE = "Source: ENTSO-E Transparency Platform (hourly prices, generation, flows & capacity)."

# Single-year exhibits state the year they show, as the source note does
# ("Fig 7: ... in Portugal (2024)"). Resolved from the data's coverage so the label
# rolls with the data and can never disagree with the bars above it.
from completeness import cutoffs as _cutoffs
LCY = _cutoffs()["last_complete_year"]

def ex(id, caption, box, chart, png, render):
    return dict(id=id, caption=caption, box=box, chart=chart, png=png, render=render)

# --- render recipes (consumed by render_all) ---
def _line(summary, x, y, country, unit, **kw):
    return dict(kind="line", summary=summary, x=x, y=y, country=country, mode="profile", unit=unit, **kw)

SLIDES = [
    dict(title="Price volatility & negative-price hours",
         kicker="Annual volatility and the incidence of negative prices across the five markets",
         exhibits=[
            ex("fig1_sd", "Price volatility: annual SD of hourly day-ahead price (€/MWh)", "L", 1,
               "fig1_sd.png", dict(kind="fig1_sd", country="DE")),
            ex("fig3_annual", "Negative-price hours per year, by country", "R", 3,
               "fig3_annual.png", dict(kind="fig3_annual")),
         ]),
    dict(title="Negative & extreme prices in detail (Germany)",
         kicker="How negative-hour incidence builds through the year, and the daily price range",
         exhibits=[
            ex("fig3_cumneg_DE", "Cumulative near-negative-price hours through the year (Germany)", "L", 4,
               "fig3_cumneg_DE.png", _line("cum_neghours", "doy", "cum_near_neg", "DE",
                                            "# hours (cumulative)", xlim=[1, 366], xlabel="day of year (UTC)")),
            ex("fig6_DE", f"Daily minimum vs maximum price (Germany, {LCY})", "R", 7,
               "fig6_DE.png", dict(kind="scatter", country="DE")),
         ]),
    dict(title="Intraday price shape & price duration",
         kicker="Average intraday price profile by year, and the full price distribution",
         exhibits=[
            ex("fig2_intraday_DE", "Intraday price shape by year, indexed to daily mean (Germany)", "L", 2,
               "fig2_intraday_DE.png", _line("intraday_price", "hour_utc", "indexed", "DE",
                                             "indexed (1 = annual base)", hours=True, xlabel="hour (UTC)")),
            ex("fig4_duration_PT", "Price duration curves by year (Portugal)", "R", 5,
               "fig4_duration_PT.png", _line("duration_curve", "pct_of_hours", "price", "PT",
                                            "EUR/MWh", xlabel="% of hours (0 = highest-priced)", hline=0)),
         ]),
    dict(title=f"Intraday generation mix & price (Portugal, {LCY})",
         kicker="Hourly generation by technology, with the wholesale price overlaid",
         exhibits=[
            ex("fig7_PT", f"Intraday generation mix and price (Portugal, {LCY})", "1up", 8,
               "fig7_PT.png", dict(kind="genmix", country="PT")),
         ]),
    dict(title="Capture price vs baseload by technology (Germany)",
         kicker="How each technology's realised (capture) price compares with time-weighted baseload",
         exhibits=[
            ex("fig5_capture_DE", "Capture price vs baseload by technology (Germany)", "1up", 6,
               "fig5_capture_DE.png", dict(kind="bar", summary="capture_annual",
                                           val="capture_vs_base_pct", country="DE",
                                           unit="% above/below base price")),
         ]),
    dict(title="Installed generation capacity by technology (Germany)",
         kicker="Installed capacity by technology",
         exhibits=[
            ex("fig9_capacity_DE", "Installed generation capacity by technology (Germany)", "1up", 9,
               "fig9_capacity_DE.png", dict(kind="bar", summary="capacity", val="capacity_mw",
                                            country="DE", unit="installed capacity (MW)", zero_line=False)),
         ]),
    dict(title="Intraday price shape — country variants",
         kicker="Spain's solar 'duck' in the indexed profile, and Germany's absolute price belly",
         exhibits=[
            ex("spain_intraday", "Spain — intraday price shape, indexed to daily mean", "L", 10,
               "spain_intraday.png", _line("intraday_price", "hour_utc", "indexed", "ES",
                                           "indexed (1 = annual base)", hours=True, xlabel="hour (UTC)")),
            ex("germany_duck", "Germany — intraday price shape (€/MWh)", "R", 11,
               "germany_duck.png", _line("intraday_price", "hour_utc", "avg_price", "DE",
                                         "EUR/MWh", hours=True, xlabel="hour (UTC)")),
         ]),
    dict(title="Capture prices & negative hours — country variants",
         kicker="Portugal's technology capture spreads, and the rise of negative-price hours in Spain",
         exhibits=[
            ex("portugal_capture", "Portugal — capture price vs baseload by technology", "L", 12,
               "portugal_capture.png", dict(kind="bar", summary="capture_annual",
                                            val="capture_vs_base_pct", country="PT",
                                            unit="% above/below base price", size=[4.3, 2.6])),
            ex("spain_cumneg", "Spain — cumulative near-negative-price hours through the year", "R", 13,
               "spain_cumneg.png", _line("cum_neghours", "doy", "cum_near_neg", "ES",
                                         "# hours (cumulative)", xlim=[1, 366], xlabel="day of year (UTC)")),
         ]),
    dict(title="Solar's imprint on the intraday market",
         kicker="The share of solar in the peak hour, and how the price 'duck' deepens month by month",
         exhibits=[
            ex("g1_solarpeak", "Solar share of the peak hour, by market (quarterly average)", "L", 14,
               "g1_solarpeak.png", dict(kind="g1")),
            ex("g2_monthduck", "Germany — intraday price by month (the monthly 'duck')", "R", 15,
               "g2_monthduck.png", dict(kind="g2", country="DE")),
         ]),
    dict(title="European power prices & renewables penetration",
         kicker="Monthly baseload price by market, and the rising share of wind & solar in generation",
         exhibits=[
            ex("A_monthly_price",
               "Monthly baseload power price by market (€/MWh). GB is the Elexon market "
               "index, not a day-ahead auction",
               "L", 16,
               "A_monthly_price.png", dict(kind="a_price")),
            ex("B_penetration", "Wind & solar share of generation, by market (12-month average)", "R", 17,
               "B_penetration.png", dict(kind="b_pen")),
         ]),
    dict(title="Renewable capture erosion & the net-load 'duck' (Germany)",
         kicker="How solar's realised price is eroded vs baseload, and how solar hollows out midday net load",
         exhibits=[
            ex("C_capture_erosion", "Solar & wind capture price vs baseload (Germany)", "L", 18,
               "C_capture_erosion.png", dict(kind="c_capture")),
            ex("D_netload_duck", "Net-load 'duck': demand − wind − solar by hour, by year (Germany)", "R", 19,
               "D_netload_duck.png", dict(kind="d_netload")),
         ]),
    dict(title="Spain intraday 'duck' — quarterly, 2019 vs 2025",
         kicker="Average intraday price by quarter (Spain day-ahead)",
         exhibits=[
            ex("snap_quarterly_2019", "2019 — by quarter", "L", None, "snap_quarterly_2019.png", None),
            ex("snap_quarterly_2025", "2025 — by quarter", "R", None, "snap_quarterly_2025.png", None),
         ]),
    dict(title="Spain July price 'spaghetti' — 2019 vs 2025",
         kicker="Every July day's intraday price shape; navy line = July average (Spain)",
         exhibits=[
            ex("snap_july_2019", "2019 — July, daily", "L", None, "snap_july_2019.png", None),
            ex("snap_july_2025", "2025 — July, daily", "R", None, "snap_july_2025.png", None),
         ]),
]

def all_exhibits():
    for s in SLIDES:
        for e in s["exhibits"]:
            yield s, e

def chart_exhibits():
    return [e for _, e in all_exhibits() if e["render"] is not None]

def snapshot_pngs():
    return [e["png"] for _, e in all_exhibits() if e["render"] is None]
