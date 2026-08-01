"""
check_coverage.py — published data may never quietly SHRINK.

Every other check in this repo asks "is this data valid?". This one asks "is this the
data we already had, plus more?" — and it exists because on 2026-07-31 the answer was no
and nothing noticed. The incremental fetch ran on a cold cache, pulled 30 days, merged
them into nothing, and published a 31-day "year" where 212 days belonged. The run was
FAST and GREEN. Every validator passed, correctly: a 31-day series is perfectly valid
data. It is just the wrong data.

`check_no_future_data` looks for coverage extending too FAR. Nothing looked for coverage
that had quietly retreated. This does.

TWO measures, because one of them alone would have missed the bug that motivated it:

  * ROW COUNT, per file. Catches the tidy/long feeds — daily_minmax, cum_neghours,
    duration_curve, capture_monthly — which really do lose rows when coverage shrinks.

  * POPULATED CELLS, per COLUMN. The wide chart CSVs that Excel actually loads are
    FIXED-SHAPE: fig3_cum_near_neg is always 366 rows (day-of-year), fig5_capture_abs is
    always 25 (years to DISPLAY_END_YEAR). A coverage collapse there does not remove a
    single row — it blanks cells inside the year's column and the row count never moves.
    Measured on the 2026-07-31 refresh commits: 595 lines added, 595 deleted, identical
    totals. A row-count check would have signed the bug off.

Per COLUMN, not per file, is what makes the signal legible. Collapsing DE_2026 from 212
populated days to 31 is an 85% drop in that column but only ~6% of the file — under any
tolerance loose enough to survive a normal month. Per column it is unmissable, and it
also survives the January rollover for free: a year column that gains its first value has
no baseline to compare against, so it simply is not compared.

Baseline is git, not a stored manifest: whatever the previous commit published IS the
claim we are defending. That means this works identically in CI (where the publish job
has main checked out and the fresh CSVs laid over it) and on a laptop against the working
tree.

Exit 0 = coverage held or grew; exit 1 = something shrank.
"""
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLISHED = os.path.join(ROOT, "published")

# A drop is tolerated only if it clears BOTH bars. The absolute floor keeps a narrow
# column — a month-granularity year with 7 points — from tripping on a single ENTSO-E
# revision; the percentage keeps a wide one from hiding a real collapse behind it.
# Neither is tuned to the 2026-07-31 bug, which was -85% and would fail any setting.
TOLERANCE_PCT = 2.0
TOLERANCE_ABS = 3


def git_show(ref: str, relpath: str) -> str | None:
    """File contents at `ref`, or None if it did not exist there."""
    p = subprocess.run(["git", "show", f"{ref}:{relpath}"],
                       cwd=ROOT, capture_output=True, text=True)
    return p.stdout if p.returncode == 0 else None


def measure(text: str):
    """(data_row_count, {column_name: populated_cell_count}).

    Populated means a non-blank cell after stripping. Blank is exactly how a shrunken
    year shows up in a fixed-shape chart CSV, so it is the thing being counted.
    """
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return 0, {}
    header = [h.strip() for h in rows[0]]
    counts = {h: 0 for h in header}
    n = 0
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue                      # trailing blank line, not a data row
        n += 1
        for i, cell in enumerate(r):
            if i < len(header) and cell.strip():
                counts[header[i]] += 1
    return n, counts


SLOT_RE = re.compile(r"^(.*_|)w(\d+)$")


def window_base(text: str | None) -> int | None:
    """The year in slot w1, read from published/charts/status.csv.

    The rolling-window charts read fixed column POSITIONS whose MEANING advances each
    January: `DE_w1` is 2019 today and 2020 from the first 2027 refresh. Slot 8 of
    line_windows is the current year-to-date, so at the rollover it goes from a complete
    365-day year to a two-day one — a 99% "drop" that is entirely correct, on the one
    unattended run of the year where a false failure would cost the most.

    So the shift has to be detected and compensated, not tolerated. status.csv publishes
    the slot labels, which makes it cheap: compare w1 before and after.
    """
    if text is None:
        return None
    rows = list(csv.reader(io.StringIO(text)))
    if len(rows) < 2:
        return None
    header = [h.strip() for h in rows[0]]
    if "w1" not in header:
        return None
    try:
        return int(rows[1][header.index("w1")].strip())
    except (ValueError, IndexError):
        return None


def baseline_column(col: str, shift: int) -> str:
    """The column in the OLD tree that holds what `col` holds in the new one."""
    if shift <= 0:
        return col
    m = SLOT_RE.match(col)
    if not m:
        return col
    return f"{m.group(1)}w{int(m.group(2)) + shift}"


def shrank(now: int, before: int) -> bool:
    """True if `now` is a drop from `before` beyond both tolerances."""
    if now >= before:
        return False
    drop = before - now
    return drop > TOLERANCE_ABS and (drop / before) * 100 > TOLERANCE_PCT


def published_csvs() -> list[str]:
    out = []
    for dirpath, _dirs, files in os.walk(PUBLISHED):
        for fn in files:
            if fn.endswith(".csv"):
                full = os.path.join(dirpath, fn)
                out.append(os.path.relpath(full, ROOT))
    return sorted(out)


def baseline_csvs(ref: str) -> set[str]:
    """Every published CSV that existed at `ref`."""
    p = subprocess.run(["git", "ls-tree", "-r", "--name-only", ref, "published/"],
                       cwd=ROOT, capture_output=True, text=True)
    return {ln for ln in p.stdout.split() if ln.endswith(".csv")}


def check(ref: str):
    errs, notes = [], []

    status = os.path.join("published", "charts", "status.csv")
    now_base = window_base(open(os.path.join(ROOT, status)).read()
                           if os.path.exists(os.path.join(ROOT, status)) else None)
    old_base = window_base(git_show(ref, status))
    shift = (now_base - old_base) if (now_base and old_base) else 0
    if shift > 0:
        notes.append(f"rolling window advanced {shift} year(s) ({old_base} -> {now_base}) "
                     f"— slot columns compared against their previous position")
    elif shift < 0:
        # The window only ever moves forward. Backwards means the build read a stale or
        # truncated history, which is the same class of fault as a shrunken feed.
        errs.append(f"{status}: the rolling window moved BACKWARDS, {old_base} -> "
                    f"{now_base}. The slot labels only ever advance")
        shift = 0

    # A feed that vanishes is the largest possible shrink, and walking only the current
    # tree would never see it.
    current = set(published_csvs())
    for rel in sorted(baseline_csvs(ref) - current):
        errs.append(f"{rel}: published feed has DISAPPEARED since {ref}")

    for rel in published_csvs():
        base = git_show(ref, rel)
        if base is None:
            notes.append(f"{rel}: new feed, no baseline at {ref}")
            continue
        with open(os.path.join(ROOT, rel), newline="") as fh:
            now_text = fh.read()

        now_rows, now_cols = measure(now_text)
        old_rows, old_cols = measure(base)

        row_loss = max(0, old_rows - now_rows)
        if shrank(now_rows, old_rows):
            errs.append(f"{rel}: {old_rows} data rows -> {now_rows} ({row_loss} lost)")

        matched = set()
        for col, now_n in now_cols.items():
            src = baseline_column(col, shift)
            if src not in old_cols:
                notes.append(f"{rel}: column {col!r} has no baseline — not compared")
                continue
            matched.add(src)
            old_n = old_cols[src]
            loss = old_n - now_n
            # In a long feed every column loses exactly the rows the file lost, so
            # listing them all restates one fact seven times. Only report a column that
            # lost MORE than the rows did — that is the fixed-shape case, where cells
            # were blanked in place and the row count never moved.
            if loss <= row_loss or not shrank(now_n, old_n):
                continue
            label = repr(col) if src == col else f"{col!r} (was {src})"
            errs.append(f"{rel}: column {label} {old_n} populated -> {now_n} "
                        f"({loss} lost)")

        # A column name vanishing from the header is always a regression. Under a shift
        # the OLDEST slot legitimately has no successor, but its NAME is still present —
        # so this only fires when the header itself lost a field.
        for col in old_cols:
            if col not in matched and col not in now_cols:
                errs.append(f"{rel}: column {col!r} has disappeared")
    return errs, notes


def month_start(y: int, m: int) -> str:
    return f"{y:04d}-{m:02d}-01"


def prev_month(y: int, m: int) -> tuple[int, int]:
    return (y - 1, 12) if m == 1 else (y, m - 1)


def check_month_arrived():
    """The month that has just ended must be PRESENT in the monthly exhibits.

    The shrink check above cannot see this. A month that never arrives is not a shrink —
    last month's feed ended in June and this month's also ends in June, so nothing got
    smaller and the gate passes. Absence and shrinkage are different failures.

    It matters because of how the month gate works: a month counts complete only once
    coverage passes its final hour, so a run soon after the month boundary that meets a
    late ENTSO-E publication produces a SUCCESSFUL run which silently omits the month
    from every monthly exhibit — for a further month, until the next scheduled run. Green
    run, wrong data, which is this project's recurring failure and the reason the
    schedule sits on the 2nd rather than the 1st.

    Detected structurally rather than from a hardcoded list: a monthly feed is one whose
    first column is `date` and whose every value is the first of a month. That
    deliberately excludes capture_monthly, which is keyed `month` and is NOT gated on
    completeness — it carries the running partial month and would fail this assertion
    every time.

    A 24-hour grace after the month boundary keeps an ad-hoc dispatch in the first hours
    of a month from failing on a month that genuinely has not closed yet.
    """
    import datetime as dt

    errs, notes = [], []
    status_path = os.path.join(PUBLISHED, "charts", "status.csv")
    if not os.path.exists(status_path):
        return errs, ["no status.csv — month-arrival check skipped"]
    rows = list(csv.reader(open(status_path, newline="")))
    if len(rows) < 2:
        return errs, ["status.csv has no data row — month-arrival check skipped"]
    hdr = [h.strip() for h in rows[0]]
    if "generated_utc" not in hdr:
        return errs, ["status.csv has no generated_utc — month-arrival check skipped"]
    gen = dt.datetime.fromisoformat(rows[1][hdr.index("generated_utc")].strip())

    start_of_month = gen.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if (gen - start_of_month) < dt.timedelta(hours=24):
        return errs, [f"only {gen - start_of_month} into {gen:%B %Y} — month-arrival "
                      f"check skipped (the month just turned)"]

    want_y, want_m = prev_month(gen.year, gen.month)
    want = month_start(want_y, want_m)

    for rel in published_csvs():
        with open(os.path.join(ROOT, rel), newline="") as fh:
            r = list(csv.reader(fh))
        if len(r) < 2 or not r[0] or r[0][0].strip().lower() != "date":
            continue
        dates = [x[0].strip() for x in r[1:] if x and x[0].strip()]
        if not dates or not all(re.match(r"\d{4}-\d{2}-01$", d) for d in dates):
            continue                      # not a monthly-axis feed
        populated = [x[0].strip() for x in r[1:]
                     if x and x[0].strip() and any(c.strip() for c in x[1:])]
        if not populated:
            errs.append(f"{rel}: monthly feed is entirely empty")
            continue
        if populated[-1] < want:
            errs.append(f"{rel}: ends {populated[-1]} but {want_y}-{want_m:02d} has "
                        f"closed — the month did not arrive")
    if not errs:
        notes.append(f"month-arrival: {want_y}-{want_m:02d} present in every monthly feed")
    return errs, notes


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", default="HEAD",
                    help="git ref to compare published/ against (default HEAD)")
    args = ap.parse_args()

    if not os.path.isdir(PUBLISHED):
        print(f"COVERAGE: no published/ directory at {PUBLISHED}")
        sys.exit(1)

    errs, notes = check(args.baseline)
    m_errs, m_notes = check_month_arrived()
    errs += m_errs
    notes += m_notes
    for n in notes:
        print("  ·", n)
    if errs:
        print(f"COVERAGE: FAIL — published data shrank against {args.baseline}, or a "
              f"closed month is missing ({len(errs)} findings)")
        for e in errs[:25]:
            print("  ✗", e)
        if len(errs) > 25:
            print(f"  … and {len(errs) - 25} more")
        print("\nA shorter series is still VALID data, which is why nothing else catches "
              "this.\nIf the drop is genuine, re-run with full_refetch=true and confirm "
              "the source,\nrather than loosening the tolerance.")
        sys.exit(1)
    print(f"COVERAGE: PASS — no published feed shrank against {args.baseline} "
          f"({len(published_csvs())} files, tolerance {TOLERANCE_PCT}% / "
          f"{TOLERANCE_ABS} cells).")


if __name__ == "__main__":
    main()
