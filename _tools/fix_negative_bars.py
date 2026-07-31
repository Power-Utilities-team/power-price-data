"""Stop negative bars rendering as hollow white outlines.

THE ACTUAL DEFECT Fred reported as "transparent/empty white bars".

Every bar series in the base Redburn workbook carries `<c:invertIfNegative val="1"/>`.
That flag tells Excel to draw negative values in an INVERTED fill, and when no explicit
negative fill is supplied the inverted fill is white — so on Fig 5 every technology that
captures BELOW baseload (Solar, Onshore wind, Offshore wind: the whole point of the
exhibit) draws as an empty outline while the positives are solid. The chart reads as
though the data were missing, precisely where the most important data is.

It is a rendering flag, not a data problem, which is why it survived every data-level
fix: the six leftover technologies (2026-07-22) and German nuclear (2026-07-30) were both
real defects, but neither was THIS one. Setting the flag to 0 makes a negative bar use the
same fill as a positive one, so the series colour means "year" everywhere, as intended.

Applies to EVERY bar series in every chart, not just the three annual ones, so any future
chart with negative values inherits the fix.
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    total = 0
    touched = []
    for name in sorted(n for n in order if re.match(r"xl/charts/chart\d+\.xml$", n)):
        xml = parts[name].decode()
        if "<c:barChart>" not in xml:
            continue
        new, n = re.subn(r'<c:invertIfNegative val="1"/>',
                         '<c:invertIfNegative val="0"/>', xml)
        if n:
            parts[name] = new.encode()
            total += n
            touched.append(f"{os.path.basename(name)}({n})")

    if not total:
        print("  no inverted-negative series found — nothing to do")
        return

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  negative bars now use the series fill — {total} series across "
          f"{len(touched)} chart(s): {', '.join(touched)}")


if __name__ == "__main__":
    main()
