"""One colour per YEAR, the same in every chart.

THE BUG
    Series colours were assigned by POSITION in the series list. The line charts carry
    eight series (2019 … 2026 YTD) and the annual bar charts seven (2019 … 2025), so the
    bar charts started one step further along the palette and every year was shifted:
    2019 was grey-green on Fig 2 and blue-grey on Fig 5; 2025 was teal on Fig 2 and navy
    on Fig 5. A reader comparing two exhibits had no reliable colour cue at all — which
    is the entire job of a year legend. Chart 19 used a third palette of its own.

THE RULE
    Colour is a property of the YEAR, not of where the series happens to sit. YEAR_COLOUR
    below is the single map; every year-series chart is repainted from it.

    Navy (the house emphasis colour) lands on the CURRENT year, so "navy = now" reads the
    same everywhere. A chart that stops at the last complete year simply has no navy — it
    is not showing "now" — which is more honest than each chart calling its own last
    series navy regardless of which year that is.

Applies only to charts whose series are years; country- and technology-series charts are
left alone, since their legends are about something else entirely.
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg
from completeness import cutoffs

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")

# The house ramp, oldest -> newest, ending on NAVY for the current year. Taken from the
# eight-series line charts, which were already the de-facto reference.
RAMP = ["C9D2CD", "9AA5B1", "8A1E41", "CC9F53", "3D664A", "ACBFB7", "5FA1AD", "2E3E80"]

_LCY = cutoffs()["last_complete_year"]
CURRENT = _LCY + 1                      # the in-progress "YTD" year
# oldest shown year -> ... -> current year, mapped onto the ramp
_YEARS = list(range(CURRENT - len(RAMP) + 1, CURRENT + 1))
YEAR_COLOUR = dict(zip(_YEARS, RAMP))


def series_year(ser: str, window: list[int], idx: int) -> int | None:
    """Which year does this series represent?"""
    # literal name, e.g. "2024" or "2026 YTD"
    #
    # The `(?:(?!</c:tx>).)*?` guard is load-bearing and was added 2026-08-03 to fix a
    # real defect. A plain `.*?` here does not stop at </c:tx>: on a chart whose series
    # are COUNTRIES and whose category axis is years, it ran past the name and matched
    # the first cached CATEGORY value instead. Fig 1 and Fig 3 both look like that, so
    # all five of their country series resolved to 2019 and were painted the identical
    # oldest-year grey — five countries, one colour, in the line and in the legend.
    # They should never have been touched at all: tempered, the match fails, the charts
    # are skipped, and they keep the distinct country colours they were built with.
    m = re.search(r"<c:tx>(?:(?!</c:tx>).)*?<c:v>\s*(\d{4})", ser, re.S)
    if m:
        return int(m.group(1))
    # rolling-window charts take their name from a Status cell, so the year comes from
    # the window this build published — same list the labels are drawn from.
    if re.search(r"<c:tx>(?:(?!</c:tx>).)*?<c:f>Status!", ser, re.S) and idx < len(window):
        return window[idx]
    return None


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    window = cfg.window_years(_LCY)
    repainted = skipped = 0
    changed = []

    for name in sorted(n for n in order if re.match(r"xl/charts/chart\d+\.xml$", n)):
        xml = parts[name].decode()
        sers = re.findall(r"<c:ser>.*?</c:ser>", xml, re.S)
        years = [series_year(s, window, i) for i, s in enumerate(sers)]
        if not sers or any(y is None for y in years):
            skipped += 1
            continue                     # not a year-series chart — leave it alone

        n_here = 0
        for s, y in zip(sers, years):
            col = YEAR_COLOUR.get(y)
            if not col:
                continue
            new = re.sub(r'(<c:spPr>.*?)srgbClr val="[0-9A-Fa-f]{6}"(.*?</c:spPr>)',
                         lambda m: f'{m.group(1)}srgbClr val="{col}"{m.group(2)}',
                         s, count=0, flags=re.S)
            if new != s:
                xml = xml.replace(s, new, 1)
                n_here += 1
        if n_here:
            parts[name] = xml.encode()
            repainted += n_here
            changed.append(f"{os.path.basename(name)}({n_here})")

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  year colours unified: {repainted} series across {len(changed)} chart(s) "
          f"({skipped} non-year charts untouched)")
    if changed:
        print(f"    {', '.join(changed)}")


if __name__ == "__main__":
    main()
