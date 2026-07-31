"""Point the seven LINE charts at the shared rolling window, so they survive the year turn.

Same problem as the annual bar charts: a year is a chart SERIES, the series count is fixed
when the workbook is built, and Power Query writes values into cells but cannot create a
series. So a workbook built in 2026 keeps showing 2019-2026 for ever.

WHY NOT RESERVE SPARE SERIES HERE
    On a LINE chart an empty series costs no width — unlike a bar chart, where it claims a
    slot and compresses the bars. So reserving looked free. Probing it showed otherwise:
    the reserved series still produced a legend entry (rendered "Column J"), which is the
    dead-entry problem Fred asked to avoid. The rolling window adds NO series at all, so
    that failure mode is impossible by construction.

WHY ONE SHARED TAB
    These seven charts read from five different sheets. Five more window tabs would mean
    five more chances at the content-types / dangling-drawing / stale-rels class of fault
    that produced three separate broken packages on 2026-07-31. One tab, one query, one
    set of joins to get right — and the row counts differ (24 hours, 101 percentiles, 366
    days) only because the short columns leave blanks, which a line chart does not draw.

Slot 1..7 are the last seven COMPLETE years, slot 8 the current year-to-date, matching
what these charts show today. Names come from the Status row's rolling labels, so the
legend advances with the data.

Runs after add_power_queries.py (which creates the Line_Window table and the Status row)
and before move_status_first / drop_readme_sheet, which re-assert the sheet mapping.
"""
from __future__ import annotations

import os
import re
import zipfile

import config as cfg
from completeness import cutoffs

WB = os.path.join(cfg.ROOT, "outputs", "HourlyPowerData.xlsx")
WINDOW_TAB = "Line_Window"
STATUS_SHEET = "Status"

# chart -> (column prefix in line_windows.csv, country)
CHARTS = {
    2: ("i", "DE"),      # Fig 2 intraday, indexed (Germany)
    10: ("i", "ES"),     # Fig 2 intraday, indexed (Spain)
    11: ("a", "DE"),     # Fig 2 intraday, absolute (Germany)
    4: ("c", "DE"),      # Fig 3 cumulative near-negative (Germany)
    13: ("c", "ES"),     # Fig 3 cumulative near-negative (Spain)
    5: ("d", "PT"),      # Fig 4 duration curve (Portugal)
    19: ("n", "DE"),     # D netload duck (Germany)
}
SLOTS = 8                # 7 complete years + the current YTD

# Fig 1 and Fig 3 are transposed: YEARS are the categories and the series are countries.
# chart -> column prefix in line_windows.csv. Their 5 series each read the same 7 rows,
# and the category axis reads the shared win_year column, so the labels roll with them.
CATEGORY_CHARTS = {1: "f1", 3: "f3"}
CATEGORY_COUNTRIES = ["Ge", "Sp", "Po", "Fr", "It"]


def header_of(parts, part):
    x = parts[part].decode()
    row1 = re.search(r'<row r="1"[^>]*>(.*?)</row>', x, re.S)
    if not row1:
        return {}
    return {m.group(1): m.group(2) for m in
            re.finditer(r'<c r="([A-Z]+)1"[^>]*><is><t>([^<]*)</t></is></c>', row1.group(1))}


def sheet_parts(parts):
    wb = parts["xl/workbook.xml"].decode()
    rm = dict(re.findall(r'Id="rId(\d+)"[^>]*Target="([^"]+)"',
                         parts["xl/_rels/workbook.xml.rels"].decode()))
    return {m.group(1): "xl/" + rm[m.group(2)].lstrip("/")
            for m in re.finditer(r'<sheet name="([^"]+)"[^>]*r:id="rId(\d+)"', wb)}


def main():
    zin = zipfile.ZipFile(WB)
    order = zin.namelist()
    parts = {n: zin.read(n) for n in order}
    zin.close()

    sp = sheet_parts(parts)
    if WINDOW_TAB not in sp:
        raise SystemExit(f"{WINDOW_TAB} tab missing — add_power_queries must run first")

    lcy = cutoffs()["last_complete_year"]
    years = cfg.window_years(lcy) + [lcy + 1]

    # the rolling labels live on the Status row; slot 8 (current YTD) has no w-label, so
    # it keeps its literal "<year> YTD" name — that text is regenerated every build anyway
    shdr = header_of(parts, sp[STATUS_SHEET])
    label = {}
    for letter, name in shdr.items():
        m = re.fullmatch(r"w(\d+)", str(name or ""))
        if m:
            label[int(m.group(1))] = f"${letter}$2"

    whdr = header_of(parts, sp[WINDOW_TAB])
    col_of = {v: k for k, v in whdr.items()}

    # how many data rows the window tab holds, so ranges do not run past it
    wx = parts[sp[WINDOW_TAB]].decode()
    last_row = max(int(m) for m in re.findall(r'<row r="(\d+)"', wx))

    done = []
    for num, (tag, country) in sorted(CHARTS.items()):
        p = f"xl/charts/chart{num}.xml"
        xml = parts[p].decode()
        sers = re.findall(r"<c:ser>.*?</c:ser>", xml, re.S)
        if len(sers) != SLOTS:
            raise SystemExit(f"chart{num}: {len(sers)} series, expected {SLOTS} — the "
                             f"window and the chart must match exactly, or a series "
                             f"would plot the wrong year under the right label")

        # keep each chart's own row span: a duration curve has 101 points, an intraday
        # profile 24, and the shared tab is as long as the longest
        rng = re.search(r"<c:val>.*?\$[A-Z]+\$(\d+):\$[A-Z]+\$(\d+)", sers[0], re.S)
        r0, r1 = int(rng.group(1)), int(rng.group(2))
        r1 = min(r1, last_row)

        for i, s in enumerate(sers, start=1):
            col = col_of.get(f"{tag}_{country}_w{i}")
            if not col:
                raise SystemExit(f"{WINDOW_TAB}: no column {tag}_{country}_w{i}")
            new = s
            if i in label:                      # slots 1..7 take the rolling label
                new = re.sub(
                    r"<c:tx>.*?</c:tx>",
                    f'<c:tx><c:strRef><c:f>{STATUS_SHEET}!{label[i]}</c:f>'
                    f'<c:strCache><c:ptCount val="1"/>'
                    f'<c:pt idx="0"><c:v>{years[i-1]}</c:v></c:pt>'
                    f'</c:strCache></c:strRef></c:tx>',
                    new, count=1, flags=re.S)
            new = re.sub(r"(<c:val>.*?<c:f>)[^<]*(</c:f>)",
                         rf"\g<1>{WINDOW_TAB}!${col}${r0}:${col}${r1}\g<2>",
                         new, count=1, flags=re.S)
            xml = xml.replace(s, new, 1)

        parts[p] = xml.encode()
        done.append(f"chart{num}({tag}_{country})")

    # --- the two category-axis charts ------------------------------------------
    for num, tag in sorted(CATEGORY_CHARTS.items()):
        p = f"xl/charts/chart{num}.xml"
        xml = parts[p].decode()
        sers = re.findall(r"<c:ser>.*?</c:ser>", xml, re.S)
        if len(sers) != len(CATEGORY_COUNTRIES):
            raise SystemExit(f"chart{num}: {len(sers)} series, expected "
                             f"{len(CATEGORY_COUNTRIES)} country series")
        ycol = col_of.get("win_year")
        if not ycol:
            raise SystemExit(f"{WINDOW_TAB}: no win_year column")
        n = len(cfg.window_years(lcy))          # 7 rows, one per window year
        for s_i, (s, cc) in enumerate(zip(sers, CATEGORY_COUNTRIES)):
            vcol = col_of.get(f"{tag}_{cc}_w")
            if not vcol:
                raise SystemExit(f"{WINDOW_TAB}: no column {tag}_{cc}_w")
            new = s
            # categories: the rolling year labels
            new = re.sub(r"(<c:cat>.*?<c:f>)[^<]*(</c:f>)",
                         rf"\g<1>{WINDOW_TAB}!${ycol}$2:${ycol}${n + 1}\g<2>",
                         new, count=1, flags=re.S)
            new = re.sub(r"(<c:val>.*?<c:f>)[^<]*(</c:f>)",
                         rf"\g<1>{WINDOW_TAB}!${vcol}$2:${vcol}${n + 1}\g<2>",
                         new, count=1, flags=re.S)
            xml = xml.replace(s, new, 1)
        parts[p] = xml.encode()
        done.append(f"chart{num}({tag}, categories)")

    tmp = WB + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in order:
            zo.writestr(n, parts[n])
    os.replace(tmp, WB)
    print(f"  line charts on the rolling window: {', '.join(done)}")


if __name__ == "__main__":
    main()
