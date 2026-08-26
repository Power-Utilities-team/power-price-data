"""check_house_palette.py — no chart may take its colours from the workbook theme.

WHY. Every chart in this workbook states its colours explicitly, bar one family: the hydro
reservoir band charts came from the tracker with their five year-lines on theme accents.
That looked harmless and was not. The workbook's own theme carries the Office 2007 defaults,
so in the file everyone downloads those eleven charts rendered in stock blue, red, green,
purple and orange while every other chart used the house palette.

It also made the file fragile in a way nothing else was: a chart on a theme colour changes
appearance when it is copied into a workbook with a different theme. That is exactly what
happened during the UpSlide merge on 2026-08-26, where the same eleven charts had to have
their accents resolved by hand, and where the accidental resolution put the current year's
line on the same colour as the band it sits inside.

WHAT IT CHECKS. The chart templates always, and the built workbook when there is one.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

import chartstyle as cs
import config as cfg

TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chart_templates")
BUILT = os.path.join(cfg.OUTPUT_DIR, "HourlyPowerData.xlsx")
THEME = re.compile(r'<a:schemeClr val="(accent\d|dk2|lt2)"')

# Everything the house palette sanctions, plus black, white and the greys the chrome uses.
ALLOWED = {c.lstrip("#").upper() for c in cs.PALETTE.values()} | {
    "000000", "FFFFFF", "595959", "666666", "808080", "D9D9D9", "BFBFBF", "E5E5E5",
    "F2F2F2", "A6A6A6", "7F7F7F", "404040", "262626", "3F3F3F",
}


def check():
    errs = []
    n_t = 0
    for name in sorted(os.listdir(TEMPLATES)):
        if not name.endswith(".xml"):
            continue
        n_t += 1
        x = open(os.path.join(TEMPLATES, name), encoding="utf-8").read()
        for m in set(THEME.findall(x)):
            errs.append(f"chart_templates/{name}: takes its colour from the theme "
                        f"({m}) — state it explicitly instead, so it renders the same "
                        f"in any workbook")
    n_c = 0
    if os.path.exists(BUILT):
        z = zipfile.ZipFile(BUILT)
        for n in z.namelist():
            if not re.match(r"xl/charts/chart\d+\.xml$", n):
                continue
            n_c += 1
            hits = set(THEME.findall(z.read(n).decode()))
            if hits:
                errs.append(f"{os.path.basename(n)}: takes its colour from the theme "
                            f"({', '.join(sorted(hits))})")
    print(f"house palette: {n_t} template(s) and {n_c} built chart(s) checked", flush=True)
    return errs


def main():
    errs = check()
    if errs:
        print("HOUSE PALETTE: FAIL", flush=True)
        for e in errs:
            print("  ✗", e, flush=True)
        print("\nA theme colour is not a colour, it is a reference. It changes when the\n"
              "workbook does, and it is why the hydro charts shipped in Office defaults.",
              flush=True)
        sys.exit(1)
    print("HOUSE PALETTE: PASS — every chart states its own colours", flush=True)


if __name__ == "__main__":
    main()
