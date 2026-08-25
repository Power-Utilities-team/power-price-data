"""
check_reference_stability.py — refuse to publish a layout that MOVED existing data.

THE FAULT THIS EXISTS TO CATCH. Every chart in the delivered workbook addresses its data
by absolute position: a column letter and a row number into a tab that Power Query loads
from a published CSV. Nothing in the file records which SERIES a reference was meant to
mean. So if a column is inserted rather than appended, every column to its right shifts
one place and every chart reading them silently starts plotting its neighbour. The file
stays valid, the tables stay the right width, every existing check passes, and the charts
are simply wrong under the right titles.

That is not hypothetical. It is what un-curated chart12 on 2026-07-22, found only because
someone looked at it. The existing guards do not cover it: `check_consistency` verifies
that ranges do not run PAST the pre-filled data, which is a different question, and
`check_coverage` verifies that no series got SHORTER. A column that moved sideways is
neither.

WHAT IT COMPARES. The freshly built CSVs in outputs/ against the currently published ones,
which is the baseline the live workbooks in the wild are pointed at. For every file that
exists in both:

  * every column that existed before must still be at the same index;
  * every row label that existed before must still be on the same row;
  * appending new columns or rows at the end is fine, and is the sanctioned way to add
    a country, a technology or a year.

It says nothing about files that are new, which is the whole point of the append rule.

WHERE IT RUNS. Before the publish step, so a bad layout is refused while the published
copy is still the good one. Running it after publishing would compare the new files with
themselves and pass every time.

Exit 0 = safe to publish; exit 1 = something moved, with the file and index named.
"""
from __future__ import annotations

import csv
import os
import sys

import config as cfg

NEW = os.path.join(cfg.OUTPUT_DIR, "csv", "charts")
BASELINE = os.path.join(cfg.ROOT, "published", "charts")

# THE BASELINE IS GIT HEAD, NOT THE WORKING TREE. published/ is a tracked directory that
# a local `generate.py --fresh` overwrites in place, so comparing against it compares the
# new build with a copy of itself and passes anything. That is not hypothetical: on
# 2026-08-25 a change inserted a column mid-table and shifted 132 others, and this guard
# passed it, because an earlier local publish had already replaced the baseline. The
# committed copy is the one every workbook in the wild actually loads.
USE_GIT_BASELINE = True

# filename -> which published/ subdirectory it lives in ("" = the root set)
_WHERE = {}

# Files whose first column is a ROW LABEL that charts address by position (a technology
# name, a month, a week). For these the row identity is checked as well as the columns.
ROW_ADDRESSED = {
    "fig5_capture_pct.csv", "fig5_capture_abs.csv", "fig5_capture_window.csv",
    "fig9_capacity.csv", "fig9_capacity_window.csv",
    "capture_monthly.csv", "capture_monthly_extra.csv",
    "line_windows.csv", "hydro_window.csv", "hydro_reservoir.csv",
    # Added 2026-08-25 after review: these have a positional first column too (hour,
    # percentile, day-of-year, month, date) that charts address by row number, so a
    # leap-year or timezone shift would move them and pass unnoticed.
    "fig2_intraday_indexed.csv", "fig2_intraday_avg.csv", "fig4_duration_curve.csv",
    "fig6_daily_minmax.csv", "fig7_gen_mix.csv", "figA_monthly_price.csv",
    "figB_penetration.csv", "figC_capture_erosion.csv", "figD_netload_duck.csv",
    "fig1_price_sd.csv", "fig3_neg_hours_annual.csv", "fig3_cum_near_neg.csv",
}


def _read_rows(text):
    rows = list(csv.reader(text.splitlines()))
    return (rows[0] if rows else []), [r[0] if r else "" for r in rows]


def _read(path):
    with open(path, encoding="utf-8") as f:
        return _read_rows(f.read())


def _git_baseline():
    """{filename: text} for published/charts at HEAD, or None if git cannot answer."""
    import subprocess
    try:
        listing = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "HEAD", "published/"],
            cwd=cfg.ROOT, capture_output=True, text=True, check=True).stdout.split()
    except Exception:                             # noqa: BLE001 - not a git checkout
        return None
    out = {}
    for path in listing:
        if not path.endswith(".csv"):
            continue
        _WHERE[os.path.basename(path)] = "charts" if "/charts/" in path else ""
        try:
            out[os.path.basename(path)] = subprocess.run(
                ["git", "show", f"HEAD:{path}"], cwd=cfg.ROOT,
                capture_output=True, text=True, check=True).stdout
        except Exception:                         # noqa: BLE001
            continue
    return out


def check():
    git = _git_baseline() if USE_GIT_BASELINE else None
    if git:
        source, names = "git HEAD", sorted(git)
    elif os.path.isdir(BASELINE):
        source = "the working tree (git baseline unavailable — a local publish may " \
                 "already have overwritten it)"
        names = sorted(n for n in os.listdir(BASELINE) if n.endswith(".csv"))
    else:
        print("no published baseline yet — nothing to compare against", flush=True)
        return []
    errs = []
    compared = widened = 0
    for name in names:
        if not name.endswith(".csv"):
            continue
        # published/ has two levels: charts/ (what the workbook loads) and a root set of
        # tidy long-form CSVs. Both are served over the network, so both are guarded —
        # the root ten were unchecked until 2026-08-25.
        sub = _WHERE.get(name, "charts")
        base_p = os.path.join(cfg.ROOT, "published", sub, name) if sub else \
            os.path.join(cfg.ROOT, "published", name)
        new_p = os.path.join(cfg.OUTPUT_DIR, "csv", sub, name) if sub else \
            os.path.join(cfg.OUTPUT_DIR, "csv", name)
        if not os.path.exists(new_p):
            # A published file the build no longer produces would be left stale on the
            # raw-URL surface for ever, still being loaded by every workbook in the wild.
            errs.append(f"{name}: is published but is no longer built — the stale copy "
                        f"would keep being served to every open workbook")
            continue
        compared += 1
        bh, bcol0 = _read_rows(git[name]) if git else _read(base_p)
        nh, ncol0 = _read(new_p)

        for i, col in enumerate(bh):
            if i >= len(nh):
                errs.append(f"{name}: column {i} {col!r} has been dropped "
                            f"(width {len(bh)} -> {len(nh)})")
                break
            if nh[i] != col:
                errs.append(f"{name}: column {i} was {col!r} and is now {nh[i]!r} — "
                            f"every chart reading it now plots a different series")
                break
        if len(nh) > len(bh) and not errs:
            widened += 1

        if name in ROW_ADDRESSED:
            for i, label in enumerate(bcol0):
                if i >= len(ncol0):
                    errs.append(f"{name}: row {i + 1} {label!r} has been dropped")
                    break
                if ncol0[i] != label:
                    errs.append(f"{name}: row {i + 1} was {label!r} and is now "
                                f"{ncol0[i]!r} — a chart addressing that row now reads "
                                f"a different one")
                    break
    print(f"reference stability: compared {compared} file(s) against {source}, "
          f"{widened} widened by appending", flush=True)
    return errs


def main():
    errs = check()
    if errs:
        print("REFERENCE STABILITY: FAIL", flush=True)
        for e in errs:
            print("  ✗", e, flush=True)
        print("\nA moved column or row does not shorten anything and does not break the\n"
              "package, so no other check sees it. Add new columns and rows at the END.",
              flush=True)
        sys.exit(1)
    print("REFERENCE STABILITY: PASS — every existing column and row is where it was",
          flush=True)


if __name__ == "__main__":
    main()
