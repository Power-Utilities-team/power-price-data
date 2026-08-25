"""
generate.py — ONE command to produce every deliverable, consistently.

  python generate.py            # rebuild all outputs from the data already on disk
  python generate.py --fresh    # first pull ENTSO-E to today, then rebuild everything
  python generate.py --deliver  # also copy the finished files to ~/Downloads

Pipeline (all gated by completeness.py, all driven by deck_spec.py):
  [--fresh] fetch -> build_hourly -> summaries -> extra_summaries -> chart_csv
  render_all -> build_static_deck        (self-contained deck, latest data)
  build_frozen_excel                      (hardcoded workbook, no live pulls)
  add_phase4_charts -> add_power_queries -> build_deck   (linked workbook + linked deck)
  check_consistency                       (FAILS the run if the two decks drift)

The static deck + frozen Excel carry the freshly-pulled data; the linked workbook/
deck are rebuilt structurally (the team refreshes their live data via Power Query).
"""
from __future__ import annotations
import os, sys, subprocess
from datetime import date

TOOLS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TOOLS)
OUT = os.path.join(ROOT, "outputs")
PY = sys.executable
FRESH = "--fresh" in sys.argv
DELIVER = "--deliver" in sys.argv
TEMPLATE = os.path.join(ROOT, "archive", "phase4_2026-07-17", "HourlyPowerData_pre-phase4.pptx")

def run(*cmd):
    print(f"\n$ {' '.join(str(c) for c in cmd)}", flush=True)
    subprocess.run([PY, *[str(c) for c in cmd]], cwd=TOOLS, check=True)


def publish_local_csvs():
    """Copy the built CSVs into published/, the way the CI publish step does."""
    import glob, shutil
    src = os.path.join(OUT, "csv")
    dst = os.path.join(ROOT, "published")
    os.makedirs(os.path.join(dst, "charts"), exist_ok=True)
    n = 0
    for pattern, target in ((os.path.join(src, "*.csv"), dst),
                            (os.path.join(src, "charts", "*.csv"),
                             os.path.join(dst, "charts"))):
        for f in glob.glob(pattern):
            shutil.copy(f, os.path.join(target, os.path.basename(f)))
            n += 1
    manifest = os.path.join(src, "manifest.json")
    if os.path.exists(manifest):
        shutil.copy(manifest, os.path.join(dst, "manifest.json"))
    print(f"\n$ publish {n} CSVs -> published/", flush=True)

def main():
    if FRESH:
        yr = date.today().year
        run("fetch.py", "--years", f"{yr-1},{yr}", "--force")
        # Great Britain left the ENTSO-E Transparency Platform on 15 June 2021, so its
        # series come from Elexon, the ECB and DUKES. fetch.py skips it; this fills it,
        # writing the same raw parquet shapes so nothing downstream needs a GB branch.
        run("fetch_uk.py", "--years", f"{yr-1},{yr}", "--force")
        # Weekly reservoir levels: a different ENTSO-E endpoint (A72), a stock rather
        # than a flow, so it never joins the hourly master and has its own summary step.
        run("fetch_hydro.py")
        run("build_hourly.py")
        run("summaries.py")
        # chart_csv BEFORE extra_summaries, corrected 2026-08-25. extra_summaries ends by
        # building line_windows, which READS the fig2, fig3 and fig4 CSVs that chart_csv
        # writes — so in the old order it always built that table from the PREVIOUS run's
        # files. Harmless while the columns never changed, and not harmless the moment
        # they did: a newly added country's columns did not exist in last run's CSVs, so
        # its window came out empty and its charts drew nothing, with every downstream
        # check passing because the columns were present and the right width.
        run("chart_csv.py")
        run("extra_summaries.py")
        run("summarise_hydro.py")
        run("build_status.py")
        # Stage the freshly-built CSVs into published/ BEFORE the workbook is built.
        # add_power_queries and add_extra_charts both read published/charts to size the
        # load targets and to resolve chart column references, so building from the
        # previous run's copies gives a workbook whose charts point at last month's
        # column layout. CI has always done this in the right order (publish, then
        # rebuild the deliverables); a local run did not, which is why a country added
        # here appeared in the data and nowhere in the charts.
        publish_local_csvs()
    # static path (fresh data)
    run("render_all.py")
    run("build_static_deck.py", os.path.join(OUT, "HourlyPowerData_snapshot.pptx"))
    # linked path (rebuild workbook + deck)
    run("add_phase4_charts.py")
    run("curate_tech_charts.py")    # curated technology sets (note Figs 5/47, 50, 7)
    run("add_status_sheet.py")      # staleness banner (workbook opens on it)
    # BEFORE add_power_queries, because it creates the two tabs that script then wires
    # (CaptureMonthlyExtra, HydroWindow) — and AFTER add_status_sheet, because every
    # chart it builds names its year series from the Status sheet's rolling cells.
    run("add_extra_charts.py")      # CaptureVsBase + the per-country, monthly and hydro charts
    run("add_power_queries.py")     # re-injects the 6 PQ connections add_phase4 rebuilds over
    run("resync_prefill.py")        # cached data == CSV, so no table changes shape on refresh
    run("fix_axes.py")            # labels below the plot, not across it; name the x-axis
    run("fix_year_colours.py")     # one colour per YEAR, identical across charts
    run("fix_negative_bars.py")   # negative bars must use the series fill, not white
    run("roll_year_window.py")      # annual bar charts read the rolling window, not fixed years
    run("roll_line_windows.py")    # the 7 line charts read the shared rolling window too
    run("roll_single_year_charts.py")  # and the last 3, which each plot one year
    run("move_status_first.py")     # health banner leftmost; remaps every localSheetId
    run("drop_readme_sheet.py")     # READ_ME_FIRST merged into Status; remaps localSheetIds
    # AFTER the linked workbook exists — it is the source the frozen copy is made from.
    # Running it earlier meant consuming the PREVIOUS run's workbook (and failing outright
    # on a clean checkout, e.g. in CI).
    run("build_frozen_excel.py", os.path.join(OUT, "HourlyPowerData.xlsx"), os.path.join(OUT, "HourlyPowerData_frozen.xlsx"))
    run("build_deck.py", TEMPLATE, os.path.join(OUT, "HourlyPowerData.xlsx"), os.path.join(OUT, "HourlyPowerData.pptx"))
    # guard
    run("opc_validate.py")        # package joins: content-types, rel types, chart caches
    run("check_chart_quality.py")  # presentation faults that used to need a human to spot
    run("check_consistency.py")

    if DELIVER:
        import shutil
        dl = os.path.expanduser("~/Downloads")
        for f in ("HourlyPowerData.xlsx", "HourlyPowerData.pptx",
                  "HourlyPowerData_frozen.xlsx", "HourlyPowerData_snapshot.pptx"):
            shutil.copy(os.path.join(OUT, f), os.path.join(dl, f))
            print("  delivered", f)
    print("\n✅ generate complete — all outputs built & consistency-checked"
          + (" (fresh data)" if FRESH else "") + ".")

if __name__ == "__main__":
    main()
