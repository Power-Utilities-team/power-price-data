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

def main():
    if FRESH:
        yr = date.today().year
        run("fetch.py", "--years", f"{yr-1},{yr}", "--force")
        run("build_hourly.py")
        run("summaries.py")
        run("extra_summaries.py")
        run("chart_csv.py")
        run("build_status.py")
    # static path (fresh data)
    run("render_all.py")
    run("build_static_deck.py", os.path.join(OUT, "HourlyPowerData_snapshot.pptx"))
    # linked path (rebuild workbook + deck)
    run("add_phase4_charts.py")
    run("curate_tech_charts.py")    # curated technology sets (note Figs 5/47, 50, 7)
    run("add_status_sheet.py")      # staleness banner (workbook opens on it)
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
