"""coverage_eyeball.py — render what the coverage guard is counting, so it can be SEEN.

check_coverage.py answers "did anything shrink" in numbers. This answers "does the
published year look complete" in a picture, which is a different and cheaper kind of
check: the 2026-07-31 collapse was invisible to every data validator and would have been
obvious in one glance at a coverage strip that stopped on 31 January.

Deliberately reads published/ — the CSVs Excel actually loads — and not the parquet or
the workbook, because published/ is what a reader ends up looking at.

    python _tools/coverage_eyeball.py [--out outputs/coverage.png]
"""
from __future__ import annotations

import argparse
import csv
import os
import re
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

import config as cfg

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUB = os.path.join(ROOT, "published")
COUNTRIES = list(cfg.COUNTRY_ORDER)   # every market, not the original five


def read(rel):
    with open(os.path.join(PUB, rel), newline="") as fh:
        rows = list(csv.reader(fh))
    return [h.strip() for h in rows[0]], rows[1:]


def daily_grid():
    """country x day-of-year presence for the current year, from daily_minmax."""
    hdr, rows = read("daily_minmax.csv")
    ci, yi, di = hdr.index("country"), hdr.index("year"), hdr.index("date")
    year = max(int(r[yi]) for r in rows if r and r[yi].strip())
    grid = np.zeros((len(COUNTRIES), 366))
    import datetime as dt
    for r in rows:
        if not r or int(r[yi]) != year or r[ci] not in COUNTRIES:
            continue
        d = dt.date.fromisoformat(r[di][:10])
        grid[COUNTRIES.index(r[ci]), d.timetuple().tm_yday - 1] = 1
    return year, grid


def year_columns(rel, pattern):
    """{year: {country: populated_cells}} for a wide per-year chart CSV."""
    hdr, rows = read(rel)
    out = defaultdict(lambda: defaultdict(int))
    for i, h in enumerate(hdr):
        m = pattern.match(h)
        if not m:
            continue
        c, y = m.group("c"), int(m.group("y"))
        for r in rows:
            if i < len(r) and r[i].strip():
                out[y][c] += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "outputs", "coverage.png"))
    args = ap.parse_args()

    year, grid = daily_grid()
    fig, axes = plt.subplots(3, 1, figsize=(13, 9),
                             gridspec_kw={"height_ratios": [1, 1.1, 1.1]})

    ax = axes[0]
    ax.imshow(grid, aspect="auto", cmap="Greens", vmin=0, vmax=1,
              extent=[1, 366, len(COUNTRIES) - 0.5, -0.5], interpolation="nearest")
    ax.set_yticks(range(len(COUNTRIES)))
    ax.set_yticklabels(COUNTRIES)
    ax.set_xlabel("day of year")
    ax.set_title(f"daily_minmax.csv — {year} coverage by country "
                 f"(filled = a day is present)", loc="left", fontsize=11)
    last = int(grid.sum(axis=1).max())
    ax.axvline(last, color="crimson", lw=1.2, ls="--")
    ax.text(last + 4, 0.2, f"{last} days", color="crimson", fontsize=9, va="center")

    # fig3 is FIXED-SHAPE: a collapse here blanks cells and never moves a row, which is
    # exactly why the row-count check alone would have missed the 2026-07-31 bug.
    for ax, (rel, pat, note) in zip(axes[1:], [
        ("charts/fig3_cum_near_neg.csv",
         re.compile(r"^(?P<c>[A-Z]{2})_(?P<y>\d{4})$"),
         "fixed-shape: 366 rows always, so a collapse shows only as blanks"),
        ("charts/fig7_gen_mix.csv",
         re.compile(r"^(?P<c>[A-Z]{2})_(?P<y>\d{4})_.+$"),
         "the feed that actually broke on 2026-07-31 (480 cells -> 48)"),
    ]):
        data = year_columns(rel, pat)
        years = sorted(data)
        w = 0.15
        for k, c in enumerate(COUNTRIES):
            vals = [data[y].get(c, 0) for y in years]
            ax.bar([i + k * w for i in range(len(years))], vals, w, label=c)
        ax.set_xticks([i + 2 * w for i in range(len(years))])
        ax.set_xticklabels(years)
        ax.set_ylabel("populated cells")
        ax.set_title(f"{rel} — {note}", loc="left", fontsize=11)
        ax.set_ylim(0, max(max(v.values()) for v in data.values()) * 1.28)
        ax.legend(ncol=5, fontsize=8, frameon=False, loc="upper left")

    fig.suptitle("Published coverage — what check_coverage.py counts, drawn",
                 x=0.005, ha="left", fontsize=13, weight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.97])
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    fig.savefig(args.out, dpi=130)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
