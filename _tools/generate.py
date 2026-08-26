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


def run_node(script):
    """The public status page's suite, which is JavaScript rather than Python.

    SKIPPED, NOT FAILED, when node is absent. The page is a convenience that this build does
    not produce and cannot break: the Worker is deployed by hand with wrangler, and the
    deliverables reach people through raw URLs whether the page exists or not. Failing a data
    build because a JS runtime is missing would stop the pipeline for something downstream of
    it. CI's ubuntu runner ships node, so the guard does run where it matters.
    """
    import shutil
    node = shutil.which("node")
    if not node:
        print(f"\n$ {script} — SKIPPED, no node on PATH", flush=True)
        return
    print(f"\n$ node {script}", flush=True)
    subprocess.run([node, os.path.join(TOOLS, "refresh-page", script)],
                   cwd=os.path.join(TOOLS, "refresh-page"), check=True)


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

def unit_suites():
    """The suites that need no data, run on EVERY build including CI's.

    THEY LIVED IN THE `--fresh` BRANCH UNTIL 2026-08-26 AND CI DOES NOT PASS `--fresh`.
    So the whole set was wired in that morning, declared to be running, and ran nowhere:
    the workflow calls a bare `python generate.py`. That is the same fault as the one the
    block was written to fix, one level up — a suite nothing invokes is documentation, and
    a suite invoked on a branch nobody takes is worse, because it looks invoked.

    Nothing here reads data/, published/ or outputs/, so there is no reason to gate them.
    The guards that DO compare against built data stay in the fresh branch, and CI runs
    those as their own workflow steps.
    """
    # FIRST, and the cheapest: the only one that reads every module. It exists because
    # fetch.py used datetime and timezone without importing them, in a branch that runs
    # only when a fetch comes back partial, so the gaps record that drives both the repair
    # run and the public page's "which series is behind" had never once been written.
    run("undefined_names_test.py")
    run("windows_test.py")
    run("chunked_test.py")
    run("fetch_retry_test.py")
    run("crossborder_test.py")
    run("status_health_test.py")
    # Great Britain's own failure path, which until 2026-08-26 did not exist. fetch_uk
    # swallowed every exception and returned None, so a total Elexon outage exited 0, wrote
    # no gaps record, and published stored data of any age with nothing saying so.
    run("fetch_uk_gaps_test.py")
    # A guard cannot notice that it has stopped guarding, which is what fixtures are for.
    run("check_reference_stability_fixtures.py")
    # The public status page. Its own suite ran nowhere for a month while the page quietly
    # promised every visitor that a refresh takes "about 20 minutes", two to three times
    # short once Great Britain and the whole-year pull landed.
    run_node("page_test.mjs")
    # page_test asks whether the page is RIGHT. This one asks whether it survives being
    # WRONG: an unparseable Origin (which returned HTTP 500 from the live Worker), a
    # cancelled run, a failed run, GitHub answering 401/403/500, a missing status record.
    run_node("page_break_test.mjs")


def main():
    unit_suites()
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
        # At the January rollover, fold the completed year into the frozen history first,
        # or the incremental build silently loses it. CI has always done this; a local run
        # did not, which is two specifications of one pipeline.
        run("build_hourly.py", "--absorb-prior-year")
        run("build_hourly.py")
        run("summaries.py")
        # chart_csv BEFORE extra_summaries, corrected 2026-08-25. extra_summaries ends by
        # building line_windows, which READS the fig2, fig3 and fig4 CSVs that chart_csv
        # writes — so in the old order it always built that table from the PREVIOUS run's
        # files. Harmless while the columns never changed, and not harmless the moment
        # they did: a newly added country's columns did not exist in last run's CSVs, so
        # its window came out empty and its charts drew nothing, with every downstream
        # check passing because the columns were present and the right width.
        run("export_csv.py")          # tidy/long CSVs, the published/ root set
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
        # Refuse to publish a layout that MOVED existing data. Charts address their
        # data by absolute column and row, so an inserted column repoints every chart to
        # its right while leaving a perfectly valid file that every other check passes.
        # Runs BEFORE the copy, while published/ still holds the good baseline.
        # THE FIXTURES RUN FIRST, LOCALLY TOO. CI has always run them; a local build did
        # not, so a change that disconnected the guard from its own fixtures passed every
        # local check and only failed once it reached CI. A guard cannot notice that it
        # has stopped guarding, which is the entire reason it has fixtures.
        # THE UNIT SUITES RUN HERE, because until 2026-08-26 they ran NOWHERE. Three
        # suites existed and were cited as evidence the pipeline was robust, and not one
        # was executed by any workflow: they passed only when someone remembered to run
        # them by hand. Not a theoretical gap - adding the concurrent border fetch broke
        # fetch_retry_test on its first attempt, and that was caught only because it
        # happened to be run by hand that minute. A suite nothing runs is documentation.
        # FIRST, because it is the cheapest and the only one that reads every module. It
        # exists because fetch.py used datetime and timezone without importing them, in a
        # branch that runs only when a fetch comes back partial, so the gaps record that
        # drives both the repair run and the public page's "which series is behind" had
        # never once been written. Import, ast.parse and the consumer's own suite all
        # passed throughout.
        # The public status page's own suite, which until 2026-08-26 also ran nowhere. It
        # caught nothing for a month because nothing invoked it, while the page quietly
        # promised every visitor a refresh would take "about 20 minutes" — a figure that
        # was two to three times short once Great Britain and the whole-year pull landed.
        run("check_reference_stability.py")
        # And refuse to publish a SHORTER series. check_coverage ran only in CI until
        # 2026-08-25, so a local --fresh run could and did overwrite the tracked baseline
        # with a month less data while every local check passed.
        run("check_coverage.py")
        # The legacy five and the "_extra" sixth come from different sources with
        # independent failure modes, so they can drift apart while both stay individually
        # valid. Nothing else compares them to each other.
        run("check_split_parity.py")
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
    # NAME THE REPO WE ACTUALLY PUBLISH TO. add_power_queries writes only its own target tabs;
    # the twelve legacy queries are inherited from the base workbook and still named the
    # pre-transfer personal account. They resolve solely through GitHub's transfer redirect,
    # which ends the moment that freed username is registered and given a repo of the same
    # name: the workbook would then pull a stranger's data, with no error and no visible
    # change. Runs on every build, so an inherited URL cannot survive a rebuild.
    run("repoint_workbook.py", os.path.join(OUT, "HourlyPowerData.xlsx"), "--apply", "--in-place")
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
    # build_frozen_excel hardcodes the query tabs; this removes the remaining dependence
    # on a reader whose Excel recalculates, which is what "self-contained" has to mean.
    run("bake_frozen_values.py")
    run("build_deck.py", TEMPLATE, os.path.join(OUT, "HourlyPowerData.xlsx"), os.path.join(OUT, "HourlyPowerData.pptx"))
    # guard
    # THE FIXTURES FIRST, as with the stability guard. opc_validate's schema checks were
    # added after a CI run died at the Windows validate leg on faults every local check
    # had passed; they are worth what the evidence that they still fire is worth.
    # And prove it stuck, on both deliverables. The repoint above runs before the frozen copy
    # is derived, so a failure here means something re-introduced an old owner downstream.
    run("repoint_workbook.py", os.path.join(OUT, "HourlyPowerData.xlsx"), "--check")
    run("repoint_workbook.py", os.path.join(OUT, "HourlyPowerData_frozen.xlsx"), "--check")
    run("opc_validate_fixtures.py")
    run("opc_validate.py")        # package joins: content-types, rel types, chart caches
    run("check_chart_quality.py")  # presentation faults that used to need a human to spot
    # Does the chart captioned "X" actually plot X's data? Every other guard here is
    # positional; this is the only one that asks what a chart MEANS, and it exists
    # because four charts captioned "United Kingdom" shipped plotting Spain and France.
    run("check_chart_captions.py")
    # And the converse question, which nothing here asked until 2026-08-26: did this build
    # TAKE SOMETHING AWAY? Adding the GB price-basis caveat deleted the y-axis label from
    # charts 1, 3 and 16, because a chart title and an axis title are both <c:title> and the
    # code removed the first one it found. Every check above passed, because every check
    # above asks whether the change added what it meant to add.
    run("check_chart_preservation.py")
    # Every chart states its own colours. The hydro band charts came from the
    # tracker on theme accents, so in the published workbook they rendered in Office
    # defaults while everything else used the house palette, and they changed
    # appearance again when copied into a workbook with a different theme.
    run("check_house_palette.py")
    run("check_consistency.py")

    # ---- the UpSlide-linked deliverable ---------------------------------------------
    # The copy Power & Utilities link into PowerPoint cannot be a freshly generated file.
    # UpSlide matches its links by a hidden marker stamped into each chart, not by path, so
    # a rebuild orphans every link in the deck. merge_into_linked.py adds this build's new
    # content to the linked workbook instead of replacing it.
    #
    # SKIPPED WHEN THERE IS NO TEMPLATE, which is the normal case in CI. The template is the
    # linked workbook itself, and that file is classified internal by the firm's own
    # Microsoft labelling and names a colleague, a file server and two paths to a shared
    # deck, so it is not in this repository and .gitignore refuses it. Point UPSLIDE_TEMPLATE
    # at it to build the linked deliverable on a machine that has it.
    tmpl = os.environ.get("UPSLIDE_TEMPLATE", "")
    if not tmpl:
        print("$ (no UPSLIDE_TEMPLATE set - skipping the linked deliverable)", flush=True)
    elif not os.path.exists(tmpl):
        raise SystemExit(f"UPSLIDE_TEMPLATE is set to {tmpl!r}, which does not exist")
    else:
        run("merge_into_linked.py", "--base", tmpl,
            "--donor", os.path.join(OUT, "HourlyPowerData.xlsx"),
            "--out", os.path.join(OUT, "HourlyPowerData_linked.xlsx"))

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
