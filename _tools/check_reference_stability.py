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

# Files whose first column is a ROW LABEL that charts address by position (a technology
# name, a month, a week). For these the row identity is checked as well as the columns.
ROW_ADDRESSED = {
    "fig5_capture_pct.csv", "fig5_capture_abs.csv", "fig5_capture_window.csv",
    "fig9_capacity.csv", "fig9_capacity_window.csv",
    "capture_monthly.csv", "capture_monthly_extra.csv",
    "line_windows.csv", "hydro_window.csv", "hydro_reservoir.csv",
}


def _read(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    return (rows[0] if rows else []), [r[0] if r else "" for r in rows]


def check():
    if not os.path.isdir(BASELINE):
        print("no published baseline yet — nothing to compare against", flush=True)
        return []
    errs = []
    compared = widened = 0
    for name in sorted(os.listdir(BASELINE)):
        if not name.endswith(".csv"):
            continue
        base_p, new_p = os.path.join(BASELINE, name), os.path.join(NEW, name)
        if not os.path.exists(new_p):
            # A published file the build no longer produces would be left stale on the
            # raw-URL surface for ever, still being loaded by every workbook in the wild.
            errs.append(f"{name}: is published but is no longer built — the stale copy "
                        f"would keep being served to every open workbook")
            continue
        compared += 1
        bh, bcol0 = _read(base_p)
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
    print(f"reference stability: compared {compared} published file(s), "
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
