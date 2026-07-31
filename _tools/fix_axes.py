"""Move category-axis labels out of the plot, and say what the x-axis actually is.

TWO FAULTS, both inherited from the base Redburn charts.

1. `<c:tickLblPos val="nextTo"/>` puts the category labels next to the AXIS LINE. On a
   chart with negative values that line sits in the middle of the plot, so on Fig 5 the
   technology names were printed across the negative bars — over Solar, Onshore wind and
   Offshore wind, which are the whole point of a capture-price exhibit. `low` pins the
   labels below the plot area instead, where they belong, whatever the data does.
   Applied to every category axis: where there are no negatives the two are identical,
   so this cannot regress a chart that was already fine.

2. Several charts have a bare 0-23 or 1-366 x-axis and no title, so the reader is left to
   infer what the numbers are. They are hour-of-day (UTC) and day-of-year respectively —
   both meaningful and both worth keeping, but only if they say so.

Runs late in the build, after every chart exists and before validation.
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")

# chart -> what its category axis actually measures
AXIS_TITLE = {
    2: "hour of day (UTC)",
    8: "hour of day (UTC)",
    10: "hour of day (UTC)",
    11: "hour of day (UTC)",
    15: "hour of day (UTC)",
    4: "day of year",
    5: "day of year",
    13: "day of year",
}

A = "http://schemas.openxmlformats.org/drawingml/2006/main"
C = "http://schemas.openxmlformats.org/drawingml/2006/chart"


def axis_title_xml(text: str) -> str:
    """A minimal <c:title> for a category axis, in the house grey/Arial."""
    return (
        '<c:title><c:tx><c:rich>'
        f'<a:bodyPr rot="0" vert="horz"/><a:lstStyle/>'
        f'<a:p><a:pPr><a:defRPr sz="800" b="0">'
        f'<a:solidFill><a:srgbClr val="595959"/></a:solidFill>'
        f'<a:latin typeface="Arial"/></a:defRPr></a:pPr>'
        f'<a:r><a:rPr lang="en-GB" sz="800" b="0">'
        f'<a:solidFill><a:srgbClr val="595959"/></a:solidFill>'
        f'<a:latin typeface="Arial"/></a:rPr><a:t>{text}</a:t></a:r></a:p>'
        '</c:rich></c:tx><c:overlay val="0"/></c:title>'
    )


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    moved = titled = 0
    for name in sorted(n for n in order if re.match(r"xl/charts/chart\d+\.xml$", n)):
        num = int(re.search(r"chart(\d+)", name).group(1))
        xml = parts[name].decode()

        def fix_cat(m):
            nonlocal moved, titled
            ax = m.group(0)
            new, n = re.subn(r'<c:tickLblPos val="nextTo"/>',
                             '<c:tickLblPos val="low"/>', ax)
            moved += n
            # a title must sit directly after <c:axPos/> in CT_CatAx
            if num in AXIS_TITLE and "<c:title>" not in new:
                new = re.sub(r'(<c:axPos val="\w"/>)',
                             r"\1" + axis_title_xml(AXIS_TITLE[num]), new, count=1)
                titled += 1
            return new

        xml = re.sub(r"<c:catAx>.*?</c:catAx>", fix_cat, xml, flags=re.S)
        parts[name] = xml.encode()

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  category labels moved below the plot on {moved} axis/axes; "
          f"{titled} x-axis title(s) added")


if __name__ == "__main__":
    main()
