"""Assert the chart-presentation faults found on 2026-07-30/31, so they cannot return.

WHY THIS EXISTS
    Every one of these was found by opening the workbook and looking at it — expensive,
    manual, and it needs Excel in the foreground. But every one of them is also visible
    in the chart XML, which needs nothing at all. Each defect below cost real time to
    find; none of them should ever need finding twice.

    That matters beyond tidiness: LibreOffice is not a safe stand-in for Excel here. It
    rendered Fig 5 with no bars and a "Column B, Column C" legend for a workbook Excel
    opened perfectly. So the choice is not "screenshot or nothing" — it is "assert the
    property directly, or be misled by whichever renderer you happened to use".

WHAT IT CHECKS
    1. invertIfNegative — draws negative bars in an inverted (white) fill, so on Fig 5
       every technology capturing below baseload rendered as a hollow outline.
    2. tickLblPos on a category axis — "nextTo" puts labels at the axis line, which sits
       mid-plot when there are negatives, printing them across the bars.
    3. one colour per year — colours were assigned by series POSITION, and bar charts
       have one fewer series than line charts, so every year was a different colour
       between exhibits.
    4. exactly one selected sheet — two make Excel open the file GROUPED, which applies
       every edit to all of them and blocks table edits outright.
    5. cached series names — a strCache claiming points but holding none is invalid.
"""
from __future__ import annotations

import os
import re
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WB = os.path.join(ROOT, "outputs", "HourlyPowerData.xlsx")


def charts(z):
    for n in sorted(z.namelist()):
        if re.match(r"xl/charts/chart\d+\.xml$", n):
            yield n, z.read(n).decode()


def series_of(xml):
    return re.findall(r"<c:ser>.*?</c:ser>", xml, re.S)


def check(path):
    errs = []
    z = zipfile.ZipFile(path)

    # 1 + 2 + 5 --------------------------------------------------------------------
    for n, x in charts(z):
        base = os.path.basename(n)
        if '<c:invertIfNegative val="1"/>' in x:
            errs.append(f"{base}: invertIfNegative=1 — negative bars will draw hollow")
        for ax in re.findall(r"<c:catAx>.*?</c:catAx>", x, re.S):
            if '<c:tickLblPos val="nextTo"/>' in ax:
                errs.append(f"{base}: category tickLblPos=nextTo — labels sit on the "
                            f"axis line, which is mid-plot when values go negative")
        for cache in re.findall(r"<c:strCache>.*?</c:strCache>", x, re.S):
            m = re.search(r'<c:ptCount val="(\d+)"/>', cache)
            if m and int(m.group(1)) > 0 and "<c:pt " not in cache:
                errs.append(f"{base}: a strCache claims {m.group(1)} point(s) but holds "
                            f"none — Excel will offer to Recover")

    # 3 ----------------------------------------------------------------------------
    year_colour = {}
    for n, x in charts(z):
        base = os.path.basename(n)
        for s in series_of(x):
            # Tempered so the match cannot leave <c:tx> (2026-08-03). With a plain `.*?`
            # this ran past the series NAME and picked up the first cached CATEGORY
            # value, so on a chart whose series are countries over a year axis every
            # country was read as the year 2019. The check then asserted that five
            # country colours were all "the colour of 2019" and contradicted itself
            # against the real year charts — a false invariant that would have blocked
            # the genuine fix in fix_year_colours.py, which had the identical defect.
            m = re.search(r"<c:tx>(?:(?!</c:tx>).)*?<c:v>\s*(\d{4})", s, re.S)
            if not m:
                continue
            sp = re.search(r"<c:spPr>.*?</c:spPr>", s, re.S)
            c = re.search(r'srgbClr val="([0-9A-Fa-f]{6})"', sp.group(0)) if sp else None
            if not c:
                continue
            y, col = int(m.group(1)), c.group(1).upper()
            if y in year_colour and year_colour[y][0] != col:
                errs.append(f"{base}: {y} is {col} here but {year_colour[y][0]} in "
                            f"{year_colour[y][1]} — a year must be one colour everywhere")
            year_colour.setdefault(y, (col, base))

    # 4 ----------------------------------------------------------------------------
    wb = z.read("xl/workbook.xml").decode()
    rm = dict(re.findall(r'Id="rId(\d+)"[^>]*Target="([^"]+)"',
                         z.read("xl/_rels/workbook.xml.rels").decode()))
    selected = []
    for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="rId(\d+)"', wb):
        p = "xl/" + rm[m.group(2)].lstrip("/")
        if p in z.namelist() and 'tabSelected="1"' in z.read(p).decode():
            selected.append(m.group(1))
    if len(selected) != 1:
        errs.append(f"{len(selected)} sheets are selected ({', '.join(selected) or 'none'}) "
                    f"— more than one opens the workbook GROUPED, which blocks table edits")

    return errs


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else WB
    errs = check(path)
    print(f"CHART QUALITY: {os.path.basename(path)}")
    if not errs:
        print("  PASS — no known presentation faults")
        return 0
    for e in errs:
        print("  ✗", e)
    print(f"  {len(errs)} problem(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
